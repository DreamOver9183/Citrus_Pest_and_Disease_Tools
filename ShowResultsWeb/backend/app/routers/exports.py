"""模型權重格式匯出路由。"""
import queue
from typing import Optional, Union

from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import FileResponse

from app.schemas import (
    ErrorResponse,
    ExportCapabilitiesResponse,
    ExportJobResponse,
    ExportJobsResponse,
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
@router.get(
    "/export/capabilities",
    response_model=ExportCapabilitiesResponse,
    response_model_exclude_unset=True,
)
def export_capabilities():
    caps = get_capabilities()
    return {"status": "success", "formats": caps["formats"], "any_available": caps["any_available"]}


@router.get("/export/jobs", response_model=ExportJobsResponse, response_model_exclude_unset=True)
def list_export_jobs(session_id: Optional[str] = None, active: int = 0):
    return {
        "status": "success",
        "jobs": export_service.get_jobs_snapshot(session_id=session_id, active_only=bool(active)),
    }


@router.post(
    "/export",
    response_model=Union[ExportJobResponse, ErrorResponse],
    response_model_exclude_unset=True,
)
def start_export(session_id: str = Form(...), format: str = Form("onnx")):
    """
    排入一個匯出 job，立即回傳 job_id。

    同步 def：這裡只做鎖內的字典操作，實際轉檔在獨立的 daemon worker 上，
    因此不會佔用 Starlette threadpool。
    """
    with SESSIONS_LOCK:
        session = ACTIVE_SESSIONS.get(session_id)
        session_copy = dict(session) if session else None

    if session_copy is None:
        return {"status": "error", "message": "無效的模型 Session ID。"}

    eligible, reason = session_export_gate(session_copy)
    if not eligible:
        return {"status": "error", "message": reason}

    available, cap_reason = is_format_available(format)
    if not available:
        return {"status": "error", "message": cap_reason}

    try:
        job = export_service.submit_export(session_copy, format)
    except queue.Full:
        return {"status": "error", "message": "匯出佇列已滿，請等待進行中的匯出完成後再試。"}

    return {"status": "success", "job": job}


@router.get("/export/{job_id}", response_model=ExportJobResponse, response_model_exclude_unset=True)
def get_export_job(job_id: str):
    job = export_service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="找不到指定的匯出工作")
    return {"status": "success", "job": job}


@router.get("/export/{job_id}/download")
def download_export(job_id: str):
    """
    下載匯出產物。

    用 FileResponse 而非 /static URL：/static 每次啟動都會被清空且是公開掛載，
    而且無法設 Content-Disposition。FileResponse 會產生 RFC 5987 的 filename*，
    正確處理 custom_name 裡的中文。
    """
    path = export_service.resolve_artifact(job_id)
    if path is None:
        raise HTTPException(status_code=404, detail="找不到可下載的匯出產物")
    return FileResponse(
        path=str(path),
        media_type="application/octet-stream",
        filename=path.name,
    )


@router.post(
    "/export/{job_id}/delete",
    response_model=ExportJobsResponse,
    response_model_exclude_unset=True,
)
def delete_export(job_id: str):
    try:
        export_service.delete_export_job(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="找不到指定的匯出工作")
    return {"status": "success", "jobs": export_service.get_jobs_snapshot()}
