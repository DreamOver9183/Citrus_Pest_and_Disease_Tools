"""
評估與報告路由的測試。

monkeypatch 目標必須是**使用該名稱的模組**（`evaluation_service.EVAL_DIR`、
`report_service.REPORTS_DIR`），不是 config——與 test_export_routes.py 同樣的道理，
patch 錯模組會悄悄不生效。
"""
import time

import pytest
from fastapi.testclient import TestClient

import main
from app.services import dataset_manager, evaluation_service as ev, report_service, session_manager


@pytest.fixture
def client():
    return TestClient(main.app)


@pytest.fixture(autouse=True)
def clean_state(tmp_path, monkeypatch):
    session_manager.ACTIVE_SESSIONS.clear()
    dataset_manager.ACTIVE_DATASETS.clear()
    ev.EVAL_JOBS.clear()
    monkeypatch.setattr(session_manager, "SESSIONS_FILE", str(tmp_path / "sessions.json"))
    monkeypatch.setattr(dataset_manager, "DATASETS_FILE", str(tmp_path / "datasets.json"))
    monkeypatch.setattr(ev, "EVAL_DIR", tmp_path / "evaluations")
    monkeypatch.setattr(report_service, "REPORTS_DIR", tmp_path / "reports")
    yield
    session_manager.ACTIVE_SESSIONS.clear()
    dataset_manager.ACTIVE_DATASETS.clear()
    ev.EVAL_JOBS.clear()


def _add_session(sid="run_a", arch="yolo", name="模型 A"):
    session_manager.ACTIVE_SESSIONS[sid] = {
        "session_id": sid, "custom_name": name, "model_arch": arch,
        "weights_path": "/fake/best.pt", "dir_path": "/fake",
    }
    return sid


def _add_dataset(tmp_path, did="ds_a", container=True):
    root = tmp_path / f"data_{did}"
    (root / "test" / "images").mkdir(parents=True, exist_ok=True)
    (root / "test" / "labels").mkdir(parents=True, exist_ok=True)
    (root / "test" / "images" / "a.jpg").write_bytes(b"\xff\xd8\xff")
    (root / "test" / "labels" / "a.txt").write_text("0 .5 .5 .2 .2\n", encoding="utf-8")

    dataset_manager.ACTIVE_DATASETS[did] = {
        "dataset_id": did, "zip_name": "mydata", "format": "yolo",
        "source_container": str(root) if container else None,
        "source_inner_prefix": "",
        "splits": [{"name": "train"}, {"name": "test"}],
        "declared_names": ["Aphid", "Canker"],
        "total_images": 1, "total_annotations": 1,
    }
    return did


def _stub_run(monkeypatch, write_plot=False):
    """
    取代真實的 val()。真實流程會把圖表寫進 job_dir/val/，所以 write_plot 也照做——
    圖表端點有路徑包含檢查，把檔案放在 job 目錄之外會（正確地）被擋下。
    """
    monkeypatch.setattr(ev, "peek_model_names", lambda w: {0: "Aphid", 1: "Canker"})

    def fake(job_dir, weights, data_yaml, log_sink):
        plots = {}
        if write_plot:
            val_dir = job_dir / "val"
            val_dir.mkdir(parents=True, exist_ok=True)
            target = val_dir / "confusion_matrix.png"
            target.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 200)
            plots["confusion_matrix"] = str(target).replace("\\", "/")
        return {
            "model_names": {0: "Aphid", 1: "Canker"},
            "overall": {"map50": 0.8, "map50_95": 0.6, "precision": 0.75, "recall": 0.7},
            "per_class": [
                {"class_id": 0, "name": "Aphid", "precision": .8, "recall": .7, "ap50": .85, "ap50_95": .6},
                {"class_id": 1, "name": "Canker", "precision": .5, "recall": .3, "ap50": .32, "ap50_95": .2},
            ],
            "speed_ms": {"inference": 42.0},
            "plots": plots,
        }

    monkeypatch.setattr(ev, "_run_validation", fake)


