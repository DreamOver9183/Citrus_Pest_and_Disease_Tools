"""逐張檢視（看圖驗收）的 API。

建立 job 讓模型逐張跑過一個 split；完成後以信心門檻、類別、狀態即時查詢每張的標註框與
預測框。調門檻只重新配對，不重跑推論。

**這是視覺化，不是評估指標**——指標走 /api/evaluations。
"""
import mimetypes
import queue
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse, Response

from app.core.envelope import ApiException, ApiResponse, ok
from app.core.imgsz import IMGSZ_CHOICES, validate_imgsz
from app.schemas import (
    ReviewItemPayload,
    ReviewItemsPayload,
    ReviewJobPayload,
    ReviewJobsPayload,
    ReviewSubmitRequest,
    ReviewTargetsPayload,
)
from app.services import review_service
from app.services.dataset_manager import ACTIVE_DATASETS, DATASETS_LOCK
from app.services.dataset_resolver import (
    available_splits,
    describe_availability,
    preferred_split,
    target_entry,
)
from app.services.session_manager import ACTIVE_SESSIONS, SESSIONS_LOCK

router = APIRouter()


def _parse_classes(raw: Optional[str]) -> Optional[List[int]]:
    if not raw:
        return None
    try:
        return [int(part) for part in raw.split(",") if part.strip()]
    except ValueError:
        raise ApiException("validation_error", "classes 必須是以逗號分隔的類別索引")


def _require_done(job_id: str) -> None:
    state = review_service.job_state(job_id)
    if state is None:
        raise ApiException("not_found", "找不到指定的逐張檢視")
    if state != "done":
        raise ApiException("precondition_failed", "逐張檢視尚未完成，完成後才能查詢結果")


# ⚠️ 路由順序：字面路徑 /reviews/targets 必須宣告在 /reviews/{job_id} 之前。
@router.get("/reviews/targets", response_model=ApiResponse[ReviewTargetsPayload])
def list_targets():
    """列出可用的模型與資料集；不可用者仍列出並附原因。"""
    with DATASETS_LOCK:
        datasets_snapshot = list(ACTIVE_DATASETS.values())
    with SESSIONS_LOCK:
        sessions_snapshot = list(ACTIVE_SESSIONS.values())

    sessions = []
    for s in sessions_snapshot:
        available, reason = review_service.session_review_gate(s)
        sessions.append({
            "session_id": s.get("session_id"),
            "name": s.get("custom_name") or s.get("session_id"),
            "model_arch": s.get("model_arch"),
            "epochs": s.get("epochs"),
            "available": available,
            "reason": reason,
            "weight_format": Path(s.get("weights_path") or "").suffix.lstrip(".").lower() or None,
        })

    return ok({
        "datasets": [target_entry(stats) for stats in datasets_snapshot],
        "sessions": sessions,
        "imgsz_choices": list(IMGSZ_CHOICES),
    })


@router.post("/reviews", response_model=ApiResponse[ReviewJobPayload])
def submit_review(payload: ReviewSubmitRequest):
    imgsz = validate_imgsz(payload.imgsz)

    with SESSIONS_LOCK:
        session = ACTIVE_SESSIONS.get(payload.session_id)
        session = dict(session) if session else None
    if session is None:
        raise ApiException("not_found", "找不到指定的模型 Session")
    available, reason = review_service.session_review_gate(session)
    if not available:
        raise ApiException("precondition_failed", reason)

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
        job = review_service.submit_review(session, dataset, chosen, imgsz)
    except queue.Full:
        raise ApiException("queue_full", "逐張檢視佇列已滿，請等待進行中的工作完成後再試")

    return ok({"job": job, "message": None})


@router.get("/reviews", response_model=ApiResponse[ReviewJobsPayload])
def list_reviews():
    return ok(review_service.get_jobs_snapshot())


@router.get("/reviews/{job_id}", response_model=ApiResponse[ReviewJobPayload])
def get_review(job_id: str):
    job = review_service.get_job(job_id)
    if job is None:
        raise ApiException("not_found", "找不到指定的逐張檢視")
    return ok({"job": job, "message": None})


