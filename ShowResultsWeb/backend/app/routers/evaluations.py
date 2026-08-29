"""驗證評估的 API。

送出一個 (session, dataset, split) 組合，背景 job 會讓模型實際跑過該 split 並算出
當下的指標。這是本系統第一條讓「模型」與「資料集」兩個子系統相遇的路徑——在此之前
兩者是完全不交集的登錄表，消融分析顯示的都是訓練當時寫進 PNG 的舊數字。

評估完成時會把結果寫進**權重登錄簿**（見 evaluation_service._process_job），因此指標
在 session 被刪除、甚至系統重啟之後仍然查得到。
"""
import queue

from fastapi import APIRouter
from fastapi.responses import FileResponse

from app.core.envelope import ApiException, ApiResponse, ok
from app.schemas import (
    EvalJobPayload,
    EvalJobsPayload,
    EvalSubmitRequest,
    EvalTargetsPayload,
)
from app.services import evaluation_service
from app.services.dataset_manager import ACTIVE_DATASETS, DATASETS_LOCK
from app.services.dataset_resolver import (
    available_splits,
    describe_availability,
    preferred_split,
)
from app.services.session_manager import ACTIVE_SESSIONS, SESSIONS_LOCK

router = APIRouter()


# ⚠️ 路由順序：字面路徑 /evaluations/targets 必須宣告在 /evaluations/{job_id} 之前，
# 否則 job_id="targets" 會吃掉請求（與 exports.py 同一個坑）。
@router.get("/evaluations/targets", response_model=ApiResponse[EvalTargetsPayload])
def list_targets():
    """列出可用的模型與資料集。

    不可評估的資料集**仍會列出並附上原因**（例如上傳的 ZIP 只有統計、沒有影像位元組），
    比照匯出功能「顯示但停用並說明原因」的既有慣例——把它藏起來只會讓使用者困惑。
    """
    with DATASETS_LOCK:
        datasets_snapshot = list(ACTIVE_DATASETS.values())
    with SESSIONS_LOCK:
        sessions_snapshot = list(ACTIVE_SESSIONS.values())

    datasets = []
    for stats in datasets_snapshot:
        available, reason = describe_availability(stats)
        datasets.append({
            "dataset_id": stats.get("dataset_id"),
            "name": stats.get("zip_name") or stats.get("dataset_id"),
            "format": stats.get("format"),
            "available": available,
            "reason": reason,
            "splits": available_splits(stats) if available else [],
            "default_split": preferred_split(stats) if available else None,
        })

    sessions = []
    for s in sessions_snapshot:
        is_yolo = s.get("model_arch") == "yolo"
        sessions.append({
            "session_id": s.get("session_id"),
            "name": s.get("custom_name") or s.get("session_id"),
            "model_arch": s.get("model_arch"),
            "epochs": s.get("epochs"),
            "available": is_yolo,
            # model.val() 是 ultralytics 專屬；SSDLite 需要另一套評估迴圈
            "reason": None if is_yolo else "目前只支援 YOLO 架構的評估（SSDLite 需另一套評估流程）。",
        })

    return ok({"datasets": datasets, "sessions": sessions})


@router.post("/evaluations", response_model=ApiResponse[EvalJobPayload])
def submit_evaluation(payload: EvalSubmitRequest):
    with SESSIONS_LOCK:
        session = ACTIVE_SESSIONS.get(payload.session_id)
        session = dict(session) if session else None
    if session is None:
        raise ApiException("not_found", "找不到指定的模型 Session")
    if session.get("model_arch") != "yolo":
        raise ApiException("precondition_failed", "目前只支援 YOLO 架構的評估。")

    with DATASETS_LOCK:
        dataset = ACTIVE_DATASETS.get(payload.dataset_id)
        dataset = dict(dataset) if dataset else None
    if dataset is None:
        raise ApiException("not_found", "找不到指定的資料集")

    available, reason = describe_availability(dataset)
    if not available:
        raise ApiException("precondition_failed", reason)

    chosen = payload.split or preferred_split(dataset)
    if chosen not in available_splits(dataset):
        raise ApiException(
            "precondition_failed",
            f"這個資料集沒有名為「{chosen}」的 split，"
            f"可用的有：{'、'.join(available_splits(dataset))}",
        )

    try:
        job = evaluation_service.submit_evaluation(session, dataset, chosen)
    except queue.Full:
        raise ApiException("queue_full", "評估佇列已滿，請等待進行中的評估完成後再試")

    return ok({"job": job, "message": None})


@router.get("/evaluations", response_model=ApiResponse[EvalJobsPayload])
def list_evaluations():
    return ok(evaluation_service.get_jobs_snapshot())


@router.get("/evaluations/{job_id}", response_model=ApiResponse[EvalJobPayload])
def get_evaluation(job_id: str):
    job = evaluation_service.get_job(job_id)
    if job is None:
        raise ApiException("not_found", "找不到指定的評估紀錄")
    return ok({"job": job, "message": None})


@router.get("/evaluations/{job_id}/plot/{key}")
def get_evaluation_plot(job_id: str, key: str):
    """直接回傳 val() 產出的圖表檔。

    走 FileResponse 而非複製到 TEMP_DIR：TEMP_DIR 每次啟動都會被清空，而評估結果
    需要跨重啟存活（manifest 已支援）。路徑包含關係由 service 端驗證。
    """
    path = evaluation_service.plot_path(job_id, key)
    if path is None:
        raise ApiException("not_found", "找不到指定的圖表")
    return FileResponse(path, media_type="image/png")


@router.delete("/evaluations/{job_id}", response_model=ApiResponse[EvalJobPayload])
def delete_evaluation(job_id: str):
    """刪除評估 job（含其圖表目錄）。

    **不會刪除登錄簿裡的那筆指標紀錄**——job 是執行期產物，帳本是長期事實。
    要刪帳本請走 DELETE /api/registry/weights/{sha256}。
    """
    if not evaluation_service.delete_job(job_id):
        raise ApiException("not_found", "找不到指定的評估紀錄")
    return ok({"job": None, "message": "已刪除"})
