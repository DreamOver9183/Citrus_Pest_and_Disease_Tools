"""Session（已載入的模型）CRUD 與模型上傳。

回應一律走 `ApiResponse` 信封（見 `app/core/envelope.py`），錯誤一律 `raise ApiException`
而不是回一個 HTTP 200 帶 `{"status": "error"}` 的 body。

檔案上傳端點是**刻意保留 multipart** 的三個之一——真正的二進位內容沒辦法塞進 JSON。
其餘寫入端點都吃 JSON body，刪除都用 DELETE + path id。
"""
import os
import shutil
import uuid

from fastapi import APIRouter, File, UploadFile

from app.core.config import EXTRACTED_RUNS_DIR, MAX_SESSIONS, UPLOAD_TEMP_DIR
from app.core.envelope import ApiException, ApiResponse, ok
from app.schemas import SessionsPayload, UpdateSessionNameRequest, UploadPayload
from app.services import registry_service
from app.services.export_service import purge_exports_for_session
from app.services.session_manager import (
    ACTIVE_SESSIONS,
    SESSIONS_LOCK,
    delete_session,
    save_sessions_to_disk,
)
from app.utils.zip_handler import ZipIndexError, extract_and_index, index_single_weight

router = APIRouter()

SUPPORTED_WEIGHT_EXTENSIONS = {".pt", ".pth", ".onnx", ".tflite", ".engine", ".torchscript"}

FORMAT_LABELS = {
    ".pt": "PyTorch",
    ".pth": "SSDLite-MobileNetV3 (PyTorch)",
    ".onnx": "ONNX",
    ".tflite": "TFLite",
    ".engine": "TensorRT",
    ".torchscript": "TorchScript",
    ".zip": "ZIP Archive",
}


def _snapshot():
    with SESSIONS_LOCK:
        return dict(ACTIVE_SESSIONS)


def _record_weights(session_ids, hyperparams_by_id=None):
    """把剛註冊的 session 寫進權重登錄簿，並把算出的 sha 回填到 session dict。

    **在 SESSIONS_LOCK 之外呼叫**：雜湊是磁碟 I/O、寫入可能是網路上的 PostgreSQL，
    在鎖內做會讓所有推論請求排隊。登錄簿失敗不影響上傳結果（record_weight 自己吞例外）。
    """
    hyperparams_by_id = hyperparams_by_id or {}
    for sid in session_ids:
        with SESSIONS_LOCK:
            data = dict(ACTIVE_SESSIONS.get(sid) or {})
        if not data:
            continue
        sha = registry_service.record_weight(data, hyperparams_by_id.get(sid))
        if sha:
            with SESSIONS_LOCK:
                if sid in ACTIVE_SESSIONS:
                    ACTIVE_SESSIONS[sid]["weight_sha256"] = sha


@router.get("/sessions", response_model=ApiResponse[SessionsPayload])
def get_sessions():
    return ok({"sessions": _snapshot()})


@router.post("/update-session-name", response_model=ApiResponse[SessionsPayload])
def update_session_name(payload: UpdateSessionNameRequest):
    """更新指定 Session 的自訂顯示名稱。"""
    with SESSIONS_LOCK:
        if payload.session_id not in ACTIVE_SESSIONS:
            raise ApiException("not_found", "找不到指定的模型 Session")
        ACTIVE_SESSIONS[payload.session_id]["custom_name"] = payload.custom_name
        snapshot = dict(ACTIVE_SESSIONS)
    save_sessions_to_disk()
    return ok({"sessions": snapshot})


