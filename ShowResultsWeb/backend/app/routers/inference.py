"""單張影像的推論。

`session_id` 與 `conf` 從 query param 改成 **multipart 表單欄位**：這個端點本來就必須是
multipart（要傳影像位元組），把參數留在 query 等於同一個請求有兩套參數傳遞方式。
統一之後的規則很單純——POST 的參數一律在 body 裡。
"""
import os
import shutil
import uuid

from fastapi import APIRouter, File, Form, UploadFile

from app.core.config import EXTRACTED_RUNS_DIR, TEMP_DIR, UPLOAD_TEMP_DIR
from app.core.envelope import ApiException, ApiResponse, ok
from app.schemas import InferencePayload
from app.services.device_service import device_service
from app.services.model_service import model_manager
from app.services.session_manager import ACTIVE_SESSIONS, SESSIONS_LOCK

router = APIRouter()


@router.post("/inference", response_model=ApiResponse[InferencePayload])
def run_inference(
    file: UploadFile = File(...),
    session_id: str = Form(...),
    conf: float = Form(0.25),
):
    """執行離線推論。使用同步 def 確保在 FastAPI 的 threadpool 上執行。"""
    with SESSIONS_LOCK:
        model_data = ACTIVE_SESSIONS.get(session_id)
        model_data = dict(model_data) if model_data else None

    if model_data is None:
        raise ApiException("not_found", "找不到指定的模型 Session")

    model_path = model_data["weights_path"]
    if not os.path.exists(model_path):
        raise ApiException(
            "precondition_failed",
            f"找不到權重檔案，請確認實體路徑: {model_path}",
        )

    model_arch = model_data.get("model_arch", "yolo")
    model_manager.load_model(model_path, device=device_service.get_current_device(), arch=model_arch)

    os.makedirs(UPLOAD_TEMP_DIR, exist_ok=True)
    temp_infer_file = os.path.join(UPLOAD_TEMP_DIR, f"{uuid.uuid4().hex}_{file.filename}")
    with open(temp_infer_file, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # 複製一份到 extracted_runs/images 供前端的原圖對照顯示
    images_dir = os.path.join(EXTRACTED_RUNS_DIR, "images")
    os.makedirs(images_dir, exist_ok=True)
    try:
        shutil.copy(temp_infer_file, os.path.join(images_dir, file.filename))
    except Exception as exc:  # noqa: BLE001
        print(f"[FastAPI] Error copying persistent image: {exc}")

    try:
        results = model_manager.predict(temp_infer_file, conf=conf)

        output_filename = f"pred_{uuid.uuid4().hex}_{file.filename}"
        output_path = os.path.join(TEMP_DIR, output_filename)

        counts = {}
        total_counts = 0

        if hasattr(results[0], "json_data"):
            # SSD 的模擬結果物件：影像已由 model_service 寫在 save_path，搬到我們的落點
            shutil.move(results[0].save_path, output_path)
            for item in results[0].json_data:
                cls_name = item["name"]
                counts[cls_name] = counts.get(cls_name, 0) + 1
                total_counts += 1
        else:
            results[0].save(filename=output_path)
            class_names = model_manager.current_model.names
            if results[0].boxes is not None:
                for box in results[0].boxes:
                    cls_id = int(box.cls[0].item())
                    cls_name = class_names.get(cls_id, str(cls_id))
                    counts[cls_name] = counts.get(cls_name, 0) + 1
                    total_counts += 1

        return ok({
            "url": f"/static/{output_filename}",
            "original_url": f"/images/{file.filename}",
            "counts": total_counts,
            "detections": counts,
            "device_used": model_manager.get_current_device_label(),
        })
    except ApiException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ApiException("internal_error", f"推論失敗: {exc}")
    finally:
        if temp_infer_file and os.path.exists(temp_infer_file):
            try:
                os.remove(temp_infer_file)
            except Exception:  # noqa: BLE001
                pass
