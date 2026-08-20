import os
import uuid
import shutil
from typing import Union
from fastapi import APIRouter, File, UploadFile, Form, HTTPException
from app.services.export_service import purge_exports_for_session
from app.services.session_manager import ACTIVE_SESSIONS, SESSIONS_LOCK, save_sessions_to_disk, delete_session
from app.utils.zip_handler import extract_and_index, ZipIndexError, index_single_weight
from app.core.config import EXTRACTED_RUNS_DIR, UPLOAD_TEMP_DIR, MAX_SESSIONS
from app.schemas import SessionsResponse, UploadResponse, ErrorResponse

router = APIRouter()

SUPPORTED_WEIGHT_EXTENSIONS = {".pt", ".pth", ".onnx", ".tflite", ".engine", ".torchscript"}

FORMAT_LABELS = {
    ".pt": "PyTorch",
    ".pth": "SSDLite-MobileNetV3 (PyTorch)",
    ".onnx": "ONNX",
    ".tflite": "TFLite",
    ".engine": "TensorRT",
    ".torchscript": "TorchScript",
    ".zip": "ZIP Archive"
}

@router.get("/sessions", response_model=SessionsResponse, response_model_exclude_unset=True)
def get_sessions():
    with SESSIONS_LOCK:
        return {
            "status": "success",
            "sessions": dict(ACTIVE_SESSIONS)
        }

@router.post("/update-session-name", response_model=SessionsResponse, response_model_exclude_unset=True)
def update_session_name(session_id: str = Form(...), custom_name: str = Form(...)):
    """更新指定 Session 的自訂顯示名稱"""
    with SESSIONS_LOCK:
        if session_id not in ACTIVE_SESSIONS:
            raise HTTPException(status_code=404, detail="Session not found")
        ACTIVE_SESSIONS[session_id]["custom_name"] = custom_name
        sessions_snapshot = dict(ACTIVE_SESSIONS)
    save_sessions_to_disk()
    return {
        "status": "success",
        "sessions": sessions_snapshot
    }

@router.post("/delete-session", response_model=SessionsResponse, response_model_exclude_unset=True)
def delete_session_route(session_id: str = Form(...)):
    """刪除指定 Session 並清理本地解壓硬碟目錄與其匯出產物"""
    try:
        delete_session(session_id)
        # 匯出清理放在 router 而非 session_manager：後者已 import model_service，
        # 若再與 export_service 互相 import 會形成循環；而且在 SESSIONS_LOCK 內取得
        # EXPORT_JOBS_LOCK 會製造鎖序風險。delete_session() 回來時鎖已釋放。
        purge_exports_for_session(session_id)
        with SESSIONS_LOCK:
            sessions_snapshot = dict(ACTIVE_SESSIONS)
        return {
            "status": "success",
            "sessions": sessions_snapshot
        }
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")

@router.post("/upload-zip", response_model=Union[UploadResponse, ErrorResponse], response_model_exclude_unset=True)
def upload_zip(file: UploadFile = File(...)):
    """向後相容別名：重定向至 /api/upload-model"""
    return upload_model(file=file)

@router.post("/upload-model", response_model=Union[UploadResponse, ErrorResponse], response_model_exclude_unset=True)
def upload_model(file: UploadFile = File(...)):
    """
    統一的模型上傳端點，支援 ZIP 訓練結果壓縮包與單一權重檔案。
    單一權重檔案格式：.pt, .pth, .onnx, .tflite, .engine, .torchscript
    """
    _, ext = os.path.splitext(file.filename)
    ext = ext.lower()
    
    # 若為 ZIP 格式，走原有的 ZIP 解析流程
    if ext == ".zip":
        return _handle_zip_upload(file)
    
    # 若為支援的單一權重格式
    if ext in SUPPORTED_WEIGHT_EXTENSIONS:
        return _handle_single_weight_upload(file, ext)
    
    # 不支援的格式
    supported_list = ", ".join(sorted(SUPPORTED_WEIGHT_EXTENSIONS | {".zip"}))
    return {
        "status": "error",
        "message": f"不支援的檔案格式 '{ext}'。支援格式：{supported_list}"
    }

