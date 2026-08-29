"""路由測試共用的信封輔助函式。

（檔名刻意不叫 conftest.py：site-packages 底下存在一個名為 `tests` 的套件，
`from tests.conftest import ...` 會解析到那一個。pytest 會把 tests/ 目錄放進
sys.path，所以 `from apitest import ...` 是明確且不會撞名的寫法。）

每個 API 回應都長成同一個樣子（見 `app/core/envelope.py`）：

    {"status": ..., "data": ..., "error": ..., "meta": ...}

把拆信封這件事收斂成 `data()` / `error()` 兩個函式有兩個好處：測試讀起來仍然是在講
業務語意（`data(res)["jobs"]`），而且**每一次呼叫都順帶驗一次信封契約**——四個 key
是否齊全、成功時 error 是否為 None、失敗時 data 是否為 None。於是契約不是靠
`test_envelope.py` 一支測試孤軍守著，而是被整個測試套件反覆檢查。
"""
ENVELOPE_KEYS = {"status", "data", "error", "meta"}


def envelope(res):
    """驗證並回傳整個信封。"""
    body = res.json()
    assert isinstance(body, dict), f"回應不是 JSON 物件：{body!r}"
    assert set(body.keys()) == ENVELOPE_KEYS, f"信封欄位不符：{sorted(body.keys())}"
    return body


def data(res, status_code=200):
    """成功回應的 payload。"""
    body = envelope(res)
    assert res.status_code == status_code, f"HTTP {res.status_code}：{body}"
    assert body["status"] == "success", body
    assert body["error"] is None, body
    return body["data"]


def meta(res):
    return envelope(res)["meta"]


def error(res, status_code=None, code=None):
    """錯誤回應的 error 物件。

    刻意要求呼叫端指明預期的 HTTP 狀態碼：整個正規化的重點就是「錯誤不再是 HTTP 200」，
    測試若不檢查狀態碼，這件事就會靜靜地退化回去。
    """
    body = envelope(res)
    assert body["status"] == "error", body
    assert body["data"] is None, body
    assert body["error"] is not None, body
    assert res.status_code >= 400, f"錯誤回應不該是 HTTP {res.status_code}：{body}"
    if status_code is not None:
        assert res.status_code == status_code, f"HTTP {res.status_code}：{body}"
    if code is not None:
        assert body["error"]["code"] == code, body
    return body["error"]