@router.delete("/sessions/{session_id}", response_model=ApiResponse[SessionsPayload])
def delete_session_route(session_id: str):
    """刪除指定 Session 並清理本地解壓硬碟目錄與其匯出產物。

    **不會刪除權重登錄簿的紀錄**——那正是登錄簿存在的理由：session 是執行期狀態，
    帳本是長期事實。要刪帳本請走 DELETE /api/registry/weights/{sha256}。
    """
    try:
        delete_session(session_id)
    except KeyError:
        raise ApiException("not_found", "找不到指定的模型 Session")

    # 匯出清理放在 router 而非 session_manager：後者已 import model_service，
    # 若再與 export_service 互相 import 會形成循環；而且在 SESSIONS_LOCK 內取得
    # EXPORT_JOBS_LOCK 會製造鎖序風險。delete_session() 回來時鎖已釋放。
    purge_exports_for_session(session_id)
    return ok({"sessions": _snapshot()})


@router.post("/upload-model", response_model=ApiResponse[UploadPayload])
def upload_model(file: UploadFile = File(...)):
    """統一的模型上傳端點，支援 ZIP 訓練結果壓縮包與單一權重檔案。"""
    _, ext = os.path.splitext(file.filename or "")
    ext = ext.lower()

    if ext == ".zip":
        return _handle_zip_upload(file)
    if ext in SUPPORTED_WEIGHT_EXTENSIONS:
        return _handle_single_weight_upload(file, ext)

    supported = ", ".join(sorted(SUPPORTED_WEIGHT_EXTENSIONS | {".zip"}))
    raise ApiException(
        "unsupported_format",
        f"不支援的檔案格式 '{ext}'。支援格式：{supported}",
    )