def _handle_single_weight_upload(file: UploadFile, ext: str):
    """處理單一權重檔案的上傳與 Session 註冊"""
    if len(ACTIVE_SESSIONS) >= MAX_SESSIONS:
        return {
            "status": "error",
            "message": f"已達上傳上限。系統最多支援載入 {MAX_SESSIONS} 個模型，請先移除既有模型。"
        }

    # 建立獨立存放目錄
    upload_id = uuid.uuid4().hex[:8]
    safe_name = os.path.basename(file.filename)
    dest_dir = os.path.join(EXTRACTED_RUNS_DIR, "weight", f"uploaded_{upload_id}_{os.path.splitext(safe_name)[0]}")
    os.makedirs(dest_dir, exist_ok=True)

    os.makedirs(UPLOAD_TEMP_DIR, exist_ok=True)
    temp_file = os.path.join(UPLOAD_TEMP_DIR, f"{uuid.uuid4().hex}_{safe_name}")
    with open(temp_file, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    try:
        session_info = index_single_weight(temp_file, dest_dir)
        
        format_label = FORMAT_LABELS.get(ext, ext.upper())
        session_id = f"run_{upload_id}"
        
        # Determine model architecture
        model_arch = "yolo"
        if ext == ".pth":
            if "small" in safe_name.lower():
                model_arch = "ssdlite_mobilenet_v3_small"
            else:
                model_arch = "ssdlite_mobilenet_v3_large"
                
        # Try to find and parse training_metrics.csv
        metrics_csv_path = None
        epochs = "N/A"
        metrics_summary = {}
        
        if ext == ".pth":
            # Typical path: same dir, or ../outputs/training_metrics.csv (if user uploaded from training structure)
            # Actually, since the user just uploads a single weight, we don't have the csv uploaded unless it's a zip.
            # But the plan says: "嘗試讀取同目錄或同命名的 training_metrics.csv". 
            # In a web interface, single file upload only gives us the file. 
            # However, if we're running locally and scanning local runs, or if they uploaded the whole folder?
            # They only uploaded .pth. So we can't read CSV unless we search the original path which we don't have.
            # Wait, the user might be using the "Auto Scan Local Runs" or we can just mock it if we can't find it.
            # Let's search the parent directories up to PROJECT_ROOT just in case, but realistically it's hard.
            # Actually, the user's files are at `SSD-MobilenetV3_Model_train/*/outputs/best_model.pth`.
            # When we use `shutil.copyfileobj(file.file, buffer)`, we lose the original path.
            # So I will just leave metrics_csv_path None for web upload, BUT I need to support local scan if it's there.
            pass
            
        with SESSIONS_LOCK:
            ACTIVE_SESSIONS[session_id] = {
                "session_id": session_id,
                "zip_name": safe_name,
                "source_type": "single_weight",
                "format_label": format_label,
                "model_arch": model_arch,
                "custom_name": f"{os.path.splitext(safe_name)[0]} ({format_label})",
                "epochs": epochs,
                "metrics_summary": metrics_summary,
                "metrics_csv_path": metrics_csv_path,
                **session_info
            }
            sessions_snapshot = dict(ACTIVE_SESSIONS)
    finally:
        if os.path.exists(temp_file):
            os.remove(temp_file)

    save_sessions_to_disk()
    print(f"[FastAPI] Registered single weight model: {safe_name} [arch: {model_arch}] ({format_label}) as {session_id}")

    return {
        "status": "success",
        "registered_sessions": [session_id],
        "sessions": sessions_snapshot
    }

def _handle_zip_upload(file: UploadFile):
    """處理 ZIP 訓練結果壓縮包的上傳"""
    if len(ACTIVE_SESSIONS) >= MAX_SESSIONS:
        return {
            "status": "error",
            "message": f"已達上傳上限。系統最多支援載入 {MAX_SESSIONS} 個模型，請先移除既有模型。"
        }

    zip_base_name = os.path.splitext(file.filename)[0]
    zip_base_name = os.path.basename(zip_base_name)
    extract_dir = os.path.join(EXTRACTED_RUNS_DIR, "weight", f"{uuid.uuid4().hex[:8]}_{zip_base_name}")

    os.makedirs(UPLOAD_TEMP_DIR, exist_ok=True)
    temp_zip = os.path.join(UPLOAD_TEMP_DIR, f"{uuid.uuid4().hex}_{file.filename}")

    with open(temp_zip, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    try:
        found_runs = extract_and_index(temp_zip, extract_dir)
        if not found_runs:
            if os.path.exists(extract_dir):
                shutil.rmtree(extract_dir)
            return {
                "status": "error",
                "message": "解壓縮成功，但目錄中找不到任何含有 args.yaml 與 weights/best.pt 的 YOLO 訓練子資料夾。"
            }
            
        # 測試訓練過濾 Heuristic: 篩選掉 epochs <= 5 的測試執行
        formal_runs = []
        for r in found_runs:
            epochs = r.get("epochs")
            try:
                epochs_val = int(epochs)
                if epochs_val > 5:
                    formal_runs.append(r)
            except (ValueError, TypeError):
                formal_runs.append(r)
                
        target_runs = formal_runs if formal_runs else found_runs
        
        # 排序 Heuristic: 依照 epochs 降序排列
        def get_epoch_count(run_item):
            epochs = run_item.get("epochs")
            try:
                return int(epochs)
            except (ValueError, TypeError):
                return 0
                
        target_runs.sort(key=get_epoch_count, reverse=True)
        
        # 批次註冊 (最多填滿至 MAX_SESSIONS 上限)
        registered_ids = []
        zip_base_name = os.path.splitext(file.filename)[0]

        with SESSIONS_LOCK:
            for run_item in target_runs:
                if len(ACTIVE_SESSIONS) >= MAX_SESSIONS:
                    break

                run_session_id = f"run_{uuid.uuid4().hex[:8]}"
                folder_name = os.path.basename(run_item["dir_path"])

                ACTIVE_SESSIONS[run_session_id] = {
                    "session_id": run_session_id,
                    "zip_name": file.filename,
                    "source_type": "zip",
                    "format_label": "ZIP Archive",
                    "model_arch": "yolo",
                    "custom_name": f"{zip_base_name} - {folder_name}",
                    "dir_path": run_item["dir_path"],
                    "weights_path": run_item["weights_path"],
                    "weights_size_mb": run_item["weights_size_mb"],
                    "epochs": run_item["epochs"],
                    "optimizer": run_item["optimizer"],
                    "model_cfg": run_item["model_cfg"],
                    "metrics_summary": run_item["metrics_summary"],
                    "results_png": run_item["results_png"],
                    "confusion_matrix": run_item["confusion_matrix"]
                }
                registered_ids.append(run_session_id)

            sessions_snapshot = dict(ACTIVE_SESSIONS)

        if not registered_ids:
            return {
                "status": "error",
                "message": f"系統已達 {MAX_SESSIONS} 個模型載入上限，無法註冊任何新模型。"
            }

        save_sessions_to_disk()
        return {
            "status": "success",
            "registered_sessions": registered_ids,
            "sessions": sessions_snapshot
        }
    except ZipIndexError as e:
        if os.path.exists(extract_dir):
            try:
                shutil.rmtree(extract_dir)
            except Exception:
                pass
        return {
            "status": "error",
            "message": f"ZIP 解包失敗: {str(e)}"
        }
    except Exception as e:
        if os.path.exists(extract_dir):
            try:
                shutil.rmtree(extract_dir)
            except Exception:
                pass
        return {
            "status": "error",
            "message": f"解包過濾與索引失敗: {str(e)}"
        }
    finally:
        if os.path.exists(temp_zip):
            os.remove(temp_zip)
