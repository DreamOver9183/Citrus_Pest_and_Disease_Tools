"""權重登錄簿路由測試。

除了一般的查詢／排序／分頁之外，這裡特別釘住兩件事：

- **路由順序**：`/registry/stats` 與 `/registry/evaluations` 必須宣告在
  `/registry/weights/{sha256}` 之前，否則字面路徑會被當成 sha256 而回 404。
  這是本專案第三次遇到同一個坑（exports、evaluations 各一次）。
- **資料庫不可用時回 503 而不是 500**：那不是伺服器出錯，是可選相依不在。
  前端據此顯示「登錄簿離線」而不是紅色錯誤。
"""
import pytest
from fastapi.testclient import TestClient

import main
from apitest import data, error, meta
from app.db import engine as db_engine
from app.services import registry_service


@pytest.fixture
def client(tmp_path):
    url = "sqlite:///" + str(tmp_path / "registry.db").replace("\\", "/")
    assert db_engine.reset_for_tests(url)
    yield TestClient(main.app)
    db_engine.dispose()


def _seed(tmp_path, name="v5-150ep", arch="yolo", epochs=150, content=b"weights-a"):
    path = tmp_path / f"{name}.pt"
    path.write_bytes(content)
    return registry_service.record_weight(
        {
            "session_id": f"run_{name}",
            "weights_path": str(path).replace("\\", "/"),
            "custom_name": name,
            "model_arch": arch,
            "format_label": "PyTorch",
            "source_type": "zip",
            "weights_size_mb": 5.2,
            "metrics_summary": {"mAP50": "0.803", "precision": "0.85", "recall": "0.78"},
        },
        {"epochs": epochs, "optimizer": "auto", "lr0": 0.01, "model": "yolo11n.pt"},
    )


def _seed_eval(sha, job_id="eval_a", map50=0.862, micro=0.71, split="test"):
    registry_service.record_evaluation(
        {
            "job_id": job_id,
            "dataset_name": "citrus_v5.zip",
            "dataset_format": "yolo",
            "split": split,
            "image_count": 445,
            "overall": {"map50": map50, "map50_95": 0.66, "precision": 0.9,
                        "recall": 0.85, "f1": 0.874, "fitness": 0.68},
            "micro": {"micro_accuracy": micro, "micro_precision": 0.83, "micro_recall": 0.83,
                      "micro_f1": 0.83, "tp": 100, "fp": 20, "fn": 21,
                      "conf_threshold": 0.25, "iou_threshold": 0.45},
            "vocab_check": {"status": "match", "model_names": ["Canker", "Aphid"]},
            "speed_ms": {"inference": 435.0},
            "per_class": [], "size_profile": [],
            "started_at": "2026-08-30T00:00:00+00:00",
            "finished_at": "2026-08-30T00:04:00+00:00",
            "elapsed_seconds": 240.0,
        },
        sha,
    )


# --- 路由順序（與 exports.py 同一個坑）--------------------------------------

def test_literal_routes_are_not_shadowed_by_sha256(client):
    assert data(client.get("/api/registry/stats"))["available"] is True
    assert data(client.get("/api/registry/evaluations"))["evaluations"] == []


# --- 清單 -------------------------------------------------------------------

def test_weights_listing_reports_total_in_meta(client, tmp_path):
    _seed(tmp_path, "alpha", content=b"a")
    _seed(tmp_path, "beta", content=b"b")

    res = client.get("/api/registry/weights")
    assert len(data(res)["weights"]) == 2
    assert meta(res)["total"] == 2
    assert "sortable" in meta(res), "排序欄位白名單要對外公開，前端才知道能點哪幾欄"


def test_weights_can_be_filtered_and_sorted(client, tmp_path):
    _seed(tmp_path, "alpha", epochs=50, content=b"a")
    _seed(tmp_path, "beta", epochs=300, content=b"b")
    _seed(tmp_path, "gamma", arch="ssdlite_mobilenet_v3_large", epochs=10, content=b"c")

    assert len(data(client.get("/api/registry/weights?model_arch=yolo"))["weights"]) == 2
    assert data(client.get("/api/registry/weights?q=bet"))["weights"][0]["display_name"] == "beta"

    ordered = data(client.get("/api/registry/weights?order_by=epochs&order=desc"))["weights"]
    assert [w["display_name"] for w in ordered] == ["beta", "alpha", "gamma"]


def test_pagination_bounds_are_validated(client):
    error(client.get("/api/registry/weights?limit=0"), status_code=400, code="validation_error")
    error(client.get("/api/registry/weights?offset=-1"), status_code=400, code="validation_error")


# --- 明細 -------------------------------------------------------------------

