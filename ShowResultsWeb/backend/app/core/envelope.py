"""統一的 API 回應信封與錯誤契約。

在此之前，同一個後端有四種回應形狀並存：成功時 `{"status": "success", ...payload}`，
失敗時可能是 200 帶 `{"status": "error", "message": ...}`、`HTTPException` 的
`{"detail": "..."}`、或 FastAPI 驗證失敗的 `{"detail": [{...}]}`。前端每個 hook 都得
各自寫 `res.data.status === 'success'` 加上 `err.response?.data?.detail || err.message`
的三段 fallback，而「HTTP 200 但其實失敗」讓 axios 的錯誤路徑形同虛設。

現在只有一種形狀：

    {"status": "success", "data": {...}, "error": null, "meta": {...}|null}
    {"status": "error",   "data": null,  "error": {"code": ..., "message": ...}, "meta": null}

**成功一律 HTTP 200，失敗一律用真正對應的狀態碼**（見 ERROR_STATUS）。四個欄位永遠都在，
不會因為沒賦值就消失——這正是移除 `response_model_exclude_unset=True` 的理由：那個選項
會把未設定的 key 從 JSON 裡靜默裁掉，前端拿到的是 `undefined` 而不是可偵測的錯誤。

檔案下載端點（FileResponse）不套信封——二進位內容沒有信封可言——但它們的**錯誤**路徑
仍然走這裡註冊的 handler，因此「找不到檔案」在所有端點看起來都一樣。
"""
from typing import Any, Dict, Generic, Literal, Optional, TypeVar

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

T = TypeVar("T")

# 錯誤碼與 HTTP 狀態碼的唯一對照表。
#
# 分界線：**400 = 請求本身壞掉，422 = 請求沒問題但這件事現在不能做。**
# FastAPI 預設把請求驗證失敗回成 422，這裡刻意改回 400，好讓 422 專門表示語意上的拒絕
#（類別數不符、資料集缺少影像位元組、非 YOLO 架構）——那才是前端需要原封不動顯示給
# 使用者看的訊息。
ERROR_STATUS: Dict[str, int] = {
    "validation_error": 400,        # 請求格式或欄位不合法
    "not_found": 404,               # session / dataset / job / report / weight 不存在
    "conflict": 409,                # 掃描或分析正在進行中
    "capacity_reached": 409,        # 已達 MAX_SESSIONS
    "unsupported_format": 415,      # 副檔名不支援
    "precondition_failed": 422,     # 格式正確但語意上不能執行
    "queue_full": 429,              # 匯出／評估佇列已滿
    "internal_error": 500,          # 未預期例外
    "dependency_unavailable": 503,  # 資料庫等外部相依不可用
}

DEFAULT_ERROR_STATUS = 400


class ApiError(BaseModel):
    """錯誤的結構化描述。`code` 供程式判斷，`message` 供人閱讀（繁體中文）。"""
    code: str
    message: str
    details: Optional[Dict[str, Any]] = None


class ApiResponse(BaseModel, Generic[T]):
    """所有 JSON 端點的回應外殼。四個欄位永遠存在。"""
    status: Literal["success", "error"] = "success"
    data: Optional[T] = None
    error: Optional[ApiError] = None
    meta: Optional[Dict[str, Any]] = None


class ApiException(Exception):
    """路由層唯一該丟的錯誤型別。狀態碼由 code 決定，不必在每個呼叫點重複指定。"""

    def __init__(
        self,
        code: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        status_code: Optional[int] = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details
        self.status_code = status_code or ERROR_STATUS.get(code, DEFAULT_ERROR_STATUS)


def ok(data: Any = None, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """成功回應。逐欄列舉，讓四個 key 在 JSON 裡永遠都在。"""
    return {"status": "success", "data": data, "error": None, "meta": meta}


def error_payload(
    code: str,
    message: str,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "status": "error",
        "data": None,
        "error": {"code": code, "message": message, "details": details},
        "meta": None,
    }


def error_response(
    code: str,
    message: str,
    details: Optional[Dict[str, Any]] = None,
    status_code: Optional[int] = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code or ERROR_STATUS.get(code, DEFAULT_ERROR_STATUS),
        content=jsonable_encoder(error_payload(code, message, details)),
    )


def _is_api_path(request: Request) -> bool:
    return request.url.path.startswith("/api")


def register_exception_handlers(app) -> None:
    """把四種例外收斂成同一個信封。在 main.py 建立 app 之後立即呼叫。"""

    @app.exception_handler(ApiException)
    async def _handle_api_exception(request: Request, exc: ApiException):
        return error_response(exc.code, exc.message, exc.details, exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(request: Request, exc: RequestValidationError):
        # FastAPI 的 errors() 帶 ctx 物件（可能含不可序列化的例外實例），
        # 只取前端真正用得到的三個欄位。
        fields = [
            {
                "loc": [str(part) for part in err.get("loc", [])],
                "msg": err.get("msg", ""),
                "type": err.get("type", ""),
            }
            for err in exc.errors()
        ]
        first = fields[0]["msg"] if fields else "請求內容不合法"
        return error_response(
            "validation_error",
            f"請求內容不合法：{first}",
            details={"fields": fields},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_exception(request: Request, exc: StarletteHTTPException):
        # 前端 SPA 掛在 "/"，StaticFiles 對未知路徑丟的 404 不該被包成 API 信封，
        # 否則使用者在網址列打錯字會下載到一段 JSON 而不是看到頁面。
        if not _is_api_path(request):
            return await http_exception_handler(request, exc)
        code = {
            400: "validation_error",
            404: "not_found",
            409: "conflict",
            415: "unsupported_format",
            422: "precondition_failed",
            429: "queue_full",
            503: "dependency_unavailable",
        }.get(exc.status_code, "internal_error")
        return error_response(code, str(exc.detail), status_code=exc.status_code)

    # 資料庫在執行期掛掉（容器被停、網路斷線）。這不是伺服器出錯，而是可選相依不在，
    # 因此必須是 503 `dependency_unavailable` 而不是 500——否則前端無法區分
    # 「登錄簿離線」與「後端壞掉」。放在通用 Exception handler 之前註冊。
    from app.db.engine import RegistryUnavailable

    @app.exception_handler(RegistryUnavailable)
    async def _handle_registry_unavailable(request: Request, exc: RegistryUnavailable):
        return error_response(
            "dependency_unavailable",
            "權重登錄簿的資料庫目前無法連線，這不影響模型載入、推論與評估等其他功能。",
            details={"reason": str(exc)[:300]},
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception):
        import traceback

        traceback.print_exc()
        if not _is_api_path(request):
            raise exc
        return error_response(
            "internal_error",
            f"伺服器內部錯誤：{exc}",
        )


__all__ = [
    "ApiError",
    "ApiException",
    "ApiResponse",
    "DEFAULT_ERROR_STATUS",
    "ERROR_STATUS",
    "error_payload",
    "error_response",
    "ok",
    "register_exception_handlers",
]
