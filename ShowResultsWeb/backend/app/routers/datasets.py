"""資料集分析路由。"""
import os
import threading
import zipfile
from typing import Union

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.schemas import DatasetAnalyzeResponse, DatasetsResponse, ErrorResponse
from app.services.dataset_analyzer import analyze_dataset
from app.services.dataset_manager import (
    delete_dataset,
    get_datasets_snapshot,
    register_dataset,
)
from app.utils.zip_handler import ZipIndexError

router = APIRouter()

# 資料集分析是重度 I/O + CPU 工作。FastAPI 會把同步路由丟進 threadpool，
# 若同時跑多個數 GB 的分析會互相拖垮，因此一次只允許一個。
_ANALYSIS_SEMAPHORE = threading.BoundedSemaphore(1)


@router.get("/datasets", response_model=DatasetsResponse, response_model_exclude_unset=True)
def list_datasets():
    return {"status": "success", "datasets": get_datasets_snapshot()}


@router.post(
    "/upload-dataset",
    response_model=Union[DatasetAnalyzeResponse, ErrorResponse],
    response_model_exclude_unset=True,
)
def upload_dataset(file: UploadFile = File(...)):
    """
    上傳資料集 ZIP 並分析。

    使用同步 def：分析是 CPU-bound，交由 FastAPI 的 threadpool 執行，
    與 inference.py / sessions.py 的做法一致。

    刻意不把上傳內容複製到 UPLOAD_TEMP_DIR：Starlette 已將 request body 寫入
    SpooledTemporaryFile（超過 1 MB 即落地），再複製一次會讓數 GB 的 ZIP
    佔用雙倍磁碟。SpooledTemporaryFile 可 seek，直接交給 ZipFile 即可。
    """
    filename = os.path.basename(file.filename or "")
    if not filename.lower().endswith(".zip"):
        return {"status": "error", "message": "資料集分析僅支援 .zip 壓縮檔"}

    if not _ANALYSIS_SEMAPHORE.acquire(blocking=False):
        return {"status": "error", "message": "目前有其他資料集正在分析中，請稍候再試"}

    try:
        file.file.seek(0, os.SEEK_END)
        zip_size = file.file.tell()
        file.file.seek(0)

        try:
            with zipfile.ZipFile(file.file) as zip_ref:
                stats = analyze_dataset(zip_ref, zip_name=filename, zip_size_bytes=zip_size)
        except zipfile.BadZipFile:
            return {"status": "error", "message": "ZIP 檔案損毀或格式不正確"}
        except ZipIndexError as exc:
            return {"status": "error", "message": str(exc)}
        except MemoryError:
            return {"status": "error", "message": "資料集過大，分析時記憶體不足"}
        except OSError as exc:
            return {"status": "error", "message": f"讀取資料集時發生系統錯誤: {exc}"}

        snapshot = register_dataset(stats)
        return {
            "status": "success",
            "dataset_id": stats["dataset_id"],
            "dataset": stats,
            "datasets": snapshot,
        }
    finally:
        _ANALYSIS_SEMAPHORE.release()


@router.post("/delete-dataset", response_model=DatasetsResponse, response_model_exclude_unset=True)
def remove_dataset(dataset_id: str = Form(...)):
    try:
        snapshot = delete_dataset(dataset_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="找不到指定的資料集分析記錄")
    return {"status": "success", "datasets": snapshot}
