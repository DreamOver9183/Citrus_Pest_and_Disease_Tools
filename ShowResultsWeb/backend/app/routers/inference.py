import os
import uuid
import shutil
from typing import Union
from fastapi import APIRouter, File, UploadFile
from app.services.session_manager import ACTIVE_SESSIONS
from app.services.model_service import model_manager
from app.services.device_service import device_service
from app.core.config import EXTRACTED_RUNS_DIR, TEMP_DIR, UPLOAD_TEMP_DIR
from app.schemas import InferenceResponse, ErrorResponse

router = APIRouter()

@router.post("/inference", response_model=Union[InferenceResponse, ErrorResponse], response_model_exclude_unset=True)
def run_inference(
    session_id: str, 
    file: UploadFile = File(...),
    conf: float = 0.25
):
    """
    執行 YOLO 離線推論。使用 def 確保在 ThreadPool 執行。
    """
    if session_id not in ACTIVE_SESSIONS:
        return {"status": "error", "message": "無效的模型 Session ID。"}
        
    model_data = ACTIVE_SESSIONS[session_id]
    model_path = model_data["weights_path"]
    
    if not os.path.exists(model_path):
        return {
            "status": "error", 
            "message": f"找不到權重檔案，請確認實體路徑: {model_path}"
        }
                
    model_arch = model_data.get("model_arch", "yolo")
    
    model_manager.load_model(model_path, device=device_service.get_current_device(), arch=model_arch)
    
    # 儲存上傳的檔案
    os.makedirs(UPLOAD_TEMP_DIR, exist_ok=True)
    temp_infer_file = os.path.join(UPLOAD_TEMP_DIR, f"{uuid.uuid4().hex}_{file.filename}")
    with open(temp_infer_file, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    # Save a copy to extracted_runs/images for persistence and display in the file tree
    images_dir = os.path.join(EXTRACTED_RUNS_DIR, "images")
    os.makedirs(images_dir, exist_ok=True)
    persistent_image_path = os.path.join(images_dir, file.filename)
    try:
        shutil.copy(temp_infer_file, persistent_image_path)
    except Exception as e:
        print(f"[FastAPI] Error copying persistent image: {e}")
        
    try:
        results = model_manager.predict(temp_infer_file, conf=conf)
        
        unique_id = uuid.uuid4().hex
        output_filename = f"pred_{unique_id}_{file.filename}"
        output_path = os.path.join(TEMP_DIR, output_filename)
        
        counts = {}
        total_counts = 0
        
        # Check if it's SSD mock result
        if hasattr(results[0], "json_data"):
            # SSD Result
            import json
            # Move from the temp path to our unique output_path
            shutil.move(results[0].save_path, output_path)
            
            for item in results[0].json_data:
                cls_name = item["name"]
                counts[cls_name] = counts.get(cls_name, 0) + 1
                total_counts += 1
        else:
            # YOLO Result
            results[0].save(filename=output_path)
            
            class_names = model_manager.current_model.names
            if results[0].boxes is not None:
                for box in results[0].boxes:
                    cls_id = int(box.cls[0].item())
                    cls_name = class_names.get(cls_id, str(cls_id))
                    counts[cls_name] = counts.get(cls_name, 0) + 1
                    total_counts += 1
                
        return {
            "status": "success",
            "url": f"/static/{output_filename}",
            "original_url": f"/images/{file.filename}",
            "counts": total_counts,
            "detections": counts,
            "device_used": model_manager.get_current_device_label()
        }
    except Exception as e:
        return {"status": "error", "message": f"推論失敗: {str(e)}"}
    finally:
        if temp_infer_file and os.path.exists(temp_infer_file):
            try:
                os.remove(temp_infer_file)
            except Exception:
                pass