def _handle_single_weight_upload(file: UploadFile, ext: str):
    """處理單一權重檔案的上傳與 Session 註冊。"""
    with SESSIONS_LOCK:
        if len(ACTIVE_SESSIONS) >= MAX_SESSIONS:
            raise ApiException(
                "capacity_reached",
                f"已達上傳上限。系統最多支援載入 {MAX_SESSIONS} 個模型，請先移除既有模型。",
            )

    upload_id = uuid.uuid4().hex[:8]
    safe_name = os.path.basename(file.filename or "weight")
    dest_dir = os.path.join(
        EXTRACTED_RUNS_DIR, "weight", f"uploaded_{upload_id}_{os.path.splitext(safe_name)[0]}"
    )
    os.makedirs(dest_dir, exist_ok=True)
    os.makedirs(UPLOAD_TEMP_DIR, exist_ok=True)

    temp_file = os.path.join(UPLOAD_TEMP_DIR, f"{uuid.uuid4().hex}_{safe_name}")
    with open(temp_file, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        session_info = index_single_weight(temp_file, dest_dir)
        format_label = FORMAT_LABELS.get(ext, ext.upper())
        session_id = f"run_{upload_id}"

        # 架構依**原始檔名**判斷。上傳時 .pth 會被改名成 .pt 讓 Ultralytics 接受，
        # 所以不能用落地後的副檔名判斷（見 dir_handler 的同一則說明）。
        model_arch = "yolo"
        if ext == ".pth":
            model_arch = (
                "ssdlite_mobilenet_v3_small"
                if "small" in safe_name.lower()
                else "ssdlite_mobilenet_v3_large"
            )

        with SESSIONS_LOCK:
            ACTIVE_SESSIONS[session_id] = {
                "session_id": session_id,
                "zip_name": safe_name,
                "source_type": "single_weight",
                "format_label": format_label,
                "model_arch": model_arch,
                "custom_name": f"{os.path.splitext(safe_name)[0]} ({format_label})",
                "metrics_csv_path": None,
                "weight_sha256": None,
                **{k: v for k, v in session_info.items() if k != "hyperparameters"},
            }
    finally:
        if os.path.exists(temp_file):
            os.remove(temp_file)

    save_sessions_to_disk()
    _record_weights([session_id])
    print(f"[FastAPI] Registered single weight model: {safe_name} [{model_arch}] as {session_id}")

    return ok({
        "registered_sessions": [session_id],
        "sessions": _snapshot(),
        "message": f"已載入 {safe_name}",
    })


def _handle_zip_upload(file: UploadFile):
    """處理 ZIP 訓練結果壓縮包的上傳。"""
    with SESSIONS_LOCK:
        if len(ACTIVE_SESSIONS) >= MAX_SESSIONS:
            raise ApiException(
                "capacity_reached",
                f"已達上傳上限。系統最多支援載入 {MAX_SESSIONS} 個模型，請先移除既有模型。",
            )

    zip_base_name = os.path.basename(os.path.splitext(file.filename or "archive")[0])
    extract_dir = os.path.join(
        EXTRACTED_RUNS_DIR, "weight", f"{uuid.uuid4().hex[:8]}_{zip_base_name}"
    )
    os.makedirs(UPLOAD_TEMP_DIR, exist_ok=True)
    temp_zip = os.path.join(UPLOAD_TEMP_DIR, f"{uuid.uuid4().hex}_{file.filename}")

    with open(temp_zip, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    def _cleanup_extract_dir():
        if os.path.exists(extract_dir):
            try:
                shutil.rmtree(extract_dir)
            except Exception:  # noqa: BLE001
                pass

    try:
        try:
            found_runs = extract_and_index(temp_zip, extract_dir)
        except ZipIndexError as exc:
            _cleanup_extract_dir()
            raise ApiException("validation_error", f"ZIP 解包失敗: {exc}")
        except Exception as exc:  # noqa: BLE001
            _cleanup_extract_dir()
            raise ApiException("validation_error", f"解包過濾與索引失敗: {exc}")

        if not found_runs:
            _cleanup_extract_dir()
            raise ApiException(
                "validation_error",
                "解壓縮成功，但目錄中找不到任何含有 args.yaml 與 weights/best.pt 的 YOLO 訓練子資料夾。",
            )

        # 測試訓練過濾 Heuristic：篩掉 epochs <= 5 的測試執行，全部被篩掉時退回原清單
        formal_runs = []
        for run in found_runs:
            try:
                if int(run.get("epochs")) > 5:
                    formal_runs.append(run)
            except (ValueError, TypeError):
                formal_runs.append(run)
        target_runs = formal_runs or found_runs

        def _epoch_count(run):
            try:
                return int(run.get("epochs"))
            except (ValueError, TypeError):
                return 0

        target_runs.sort(key=_epoch_count, reverse=True)

        registered_ids = []
        hyperparams_by_id = {}
        with SESSIONS_LOCK:
            for run in target_runs:
                if len(ACTIVE_SESSIONS) >= MAX_SESSIONS:
                    break
                run_session_id = f"run_{uuid.uuid4().hex[:8]}"
                folder_name = os.path.basename(run["dir_path"])
                ACTIVE_SESSIONS[run_session_id] = {
                    "session_id": run_session_id,
                    "zip_name": file.filename,
                    "source_type": "zip",
                    "format_label": "ZIP Archive",
                    "model_arch": "yolo",
                    "custom_name": f"{zip_base_name} - {folder_name}",
                    "dir_path": run["dir_path"],
                    "weights_path": run["weights_path"],
                    "weights_size_mb": run["weights_size_mb"],
                    "epochs": run["epochs"],
                    "optimizer": run["optimizer"],
                    "model_cfg": run["model_cfg"],
                    "metrics_summary": run["metrics_summary"],
                    "results_png": run["results_png"],
                    "confusion_matrix": run["confusion_matrix"],
                    "weight_sha256": None,
                }
                registered_ids.append(run_session_id)
                hyperparams_by_id[run_session_id] = run.get("hyperparameters") or {}

        if not registered_ids:
            raise ApiException(
                "capacity_reached",
                f"系統已達 {MAX_SESSIONS} 個模型載入上限，無法註冊任何新模型。",
            )

        save_sessions_to_disk()
        _record_weights(registered_ids, hyperparams_by_id)
        return ok({
            "registered_sessions": registered_ids,
            "sessions": _snapshot(),
            "message": f"已載入 {len(registered_ids)} 個訓練成果",
        })
    finally:
        if os.path.exists(temp_zip):
            os.remove(temp_zip)
