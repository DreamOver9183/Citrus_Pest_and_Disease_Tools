"""
逐張檢視路由的測試。

monkeypatch 目標是使用該名稱的模組（`review_service.REVIEW_DIR`），不是 config。
"""
import io
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import main
from apitest import data, error
from app.services import dataset_manager, review_service as rs, session_manager


@pytest.fixture
def client():
    return TestClient(main.app)


@pytest.fixture(autouse=True)
def clean_state(tmp_path, monkeypatch):
    session_manager.ACTIVE_SESSIONS.clear()
    dataset_manager.ACTIVE_DATASETS.clear()
    rs.REVIEW_JOBS.clear()
    rs._ITEMS_CACHE.clear()
    monkeypatch.setattr(session_manager, "SESSIONS_FILE", str(tmp_path / "sessions.json"))
    monkeypatch.setattr(dataset_manager, "DATASETS_FILE", str(tmp_path / "datasets.json"))
    monkeypatch.setattr(rs, "REVIEW_DIR", tmp_path / "reviews")
    yield
    session_manager.ACTIVE_SESSIONS.clear()
    dataset_manager.ACTIVE_DATASETS.clear()
    rs.REVIEW_JOBS.clear()
    rs._ITEMS_CACHE.clear()


def _add_session(sid="run_a", arch="yolo", weights="/fake/best.pt"):
    session_manager.ACTIVE_SESSIONS[sid] = {
        "session_id": sid, "custom_name": "模型 A", "model_arch": arch,
        "weights_path": weights, "dir_path": "/fake",
    }
    return sid


def _add_dataset(tmp_path, did="ds_a", container=True):
    root = tmp_path / f"data_{did}"
    (root / "test" / "images").mkdir(parents=True, exist_ok=True)
    (root / "test" / "labels").mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    Image.new("RGB", (100, 80)).save(buf, "JPEG")
    (root / "test" / "images" / "a.jpg").write_bytes(buf.getvalue())
    (root / "test" / "labels" / "a.txt").write_text("0 0.3 0.375 0.4 0.5\n", encoding="utf-8")
    dataset_manager.ACTIVE_DATASETS[did] = {
        "dataset_id": did, "zip_name": "mydata", "format": "yolo",
        "source_container": str(root) if container else None,
        "source_inner_prefix": "",
        "splits": [{"name": "train"}, {"name": "test"}],
        "declared_names": ["Aphid", "Canker"],
    }
    return did


def _stub(monkeypatch):
    model = SimpleNamespace(names={0: "Aphid", 1: "Canker"}, overrides={"imgsz": 640})
    monkeypatch.setattr(rs, "_load_model", lambda w: model)
    monkeypatch.setattr(
        rs, "_predict_image",
        lambda m, image, imgsz: [{"cls": 1, "conf": 0.8, "box": [10.0, 10.0, 50.0, 50.0]}],
    )


def _done_job(client, tmp_path, monkeypatch, **body):
    _stub(monkeypatch)
    sid, did = _add_session(), _add_dataset(tmp_path)
    job = data(client.post("/api/reviews", json={"session_id": sid, "dataset_id": did, **body}))["job"]
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        current = data(client.get(f"/api/reviews/{job['job_id']}"))["job"]
        if current["state"] in ("done", "failed"):
            return current
        time.sleep(0.05)
    raise AssertionError("逐張檢視未在時限內完成")


# --- targets ------------------------------------------------------------------

def test_targets_explain_why_a_session_cannot_be_reviewed(client, tmp_path, monkeypatch):
    monkeypatch.setattr(rs.export_capabilities, "_find_spec", lambda name: False)
    _add_session("run_pt")
    _add_session("run_ssd", arch="ssdlite_mobilenet_v3_large")
    _add_session("run_tflite", weights="/fake/model.tflite")
    _add_dataset(tmp_path)

    body = data(client.get("/api/reviews/targets"))
    by_id = {s["session_id"]: s for s in body["sessions"]}
    assert by_id["run_pt"]["available"] is True
    assert by_id["run_ssd"]["available"] is False
    assert by_id["run_tflite"]["available"] is False and "Docker" in by_id["run_tflite"]["reason"]
    assert body["imgsz_choices"] == [320, 416, 512, 640]
    assert body["datasets"][0]["default_split"] == "test"


# --- 送出 ---------------------------------------------------------------------

