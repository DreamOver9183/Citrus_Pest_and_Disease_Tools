import os
import csv
from fastapi import APIRouter
from app.services.session_manager import ACTIVE_SESSIONS, SESSIONS_LOCK
from app.core.config import TEMP_DIR
from app.core.envelope import ApiException, ApiResponse, ok
from app.schemas import MetricsPayload
from PIL import Image, ImageDraw, ImageFont

router = APIRouter()

CHART_TITLES = {
    "ssd_train_loss": "Training Loss",
    "ssd_val_loss": "Validation Loss",
    "ssd_mAP": "mAP (IoU=0.5:0.95)",
    "ssd_mAP_50": "mAP@50 (IoU=0.5)"
}

CSV_FIELD_MAPPING = {
    "ssd_train_loss": "train_loss",
    "ssd_val_loss": "val_loss",
    "ssd_mAP": "mAP",
    "ssd_mAP_50": "mAP_50"
}

CHART_COLORS = {
    "ssd_train_loss": "#F97316", # Orange
    "ssd_val_loss": "#6366F1",   # Indigo
    "ssd_mAP": "#14B8A6",        # Teal
    "ssd_mAP_50": "#A855F7"      # Purple
}

@router.get("/generate-chart", response_model=ApiResponse[MetricsPayload])
def generate_chart(session_id: str, chart_type: str):
    """用 Pillow 手繪 SSD 的訓練曲線（YOLO 走 /api/metrics 的裁切路徑）。"""
    with SESSIONS_LOCK:
        session_data = ACTIVE_SESSIONS.get(session_id)
        session_data = dict(session_data) if session_data else None

    if session_data is None:
        raise ApiException("not_found", "找不到指定的模型 Session")

    csv_path = session_data.get("metrics_csv_path")
    if not csv_path or not os.path.exists(csv_path):
        raise ApiException("precondition_failed", "該模型沒有找到訓練指標 CSV 記錄。")

    if chart_type not in CHART_TITLES:
        raise ApiException("validation_error", f"未知的圖表類型: {chart_type}")
        
    # Read CSV
    epochs = []
    values = []
    
    target_field = CSV_FIELD_MAPPING[chart_type]
    
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    epochs.append(int(row["epoch"]))
                    values.append(float(row[target_field]))
                except (ValueError, KeyError):
                    continue
    except Exception as e:
        raise ApiException("internal_error", f"讀取 CSV 發生錯誤: {e}")
        
    if not epochs or not values:
        raise ApiException("precondition_failed", "CSV 中沒有有效的數據。")
        
    # Draw chart with Pillow
    target_name = f"chart_{session_id}_{chart_type}.png"
    target_path = os.path.join(TEMP_DIR, target_name)
    
    try:
        width, height = 700, 450
        bg_color = (13, 17, 23) # #0d1117 (Dark background)
        text_color = (201, 209, 217) # #c9d1d9
        grid_color = (48, 54, 61) # #30363d
        
        # PIL can handle hex string colors from modern versions, but better safe with RGB or just text
        line_color = CHART_COLORS[chart_type]
        
        img = Image.new("RGB", (width, height), color=bg_color)
        draw = ImageDraw.Draw(img)
        
        # Margins
        margin_left = 60
        margin_right = 30
        margin_top = 50
        margin_bottom = 50
        
        plot_width = width - margin_left - margin_right
        plot_height = height - margin_top - margin_bottom
        
        # Calculate scales
        min_val = min(values)
        max_val = max(values)
        val_range = max_val - min_val
        if val_range == 0:
            val_range = 1
            min_val -= 0.5
            max_val += 0.5
            
        # Add 5% padding
        min_val -= val_range * 0.05
        max_val += val_range * 0.05
        val_range = max_val - min_val
        
        min_epoch = min(epochs)
        max_epoch = max(epochs)
        epoch_range = max_epoch - min_epoch if max_epoch > min_epoch else 1
        
        def get_coords(e, v):
            x = margin_left + ((e - min_epoch) / epoch_range) * plot_width
            y = margin_top + plot_height - ((v - min_val) / val_range) * plot_height
            return (x, y)
            
        # Draw grid & axes
        # Y-axis
        for i in range(5):
            val = min_val + (val_range * i / 4)
            y = margin_top + plot_height - (plot_height * i / 4)
            draw.line([(margin_left, y), (width - margin_right, y)], fill=grid_color, width=1)
            # Use basic default font (doesn't support size in basic draw.text without loading font file, so skip size)
            draw.text((margin_left - 45, y - 5), f"{val:.4f}", fill=text_color)
            
        # X-axis
        step = max(1, epoch_range // 10)
        for e in range(min_epoch, max_epoch + 1, step):
            x = margin_left + ((e - min_epoch) / epoch_range) * plot_width
            draw.line([(x, margin_top), (x, height - margin_bottom)], fill=grid_color, width=1)
            draw.text((x - 10, height - margin_bottom + 10), str(e), fill=text_color)
            
        # Draw title
        draw.text((margin_left, margin_top - 30), CHART_TITLES[chart_type], fill=text_color)
        
        # Draw line
        points = [get_coords(e, v) for e, v in zip(epochs, values)]
        if len(points) > 1:
            draw.line(points, fill=line_color, width=3)
            
        # Draw Phase boundary if exists (Epoch 5)
        if 5 in epochs and max_epoch >= 5:
            phase_x = get_coords(5, min_val)[0]
            draw.line([(phase_x, margin_top), (phase_x, height - margin_bottom)], fill=(255, 255, 255), width=2)
            draw.text((phase_x + 5, margin_top + 10), "Phase 2 Unfrozen", fill=(255, 255, 255))
            
        # Draw best point (max for mAP, min for loss)
        if "loss" in chart_type:
            best_val = min(values)
            best_idx = values.index(best_val)
        else:
            best_val = max(values)
            best_idx = values.index(best_val)
            
        best_e = epochs[best_idx]
        bx, by = get_coords(best_e, best_val)
        draw.ellipse([(bx-4, by-4), (bx+4, by+4)], fill="white", outline=line_color, width=2)
        draw.text((bx + 10, by - 10), f"Best: {best_val:.4f} (E{best_e})", fill="white")
            
        img.save(target_path)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise ApiException("internal_error", f"繪製圖表失敗: {e}")
        
    source_path_clean = os.path.abspath(csv_path).replace('\\', '/')
    return ok({
        "url": f"/static/{target_name}",
        "source_path": f"{source_path_clean} (指標: {chart_type})",
    })