def test_weight_detail_carries_hyperparameters_and_evaluations(client, tmp_path):
    sha = _seed(tmp_path)
    _seed_eval(sha)

    body = data(client.get(f"/api/registry/weights/{sha}"))
    assert body["weight"]["sha256"] == sha
    assert body["training_run"]["epochs"] == 150
    assert body["training_run"]["hyperparameters"]["lr0"] == 0.01
    assert len(body["evaluations"]) == 1
    assert body["evaluations"][0]["micro_accuracy"] == pytest.approx(0.71)


def test_unknown_sha_returns_404(client):
    error(client.get("/api/registry/weights/" + "0" * 64), status_code=404, code="not_found")


# --- 指標帳本 ---------------------------------------------------------------

def test_evaluations_ledger_filters_and_sorts(client, tmp_path):
    sha_a = _seed(tmp_path, "alpha", content=b"a")
    sha_b = _seed(tmp_path, "beta", content=b"b")
    _seed_eval(sha_a, "eval_a", map50=0.80, micro=0.60)
    _seed_eval(sha_b, "eval_b", map50=0.91, micro=0.75, split="valid")

    rows = data(client.get("/api/registry/evaluations?order_by=map50&order=desc"))["evaluations"]
    assert [r["job_id"] for r in rows] == ["eval_b", "eval_a"]

    assert len(data(client.get(f"/api/registry/evaluations?weight_sha={sha_a}"))["evaluations"]) == 1
    assert len(data(client.get("/api/registry/evaluations?split=valid"))["evaluations"]) == 1
    assert data(client.get("/api/registry/evaluations?dataset_name=nope"))["evaluations"] == []


def test_stats_summarises_the_ledger(client, tmp_path):
    sha = _seed(tmp_path)
    _seed_eval(sha)

    body = data(client.get("/api/registry/stats"))
    assert body["total_weights"] == 1
    assert body["total_evaluations"] == 1
    assert body["datasets_evaluated"] == ["citrus_v5.zip"]
    assert {b["metric"] for b in body["best"]} >= {"mAP@50", "Micro-Accuracy (Jaccard)"}


# --- 刪除 -------------------------------------------------------------------

def test_delete_removes_weight_and_its_evaluations(client, tmp_path):
    sha = _seed(tmp_path)
    _seed_eval(sha)

    body = data(client.delete(f"/api/registry/weights/{sha}"))
    assert body == {"sha256": sha, "deleted_evaluations": 1}
    assert data(client.get("/api/registry/weights"))["weights"] == []
    error(client.delete(f"/api/registry/weights/{sha}"), status_code=404, code="not_found")


# --- 降級 -------------------------------------------------------------------

def test_endpoints_return_503_not_500_when_database_is_down(client):
    db_engine.disable_for_tests()

    for path in ("/api/registry/weights", "/api/registry/evaluations",
                 "/api/registry/weights/" + "0" * 64):
        detail = error(client.get(path), status_code=503, code="dependency_unavailable")
        assert "登錄簿" in detail["message"]

    error(client.delete("/api/registry/weights/" + "0" * 64),
          status_code=503, code="dependency_unavailable")


def test_runtime_failure_is_503_not_500(client, tmp_path, monkeypatch):
    """資料庫在**啟動之後**才掛掉（容器被停、網路斷線）。

    這條路徑與「啟動時就連不上」不同：`is_available()` 仍是 True，查詢會一路打到
    driver 才炸開。若不特別處理，通用 handler 會把它收成 HTTP 500 `internal_error`——
    但那並不是伺服器出錯，前端也就無法區分「登錄簿離線」與「後端壞掉」。

    這是實際發生過的缺陷：在 Docker 上 `docker compose stop db` 之後，
    /api/registry/weights 回的是 500。
    """
    from sqlalchemy.exc import OperationalError

    _seed(tmp_path)

    def explode(*_args, **_kwargs):
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    # 打在 Session 的執行層，模擬連線在查詢當下斷掉
    monkeypatch.setattr(
        "sqlalchemy.orm.Session.execute", explode, raising=True
    )

    detail = error(client.get("/api/registry/weights"),
                   status_code=503, code="dependency_unavailable")
    assert "登錄簿" in detail["message"]

    # stats 即使在這種狀況下也必須回 200，並誠實說 available:false
    body = data(client.get("/api/registry/stats"))
    assert body["available"] is False


def test_stats_stays_reachable_when_database_is_down(client):
    """stats 是前端判斷「登錄簿在不在」的依據，它自己絕不能因為資料庫掛掉而失敗。"""
    db_engine.disable_for_tests()
    body = data(client.get("/api/registry/stats"))
    assert body["available"] is False
    assert body["total_weights"] == 0