@router.get("/reviews/{job_id}/items", response_model=ApiResponse[ReviewItemsPayload])
def list_review_items(
    job_id: str,
    conf: float = Query(0.25, ge=review_service.STORE_CONF, le=1.0),
    classes: Optional[str] = None,
    status: str = "all",
    sort: str = "errors",
    offset: int = Query(0, ge=0),
    limit: int = Query(24, ge=1, le=200),
):
    if status not in review_service.STATUS_FILTERS:
        raise ApiException("validation_error", f"status 必須是 {'、'.join(review_service.STATUS_FILTERS)} 之一")
    if sort not in review_service.SORT_KEYS:
        raise ApiException("validation_error", f"sort 必須是 {'、'.join(review_service.SORT_KEYS)} 之一")
    _require_done(job_id)

    result = review_service.query_items(
        job_id, conf, _parse_classes(classes), status, sort, offset, limit
    )
    if result is None:
        raise ApiException("not_found", "找不到逐張檢視的結果檔")
    return ok(result)


@router.get("/reviews/{job_id}/item", response_model=ApiResponse[ReviewItemPayload])
def get_review_item(
    job_id: str,
    name: str,
    conf: float = Query(0.25, ge=review_service.STORE_CONF, le=1.0),
):
    _require_done(job_id)
    item = review_service.get_item(job_id, name, conf)
    if item is None:
        raise ApiException("not_found", f"此逐張檢視沒有名為「{name}」的影像")
    return ok({"item": item})


@router.get("/reviews/{job_id}/image/{index}")
def get_review_image(job_id: str, index: int, variant: str = "full"):
    """串流原圖或縮圖。以索引定位，路徑包含關係由 service 驗證。"""
    if variant not in ("full", "thumb"):
        raise ApiException("validation_error", "variant 必須是 full 或 thumb")
    path = review_service.image_path(job_id, index, variant)
    if path is None:
        raise ApiException("not_found", "找不到指定的影像")
    return FileResponse(path, media_type=mimetypes.guess_type(path)[0] or "application/octet-stream")


@router.get("/reviews/{job_id}/export")
def export_review(
    job_id: str,
    conf: float = Query(0.25, ge=review_service.STORE_CONF, le=1.0),
    classes: Optional[str] = None,
    status: str = "errors",
    sort: str = "errors",
    limit: int = Query(review_service.EXPORT_LIMIT_DEFAULT, ge=1, le=review_service.EXPORT_LIMIT_MAX),
    title: Optional[str] = None,
):
    """以目前的篩選條件下載一份自足 HTML（影像與框全部內嵌，離線可開、可列印成 PDF）。"""
    if status not in review_service.STATUS_FILTERS:
        raise ApiException("validation_error", f"status 必須是 {'、'.join(review_service.STATUS_FILTERS)} 之一")
    if sort not in review_service.SORT_KEYS:
        raise ApiException("validation_error", f"sort 必須是 {'、'.join(review_service.SORT_KEYS)} 之一")
    _require_done(job_id)

    rendered = review_service.render_export(
        job_id, conf, _parse_classes(classes), status, sort, limit, title
    )
    if rendered is None:
        raise ApiException("not_found", "找不到逐張檢視的結果檔")
    html, filename = rendered
    # 中文檔名走 RFC 5987（與 FileResponse 的處理方式相同），另給一個 ASCII 後備
    disposition = f"attachment; filename=\"review.html\"; filename*=utf-8''{quote(filename)}"
    return Response(content=html, media_type="text/html; charset=utf-8",
                    headers={"Content-Disposition": disposition})


@router.delete("/reviews/{job_id}", response_model=ApiResponse[ReviewJobPayload])
def delete_review(job_id: str):
    """刪除逐張檢視（執行中的會在下一張之前停下）。"""
    if not review_service.delete_job(job_id):
        raise ApiException("not_found", "找不到指定的逐張檢視")
    return ok({"job": None, "message": "已刪除"})
