"""API 契約測試。

正規化最容易失敗的方式不是一開始做錯，而是**慢慢退化**：某天新增一個端點，隨手回了
一個裸 dict；某天為了「快一點」在錯誤時回 HTTP 200 帶 `{"status": "error"}`。這支測試
走訪 `app.routes` 本身，讓契約由程式強制，而不是靠每個人記得。

守四件事：

1. 每個回 JSON 的路由，其 `response_model` 都是 `ApiResponse[...]`。
2. 沒有任何路由還在用 `response_model_exclude_unset`（那是 CLAUDE.md 記載的地雷：
   未賦值欄位被靜默裁掉，前端拿到 undefined）。
3. 成功與失敗回應的 key 集合完全一致。
4. 錯誤一律用真正的 HTTP 狀態碼，而不是 HTTP 200。
"""
import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import main
from apitest import ENVELOPE_KEYS, data, envelope, error
from app.core.envelope import ERROR_STATUS, ApiResponse

# 回二進位內容的端點：檔案就是回應本體，沒有信封可言。
# 它們的**錯誤**路徑仍然走 ApiException，由下面的測試分別驗證。
BINARY_ROUTES = {
    "/api/export/{job_id}/download",
    "/api/evaluations/{job_id}/plot/{key}",
    "/api/reports/{report_id}/download",
    "/api/reports/{report_id}/view",
}


def _walk(routes, prefix=""):
    """遞迴展開路由樹，並把 include_router() 的 prefix 接回路徑上。

    FastAPI 0.141 起，`include_router()` 掛上的是一個 `_IncludedRouter` 容器，不再把
    APIRoute 攤平進 `app.routes`；容器底下的 APIRoute 也只帶**未加前綴**的路徑
    （`/sessions` 而不是 `/api/sessions`）。直接過濾頂層會一個都找不到，而且是
    **靜默**找不到——test_there_are_api_routes_to_check 就是為了擋這種空跑。
    """
    for route in routes:
        if isinstance(route, APIRoute):
            yield prefix + route.path, route
            continue
        included = getattr(route, "original_router", None)
        if included is not None:
            sub_prefix = prefix + getattr(route.include_context, "prefix", "")
            yield from _walk(included.routes, sub_prefix)
            continue
        nested = getattr(route, "routes", None)
        if nested:
            yield from _walk(nested, prefix)


def _api_routes():
    seen, found = set(), []
    for path, route in _walk(main.app.routes):
        key = (path, tuple(sorted(route.methods or ())))
        if path.startswith("/api") and key not in seen:
            seen.add(key)
            route.full_path = path
            found.append(route)
    return found


def test_there_are_api_routes_to_check():
    """萬一路由註冊方式改了，這支測試不能靜默變成空跑。"""
    assert len(_api_routes()) >= 20


@pytest.mark.parametrize("route", _api_routes(), ids=lambda r: f"{sorted(r.methods)[0]} {r.full_path}")
def test_every_json_route_returns_the_envelope(route):
    if route.full_path in BINARY_ROUTES:
        assert route.response_model is None, f"{route.full_path} 是二進位端點，不該宣告 response_model"
        return

    model = route.response_model
    assert model is not None, f"{route.full_path} 沒有宣告 response_model"
    origin = getattr(model, "__pydantic_generic_metadata__", {}).get("origin")
    assert origin is ApiResponse, (
        f"{route.full_path} 的 response_model 是 {model}，必須是 ApiResponse[...]"
    )


@pytest.mark.parametrize("route", _api_routes(), ids=lambda r: f"{sorted(r.methods)[0]} {r.full_path}")
def test_no_route_uses_exclude_unset(route):
    """`response_model_exclude_unset=True` 會靜默裁掉沒賦值的欄位。

    前端拿到的是 `undefined` 而不是一個能偵測到的錯誤——CLAUDE.md 把它列為地雷。
    固定信封 + 每個欄位都有預設值之後，這個選項不該再出現在任何地方。
    """
    assert route.response_model_exclude_unset is False, f"{route.full_path} 仍在用 exclude_unset"


# --- 執行期形狀 -------------------------------------------------------------

@pytest.fixture
def client():
    return TestClient(main.app)


def test_success_and_error_have_identical_key_sets(client):
    success = envelope(client.get("/api/sessions"))
    failure = envelope(client.get("/api/evaluations/definitely-not-a-job"))
    assert set(success) == set(failure) == ENVELOPE_KEYS


def test_success_response_shape(client):
    body = envelope(client.get("/api/sessions"))
    assert body["status"] == "success"
    assert body["error"] is None
    assert body["data"] is not None


def test_not_found_uses_404_not_200(client):
    """整個正規化的核心：失敗不再偽裝成 HTTP 200。"""
    detail = error(client.get("/api/evaluations/definitely-not-a-job"),
                   status_code=404, code="not_found")
    assert detail["message"]


def test_validation_error_is_400_not_422(client):
    """FastAPI 預設把請求驗證失敗回成 422。

    這裡刻意改回 400，好讓 422 專門表示「請求沒問題，但這件事現在不能做」——
    那才是使用者需要原封不動看到的訊息。
    """
    detail = error(client.post("/api/evaluations", json={"session_id": "x"}),
                   status_code=400, code="validation_error")
    assert detail["details"]["fields"], "驗證錯誤要指出是哪個欄位"


def test_unknown_api_path_is_still_an_envelope(client):
    error(client.get("/api/no-such-endpoint"), status_code=404, code="not_found")


def test_every_error_code_maps_to_a_real_http_status():
    for code, status in ERROR_STATUS.items():
        assert 400 <= status <= 599, f"{code} 對應到 {status}，不是錯誤狀態碼"


def test_binary_endpoints_report_missing_files_through_the_envelope(client):
    """二進位端點雖然不套信封，錯誤路徑仍要與其他端點長得一樣。"""
    for path in ("/api/export/exp_missing/download",
                 "/api/evaluations/eval_missing/plot/confusion_matrix",
                 "/api/reports/rep_missing/download",
                 "/api/reports/rep_missing/view"):
        error(client.get(path), status_code=404, code="not_found")


def test_non_api_paths_are_not_wrapped(client):
    """SPA 掛在 "/"。網址列打錯字應該看到頁面或原生 404，而不是下載到一段 JSON。"""
    res = client.get("/definitely-not-a-page")
    if res.status_code == 404:
        assert set(res.json() if res.headers.get("content-type", "").startswith(
            "application/json") else {}) != ENVELOPE_KEYS
