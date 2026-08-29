"""權重登錄簿的查詢 API。

這是唯一會讀資料庫的路由。與其他子系統最大的差別：**這裡的資料不依賴任何 session
還活著**。使用者可以刪掉所有已載入的模型、重啟整個系統，登錄簿裡「這顆權重的超參數
是什麼、在哪個資料集上實測到多少」仍然查得到。

資料庫不可用時一律回 503 + `dependency_unavailable`，**不是 500**：那不是伺服器出錯，
而是一個可選相依暫時不在。前端據此顯示「登錄簿離線」而不是紅色錯誤。
"""
from typing import Optional

from fastapi import APIRouter, Query

from app.core.envelope import ApiException, ApiResponse, ok
from app.db import engine as db_engine
from app.schemas import (
    RegistryDeletePayload,
    RegistryEvaluationsPayload,
    RegistryStatsPayload,
    RegistryWeightDetailPayload,
    RegistryWeightsPayload,
)
from app.services import registry_service

router = APIRouter()


def _unavailable() -> ApiException:
    return ApiException(
        "dependency_unavailable",
        "權重登錄簿的資料庫目前無法連線，這不影響模型載入、推論與評估等其他功能。",
        details={"backend": db_engine.backend_name(), "reason": db_engine.last_error()},
    )


def _require_db() -> None:
    """確認資料庫可用；不可用時先試著重連一次。

    重連是必要的：資料庫在執行期掛掉會把 `_AVAILABLE` 拉成 False，若不重試，
    即使資料庫已經回來，使用者也得重啟整個應用才能再用登錄簿。
    """
    if db_engine.is_available():
        return
    if db_engine.init_db(retries=1):
        return
    raise _unavailable()


# ⚠️ 字面路徑必須宣告在 /weights/{sha256} 之前（與 exports.py 同一個坑）。
@router.get("/registry/stats", response_model=ApiResponse[RegistryStatsPayload])
def registry_stats():
    """總覽。**刻意不 raise**——資料庫離線時這個端點要能誠實回報 `available: false`，
    那正是前端判斷登錄簿狀態的依據。若資料庫已經回來，順手重連。"""
    if not db_engine.is_available():
        db_engine.init_db(retries=1)
    return ok(registry_service.stats())


@router.get("/registry/evaluations", response_model=ApiResponse[RegistryEvaluationsPayload])
def list_registry_evaluations(
    weight_sha: Optional[str] = None,
    dataset_name: Optional[str] = None,
    split: Optional[str] = None,
    order_by: str = "finished_at",
    order: str = "desc",
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """跨權重的指標帳本，可依任一指標排序。"""
    _require_db()
    result = registry_service.query_evaluations(
        weight_sha=weight_sha,
        dataset_name=dataset_name,
        split=split,
        order_by=order_by,
        order=order,
        limit=limit,
        offset=offset,
    )
    return ok(
        {"evaluations": result["evaluations"]},
        meta={
            "total": result["total"],
            "limit": limit,
            "offset": offset,
            "order_by": order_by,
            "order": order,
            "sortable": list(registry_service.EVALUATION_ORDER_FIELDS),
        },
    )


@router.get("/registry/weights", response_model=ApiResponse[RegistryWeightsPayload])
def list_registry_weights(
    q: Optional[str] = None,
    model_arch: Optional[str] = None,
    order_by: str = "last_seen_at",
    order: str = "desc",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    _require_db()
    result = registry_service.query_weights(
        q=q,
        model_arch=model_arch,
        order_by=order_by,
        order=order,
        limit=limit,
        offset=offset,
    )
    return ok(
        {"weights": result["weights"]},
        meta={
            "total": result["total"],
            "limit": limit,
            "offset": offset,
            "order_by": order_by,
            "order": order,
            "sortable": list(registry_service.WEIGHT_ORDER_FIELDS),
        },
    )


@router.get("/registry/weights/{sha256}", response_model=ApiResponse[RegistryWeightDetailPayload])
def get_registry_weight(sha256: str):
    """單一權重：身分 + 完整訓練超參數 + 歷次評估。"""
    _require_db()
    detail = registry_service.get_weight_detail(sha256)
    if detail is None:
        raise ApiException("not_found", "登錄簿中找不到這顆權重")
    return ok(detail)


@router.delete("/registry/weights/{sha256}", response_model=ApiResponse[RegistryDeletePayload])
def delete_registry_weight(sha256: str):
    """從登錄簿移除一顆權重及其所有紀錄。

    只動資料庫——不會碰使用者磁碟上的權重檔，也不會影響已載入的 session。
    """
    _require_db()
    removed = registry_service.delete_weight(sha256)
    if removed is None:
        raise ApiException("not_found", "登錄簿中找不到這顆權重")
    return ok(removed)
