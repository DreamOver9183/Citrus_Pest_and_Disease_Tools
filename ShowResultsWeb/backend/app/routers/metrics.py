import os
import shutil
from typing import Union
from fastapi import APIRouter
from app.services.session_manager import ACTIVE_SESSIONS
from app.core.config import TEMP_DIR
from app.utils.image_cropper import crop_metric_image
from app.schemas import MetricsResponse, ErrorResponse

router = APIRouter()

@router.get("/metrics", response_model=Union[MetricsResponse, ErrorResponse], response_model_exclude_unset=True)
def get_metrics(session_id: str, metric_type: str = "mAP50"):
    """
    同步路由處理影像與指標讀取。根據 session_id 與指標類型動態回傳 URL 與原始實體路徑。
    """
    if session_id not in ACTIVE_SESSIONS:
        return {"status": "error", "message": "無效的 Session ID。"}
        
    session_data = ACTIVE_SESSIONS[session_id]
    dir_path = session_data["dir_path"]
    
    # 判定是否為獨立圖表 (不需像素裁剪)
    standalone_metrics = {
        "confusion_matrix": "confusion_matrix.png",
        "confusion_matrix_normalized": "confusion_matrix_normalized.png",
        "BoxF1_curve": "BoxF1_curve.png",
        "BoxP_curve": "BoxP_curve.png",
        "BoxPR_curve": "BoxPR_curve.png",
        "BoxR_curve": "BoxR_curve.png"
    }
    
    if metric_type in standalone_metrics:
        filename = standalone_metrics[metric_type]
        src = os.path.join(dir_path, filename).replace("\\", "/")

        if not os.path.exists(src):
            return {"status": "error", "message": f"該模型未產出獨立圖表：{filename}"}
            
        target_name = f"{session_id}_{filename}"
        target_path = os.path.join(TEMP_DIR, target_name)
        shutil.copy(src, target_path)
        return {
            "status": "success",
            "url": f"/static/{target_name}",
            "source_path": os.path.abspath(src).replace("\\", "/")
        }
        
    # 一般結果圖 results.png 裁剪
    src = session_data["results_png"]
    if not src or not os.path.exists(src):
        return {"status": "error", "message": f"該模型未產出結果指標圖表 results.png。"}
        
    target_name = f"{session_id}_{metric_type}.png"
    target_path = os.path.join(TEMP_DIR, target_name)
    
    crop_metric_image(src, target_path, metric_type)
    source_path_clean = os.path.abspath(src).replace('\\', '/')
    return {
        "status": "success",
        "url": f"/static/{target_name}",
        "source_path": f"{source_path_clean} (指標: {metric_type})"
    }
