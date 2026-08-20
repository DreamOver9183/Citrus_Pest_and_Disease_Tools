"""
匯出路由測試。

存在的主要理由是路由順序那一項：/export/{job_id} 若宣告在 /export/capabilities
之前，後者會被當成 job_id="capabilities" 而回 404。這種 bug 在 code review 看不
出來，但在瀏覽器裡立刻致命。
"""
import pytest
from fastapi.testclient import TestClient

import main
from app.services import export_capabilities, export_service
from app.services.session_manager import ACTIVE_SESSIONS


@pytest.fixture
def client(tmp_path, monkeypatch):
    exports_dir = tmp_path / "exports"
    exports_dir.mkdir()
    monkeypatch.setattr(export_service, "EXPORTS_DIR", exports_dir)
    export_service.EXPORT_JOBS.clear()
    ACTIVE_SESSIONS.clear()
    export_capabilities.refresh()
    yield TestClient(main.app)
    export_service.EXPORT_JOBS.clear()
    ACTIVE_SESSIONS.clear()
    export_capabilities.refresh()


def _register_session(tmp_path, session_id="run_abc12345", arch="yolo", weights="best.pt"):
    wp = tmp_path / weights
    wp.write_bytes(b"fake")
    ACTIVE_SESSIONS[session_id] = {
        "session_id": session_id,
        "custom_name": "test model",
        "model_arch": arch,
        "weights_path": str(wp).replace("\\", "/"),
        "format_label": "PyTorch",
    }
    return session_id


# --- 路由順序（本檔存在的主因）---------------------------------------------

def test_capabilities_route_is_not_shadowed_by_job_id(client):
    res = client.get("/api/export/capabilities")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "success"
    assert "formats" in body
    assert {f["format"] for f in body["formats"]} == {"onnx", "litert"}


def test_jobs_route_is_not_shadowed_by_job_id(client):
    res = client.get("/api/export/jobs")
    assert res.status_code == 200
    assert res.json()["jobs"] == {}


# --- 提交閘 -----------------------------------------------------------------

def test_unknown_session_returns_error_not_500(client):
    res = client.post("/api/export", data={"session_id": "nope", "format": "onnx"})
    assert res.status_code == 200
    assert res.json()["status"] == "error"


def test_ssdlite_session_is_refused_without_enqueueing(client, tmp_path):
    sid = _register_session(tmp_path, arch="ssdlite_mobilenet_v3_large")
    res = client.post("/api/export", data={"session_id": sid, "format": "onnx"})
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "error"
    assert "YOLO" in body["message"]
    assert export_service.EXPORT_JOBS == {}, "不符資格的請求不該建立 job"


def test_unavailable_format_is_refused(client, tmp_path, monkeypatch):
    sid = _register_session(tmp_path)
    monkeypatch.setattr(export_capabilities.platform, "system", lambda: "Windows")
    monkeypatch.setattr(export_capabilities.platform, "machine", lambda: "AMD64")
    export_capabilities.refresh()

    res = client.post("/api/export", data={"session_id": sid, "format": "litert"})
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "error"
    assert "Docker" in body["message"]
    assert export_service.EXPORT_JOBS == {}


def test_unknown_format_is_refused(client, tmp_path):
    sid = _register_session(tmp_path)
    res = client.post("/api/export", data={"session_id": sid, "format": "coreml"})
    assert res.status_code == 200
    assert res.json()["status"] == "error"


# --- 成功流程與下載 ---------------------------------------------------------

def test_submit_then_poll_then_download(client, tmp_path, monkeypatch):
    from pathlib import Path

    def fake_run(job_dir, src_pt, fmt):
        out = Path(job_dir) / "raw.onnx"
        out.write_bytes(b"ONNXFAKE" * 500)
        return out, {"imgsz": 640}

    monkeypatch.setattr(export_service, "_run_export", fake_run)
    sid = _register_session(tmp_path)

    res = client.post("/api/export", data={"session_id": sid, "format": "onnx"})
    assert res.status_code == 200
    job_id = res.json()["job"]["job_id"]

    assert export_service.wait_for_job(job_id, timeout=15)

    status = client.get(f"/api/export/{job_id}")
    assert status.status_code == 200
    job = status.json()["job"]
    assert job["state"] == "done"
    assert job["download_url"] == f"/api/export/{job_id}/download"

    dl = client.get(job["download_url"])
    assert dl.status_code == 200
    assert dl.content == b"ONNXFAKE" * 500
    assert "attachment" in dl.headers.get("content-disposition", "")
    assert dl.headers.get("content-type") == "application/octet-stream"


def test_download_unknown_job_returns_404(client):
    assert client.get("/api/export/exp_missing/download").status_code == 404


def test_get_unknown_job_returns_404(client):
    assert client.get("/api/export/exp_missing").status_code == 404


def test_delete_unknown_job_returns_404(client):
    assert client.post("/api/export/exp_missing/delete").status_code == 404


def test_jobs_filter_by_session_and_active(client, tmp_path, monkeypatch):
    from pathlib import Path
    monkeypatch.setattr(export_service, "_run_export",
                        lambda job_dir, src, fmt: _mk(Path(job_dir) / "a.onnx"))
    sid = _register_session(tmp_path)
    res = client.post("/api/export", data={"session_id": sid, "format": "onnx"})
    job_id = res.json()["job"]["job_id"]
    export_service.wait_for_job(job_id, timeout=15)

    assert job_id in client.get(f"/api/export/jobs?session_id={sid}").json()["jobs"]
    assert client.get("/api/export/jobs?session_id=run_other").json()["jobs"] == {}
    # 已完成的 job 不算 active
    assert client.get("/api/export/jobs?active=1").json()["jobs"] == {}


def _mk(path):
    path.write_bytes(b"x" * 100)
    return path