def test_submit_and_query_items(client, tmp_path, monkeypatch):
    job = _done_job(client, tmp_path, monkeypatch, imgsz=320)
    assert job["state"] == "done", job["message"]
    assert job["imgsz_used"] == 320

    items = data(client.get(f"/api/reviews/{job['job_id']}/items", params={"conf": 0.25}))
    assert items["summary"]["wrong"] == 1, "類別 1 的預測壓在類別 0 的標註上 → 類別錯"
    item = items["items"][0]
    assert item["preds"][0]["status"] == "wrong"

    single = data(client.get(f"/api/reviews/{job['job_id']}/item", params={"name": "a.jpg"}))
    assert single["item"]["name"] == "a.jpg"


@pytest.mark.parametrize("imgsz", [300, 2000])
def test_submit_rejects_invalid_imgsz(client, tmp_path, imgsz):
    sid, did = _add_session(), _add_dataset(tmp_path)
    res = client.post("/api/reviews", json={"session_id": sid, "dataset_id": did, "imgsz": imgsz})
    error(res, status_code=400, code="validation_error")


def test_submit_rejects_ssd_and_uploaded_datasets(client, tmp_path):
    ssd = _add_session("run_ssd", arch="ssdlite_mobilenet_v3_large")
    did = _add_dataset(tmp_path)
    error(client.post("/api/reviews", json={"session_id": ssd, "dataset_id": did}),
          status_code=422, code="precondition_failed")

    sid = _add_session()
    uploaded = _add_dataset(tmp_path, "ds_up", container=False)
    res = client.post("/api/reviews", json={"session_id": sid, "dataset_id": uploaded})
    assert "上傳" in error(res, status_code=422, code="precondition_failed")["message"]


def test_submit_rejects_missing_ids(client, tmp_path):
    _add_dataset(tmp_path)
    error(client.post("/api/reviews", json={"session_id": "nope", "dataset_id": "ds_a"}),
          status_code=404, code="not_found")


# --- 查詢參數與影像 -----------------------------------------------------------

def test_items_reject_unknown_filters_and_low_thresholds(client, tmp_path, monkeypatch):
    job = _done_job(client, tmp_path, monkeypatch)
    base = f"/api/reviews/{job['job_id']}/items"
    error(client.get(base, params={"status": "bogus"}), status_code=400, code="validation_error")
    error(client.get(base, params={"classes": "a,b"}), status_code=400, code="validation_error")
    # 低於存檔門檻的框根本沒存，不能假裝查得到
    error(client.get(base, params={"conf": 0.01}), status_code=400, code="validation_error")


def test_image_route_serves_thumbnails_and_rejects_unknown_indexes(client, tmp_path, monkeypatch):
    job = _done_job(client, tmp_path, monkeypatch)
    res = client.get(f"/api/reviews/{job['job_id']}/image/0", params={"variant": "thumb"})
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("image/jpeg")

    error(client.get(f"/api/reviews/{job['job_id']}/image/99"), status_code=404, code="not_found")


def test_export_is_a_self_contained_html_attachment(client, tmp_path, monkeypatch):
    job = _done_job(client, tmp_path, monkeypatch)
    res = client.get(
        f"/api/reviews/{job['job_id']}/export",
        params={"status": "all", "title": "<script>alert(1)</script>"},
    )
    assert res.status_code == 200
    assert "attachment" in res.headers["content-disposition"]

    html = res.text
    assert "data:image/jpeg;base64," in html, "影像必須內嵌，離線才打得開"
    assert 'src="http' not in html and 'href="http' not in html
    assert "逐張計數（非評估指標）" in html
    assert "錯判：Aphid→Canker" in html
    assert "<script>alert(1)</script>" not in html, "標題來自使用者輸入，必須跳脫"


def test_export_rejects_limits_above_the_cap(client, tmp_path, monkeypatch):
    job = _done_job(client, tmp_path, monkeypatch)
    res = client.get(f"/api/reviews/{job['job_id']}/export", params={"limit": 5000})
    error(res, status_code=400, code="validation_error")


def test_delete_review(client, tmp_path, monkeypatch):
    job = _done_job(client, tmp_path, monkeypatch)
    data(client.delete(f"/api/reviews/{job['job_id']}"))
    error(client.get(f"/api/reviews/{job['job_id']}"), status_code=404, code="not_found")