def _wait(client, job_id, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/api/evaluations/{job_id}").json()
        if body.get("job", {}).get("state") in ("done", "failed"):
            return body["job"]
        time.sleep(0.05)
    raise AssertionError("評估未在時限內完成")


# --- /evaluations/targets -----------------------------------------------------

def test_targets_lists_unavailable_datasets_with_a_reason(client, tmp_path):
    """
    不可評估的資料集仍要列出並附原因。

    比照匯出功能「顯示但停用並說明原因」的既有慣例——把它藏起來，使用者只會困惑於
    「我的資料集去哪了」。
    """
    _add_dataset(tmp_path, "ds_ok", container=True)
    _add_dataset(tmp_path, "ds_uploaded", container=False)

    body = client.get("/api/evaluations/targets").json()
    by_id = {d["dataset_id"]: d for d in body["datasets"]}

    assert by_id["ds_ok"]["available"] is True
    assert by_id["ds_ok"]["default_split"] == "test"
    assert by_id["ds_uploaded"]["available"] is False
    assert "上傳" in by_id["ds_uploaded"]["reason"]


def test_targets_marks_ssd_sessions_unavailable(client):
    _add_session("run_yolo", arch="yolo")
    _add_session("run_ssd", arch="ssdlite_mobilenet_v3_large")

    body = client.get("/api/evaluations/targets").json()
    by_id = {s["session_id"]: s for s in body["sessions"]}

    assert by_id["run_yolo"]["available"] is True
    assert by_id["run_ssd"]["available"] is False
    assert "YOLO" in by_id["run_ssd"]["reason"]


def test_targets_never_mutates_state(client, tmp_path):
    _add_session()
    _add_dataset(tmp_path)
    for _ in range(3):
        client.get("/api/evaluations/targets")
    assert ev.EVAL_JOBS == {}


# --- 送出 ---------------------------------------------------------------------

def test_submit_runs_and_returns_metrics(client, tmp_path, monkeypatch):
    _stub_run(monkeypatch)
    sid, did = _add_session(), _add_dataset(tmp_path)

    body = client.post("/api/evaluations", data={"session_id": sid, "dataset_id": did}).json()
    assert body["status"] == "success"

    job = _wait(client, body["job"]["job_id"])
    assert job["state"] == "done"
    assert job["split"] == "test", "未指定 split 時應預設 test"
    assert job["overall"]["map50"] == 0.8
    assert len(job["size_profile"]) == 2


def test_submit_rejects_ssd_session(client, tmp_path):
    sid = _add_session("run_ssd", arch="ssdlite_mobilenet_v3_large")
    did = _add_dataset(tmp_path)
    body = client.post("/api/evaluations", data={"session_id": sid, "dataset_id": did}).json()
    assert body["status"] == "error"
    assert "YOLO" in body["message"]


def test_submit_rejects_uploaded_zip_dataset(client, tmp_path):
    sid = _add_session()
    did = _add_dataset(tmp_path, "ds_uploaded", container=False)
    body = client.post("/api/evaluations", data={"session_id": sid, "dataset_id": did}).json()
    assert body["status"] == "error"
    assert "上傳" in body["message"]


def test_submit_rejects_unknown_split(client, tmp_path):
    sid, did = _add_session(), _add_dataset(tmp_path)
    body = client.post(
        "/api/evaluations", data={"session_id": sid, "dataset_id": did, "split": "holdout"}
    ).json()
    assert body["status"] == "error"
    assert "holdout" in body["message"]


def test_submit_rejects_missing_ids(client, tmp_path):
    _add_dataset(tmp_path)
    body = client.post("/api/evaluations", data={"session_id": "nope", "dataset_id": "ds_a"}).json()
    assert body["status"] == "error"


# --- 圖表與刪除 ---------------------------------------------------------------

def test_plot_endpoint_serves_the_generated_image(client, tmp_path, monkeypatch):
    _stub_run(monkeypatch, write_plot=True)

    sid, did = _add_session(), _add_dataset(tmp_path)
    body = client.post("/api/evaluations", data={"session_id": sid, "dataset_id": did}).json()
    job = _wait(client, body["job"]["job_id"])

    assert "confusion_matrix" in job["plot_urls"]
    res = client.get(job["plot_urls"]["confusion_matrix"])
    assert res.status_code == 200
    assert res.content.startswith(b"\x89PNG")


def test_delete_evaluation(client, tmp_path, monkeypatch):
    _stub_run(monkeypatch)
    sid, did = _add_session(), _add_dataset(tmp_path)
    body = client.post("/api/evaluations", data={"session_id": sid, "dataset_id": did}).json()
    job_id = body["job"]["job_id"]
    _wait(client, job_id)

    assert client.post(f"/api/evaluations/{job_id}/delete").json()["status"] == "success"
    assert client.get(f"/api/evaluations/{job_id}").json()["status"] == "error"


# --- 報告 ---------------------------------------------------------------------

def _completed_job(client, tmp_path, monkeypatch, sid=None, did=None):
    _stub_run(monkeypatch)
    sid = sid or _add_session()
    did = did or _add_dataset(tmp_path)
    body = client.post("/api/evaluations", data={"session_id": sid, "dataset_id": did}).json()
    return _wait(client, body["job"]["job_id"])


def test_report_generation_produces_a_self_contained_html(client, tmp_path, monkeypatch):
    job = _completed_job(client, tmp_path, monkeypatch)

    body = client.post("/api/reports", json={"job_ids": [job["job_id"]]}).json()
    assert body["status"] == "success"
    meta = body["report"]
    assert meta["filename"].endswith(".html")
    assert meta["size_kb"] > 0

    html = client.get(f"/api/reports/{meta['report_id']}/view").text
    assert "實測指標總覽" in html
    assert "Aphid" in html and "Canker" in html
    assert 'src="http' not in html, "報告不得引用外部資源，離線必須可讀"


def test_report_marks_multi_dataset_comparisons_as_incomparable(client, tmp_path, monkeypatch):
    """
    不同資料集的指標並列時必須警告。

    這正是本功能存在的理由：消融比較的前提是共同的評估協定，把不同測試集的數字
    放在同一張表卻不說明，比不做這個功能更糟。
    """
    job_a = _completed_job(client, tmp_path, monkeypatch,
                           sid=_add_session("run_a"), did=_add_dataset(tmp_path, "ds_a"))
    job_b = _completed_job(client, tmp_path, monkeypatch,
                           sid=_add_session("run_b"), did=_add_dataset(tmp_path, "ds_b"))
    # 讓兩者的資料集名稱不同
    ev.EVAL_JOBS[job_b["job_id"]]["dataset_name"] = "another_dataset"

    body = client.post("/api/reports", json={"job_ids": [job_a["job_id"], job_b["job_id"]]}).json()
    html = client.get(f"/api/reports/{body['report']['report_id']}/view").text
    assert "不可直接互相比較" in html


def test_report_rejects_empty_and_unfinished_selections(client, tmp_path, monkeypatch):
    assert client.post("/api/reports", json={"job_ids": []}).json()["status"] == "error"
    assert client.post("/api/reports", json={"job_ids": ["eval_nope"]}).json()["status"] == "error"


def test_report_listing_and_deletion(client, tmp_path, monkeypatch):
    job = _completed_job(client, tmp_path, monkeypatch)
    meta = client.post("/api/reports", json={"job_ids": [job["job_id"]]}).json()["report"]

    listed = client.get("/api/reports").json()
    assert any(r["report_id"] == meta["report_id"] for r in listed["reports"])

    assert client.post(f"/api/reports/{meta['report_id']}/delete").json()["status"] == "success"
    assert client.get("/api/reports").json()["reports"] == []


def test_report_download_is_an_attachment(client, tmp_path, monkeypatch):
    job = _completed_job(client, tmp_path, monkeypatch)
    meta = client.post("/api/reports", json={"job_ids": [job["job_id"]]}).json()["report"]

    res = client.get(f"/api/reports/{meta['report_id']}/download")
    assert res.status_code == 200
    assert "attachment" in res.headers.get("content-disposition", "")
