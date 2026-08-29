"""模型權重格式匯出路由。"""
import queue
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import FileResponse

from app.core.envelope import ApiException, ApiResponse, ok
from app.schemas import (
    ExportCapabilitiesPayload,
    ExportJobPayload,
    ExportJobsPayload,
    ExportSubmitRequest,
)
from app.services import export_service
from app.services.export_capabilities import (
    get_capabilities,
    is_format_available,
    session_export_gate,
)
from app.services.session_manager import ACTIVE_SESSIONS, SESSIONS_LOCK

router = APIRouter()


# ⚠️ 路由順序很重要：字面路徑（/export/capabilities、/export/jobs）必須宣告在
# /export/{job_id} 之前。FastAPI 依宣告順序比對，否則 job_id="capabilities"
# 會吃掉請求並回 404。
@router.get("/export/capabilities", response_model=ApiResponse[ExportCapabilitiesPayload])
def export_capabilities():
    caps = get_capabilities()
    return ok({"formats": caps["formats"], "any_available": caps["any_available"]})


@router.get("/export/jobs", response_model=ApiResponse[ExportJobsPayload])
def list_export_jobs(session_id: Optional[str] = None, active: int = 0):
    return ok({
        "jobs": export_service.get_jobs_snapshot(session_id=session_id, active_only=bool(active)),
    })


@router.post("/export", response_model=ApiResponse[ExportJobPayload])
def start_export(payload: ExportSubmitRequest):
    """排入一個匯出 job，立即回傳 job_id。

    同步 def：這裡只做鎖內的字典操作，實際轉檔在獨立的 daemon worker 上，
    因此不會佔用 Starlette threadpool。
    """
    with SESSIONS_LOCK:
        session = ACTIVE_SESSIONS.get(payload.session_id)
        session_copy = dict(session) if session else None

    if session_copy is None:
        raise ApiException("not_found", "找不到指定的模型 Session")

    eligible, reason = session_export_gate(session_copy)
    if not eligible:
        raise ApiException("precondition_failed", reason)

    available, cap_reason = is_format_available(payload.format)
    if not available:
        raise ApiException("precondition_failed", cap_reason)

    try:
        job = export_service.submit_export(session_copy, payload.format)
    except queue.Full:
        raise ApiException("queue_full", "匯出佇列已滿，請等待進行中的匯出完成後再試。")

    return ok({"job": job})


@router.get("/export/{job_id}", response_model=ApiResponse[ExportJobPayload])
def get_export_job(job_id: str):
    job = export_service.get_job(job_id)
    if job is None:
        raise ApiException("not_found", "找不到指定的匯出工作")
    return ok({"job": job})


@router.get("/export/{job_id}/download")
def download_export(job_id: str):
    """下載匯出產物。

    用 FileResponse 而非 /static URL：/static 每次啟動都會被清空且是公開掛載，
    而且無法設 Content-Disposition。FileResponse 會產生 RFC 5987 的 filename*，
    正確處理 custom_name 裡的中文。

    二進位回應不套信封，但錯誤路徑仍走 ApiException，因此「找不到」在所有端點
    看起來都一樣。
    """
    path = export_service.resolve_artifact(job_id)
    if path is None:
        raise ApiException("not_found", "找不到可下載的匯出產物")
    return FileResponse(path=str(path), media_type="application/octet-stream", filename=path.name)


@router.delete("/export/{job_id}", response_model=ApiResponse[ExportJobsPayload])
def delete_export(job_id: str):
    try:
        export_service.delete_export_job(job_id)
    except KeyError:
        raise ApiException("not_found", "找不到指定的匯出工作")
    return ok({"jobs": export_service.get_jobs_snapshot()})
