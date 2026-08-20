"""
本機資料夾掃描。

使用者用作業系統的檔案總管把訓練成果／資料集放進 LOCAL_LIBRARY_DIR，再按下
掃描按鈕檢視找到的內容，勾選要載入的項目。

為什麼是「固定目錄」而不是讓使用者輸入路徑：瀏覽器基於安全機制，永遠不會把
使用者選取的資料夾轉成可用的絕對路徑字串（showDirectoryPicker() 只給檔案控制代碼
與資料夾名稱）。固定目錄讓路徑完全不需要經過瀏覽器，同時也讓 Docker 支援退化成
一條普通的 bind mount。

**掃描與註冊是分開的兩個端點**：掃描純唯讀，註冊只處理使用者實際勾選的項目。
理由與實作細節見 `app/services/library_scanner.py` 的模組說明。

**本模組不寫入 LOCAL_LIBRARY_DIR**：資料夾與散落權重檔都是就地引用；唯一會落地的
是 ZIP 的解壓內容，而落點在受管的 extracted_runs/local_library/ 底下。
"""
import threading
from typing import Union

from fastapi import APIRouter

from app.core.config import LOCAL_LIBRARY_DIR, MAX_SESSIONS
from app.schemas import (
    ErrorResponse,
    LocalLibraryInfoResponse,
    LocalLibraryRegisterRequest,
    LocalLibraryRegisterResponse,
    LocalLibraryScanResponse,
)
from app.services import library_scanner
from app.services.dataset_manager import ACTIVE_DATASETS, DATASETS_LOCK
from app.services.session_manager import ACTIVE_SESSIONS, SESSIONS_LOCK

router = APIRouter()

# 一次只允許一個掃描：走訪大型資料夾並分析其中的資料集是重度 I/O，
# 與 datasets.py 的分析同理。
_SCAN_SEMAPHORE = threading.BoundedSemaphore(1)


def _snapshots():
    with SESSIONS_LOCK:
        sessions = dict(ACTIVE_SESSIONS)
    with DATASETS_LOCK:
        datasets = dict(ACTIVE_DATASETS)
    return sessions, datasets


@router.get("/local-library", response_model=LocalLibraryInfoResponse, response_model_exclude_unset=True)
def get_local_library_info():
    """回傳資料夾的絕對路徑供 UI 顯示。純唯讀，不會註冊任何東西。"""
    return {
        "status": "success",
        "path": str(LOCAL_LIBRARY_DIR).replace("\\", "/"),
        "exists": LOCAL_LIBRARY_DIR.exists(),
    }


@router.post(
    "/local-library/scan",
    response_model=Union[LocalLibraryScanResponse, ErrorResponse],
    response_model_exclude_unset=True,
)
def scan_local_library():
    """
    列出資料夾內所有可辨識的模型與資料集。

    不接受任何請求參數——掃描目標永遠是伺服器端設定好的 LOCAL_LIBRARY_DIR，
    路徑完全不經過瀏覽器。

    **這個端點不註冊任何東西**，只回報找到什麼。實際載入請呼叫 /register。
    """
    if not LOCAL_LIBRARY_DIR.exists():
        return {
            "status": "error",
            "message": f"找不到本機資料夾：{LOCAL_LIBRARY_DIR}。請先建立此資料夾並放入模型或資料集。",
        }

    if not _SCAN_SEMAPHORE.acquire(blocking=False):
        return {"status": "error", "message": "目前已有掃描正在進行中，請稍候再試"}

    try:
        candidates = library_scanner.discover(str(LOCAL_LIBRARY_DIR))
    finally:
        _SCAN_SEMAPHORE.release()

    models = [c for c in candidates if c["kind"] == "model"]
    datasets = [c for c in candidates if c["kind"] == "dataset"]

    if candidates:
        message = f"已掃描出 {len(models)} 個權重、{len(datasets)} 個資料集"
    else:
        message = "未找到可辨識的模型或資料集。請確認資料夾內含 YOLO 訓練成果（weights/best.pt + args.yaml）、權重檔或資料集。"

    return {
        "status": "success",
        "candidates": [library_scanner.public_view(c) for c in candidates],
        "total_models": len(models),
        "total_datasets": len(datasets),
        "message": message,
    }


@router.post(
    "/local-library/register",
    response_model=Union[LocalLibraryRegisterResponse, ErrorResponse],
    response_model_exclude_unset=True,
)
def register_local_library(payload: LocalLibraryRegisterRequest):
    """載入使用者勾選的項目。candidate_id 來自上一次 /scan 的結果。"""
    if not payload.candidate_ids:
        return {"status": "error", "message": "請至少勾選一個項目"}

    result = library_scanner.register(payload.candidate_ids)

    parts = []
    if result["registered_sessions"]:
        parts.append(f"已載入 {len(result['registered_sessions'])} 個權重")
    if result["registered_datasets"]:
        parts.append(f"已載入 {len(result['registered_datasets'])} 個資料集")
    if result["skipped"]:
        parts.append(f"{result['skipped']} 筆已存在略過")
    if result["capped"]:
        parts.append(f"已達模型數量上限（{MAX_SESSIONS}），請先刪除既有模型再載入其餘項目")
    if result["failed"]:
        parts.append(f"{len(result['failed'])} 筆載入失敗：{'、'.join(result['failed'])}")
    if result["unknown"]:
        parts.append(f"{len(result['unknown'])} 筆項目已失效，請重新掃描")
    if not parts:
        parts.append("沒有任何項目被載入")

    sessions, datasets = _snapshots()
    return {
        "status": "success",
        "registered_sessions": result["registered_sessions"],
        "registered_datasets": result["registered_datasets"],
        "skipped": result["skipped"],
        "failed": result["failed"],
        "message": "；".join(parts),
        "sessions": sessions,
        "datasets": datasets,
    }
