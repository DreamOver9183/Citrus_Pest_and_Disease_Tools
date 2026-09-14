"""
即時推論的 imgsz 參數。

model_manager 是持鎖的單例，這裡把 load_model/predict 整個換掉——測試只關心路由把 imgsz
正確傳下去、並回報實際使用的解析度，不需要真的載入模型。
"""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import main
from apitest import data, error
from app.routers import inference
from app.services import session_manager


@pytest.fixture
def client():
    return TestClient(main.app)


class _FakeResult:
    boxes = None

    def save(self, filename):
        with open(filename, "wb") as f:
            f.write(b"\xff\xd8\xff")


@pytest.fixture
def predict_calls(tmp_path, monkeypatch):
    weights = tmp_path / "best.pt"
    weights.write_bytes(b"0")
    session_manager.ACTIVE_SESSIONS.clear()
    monkeypatch.setattr(session_manager, "SESSIONS_FILE", str(tmp_path / "sessions.json"))
    session_manager.ACTIVE_SESSIONS["run_a"] = {
        "session_id": "run_a", "model_arch": "yolo",
        "weights_path": str(weights), "dir_path": str(tmp_path),
    }
    for name in ("TEMP_DIR", "UPLOAD_TEMP_DIR", "EXTRACTED_RUNS_DIR"):
        target = tmp_path / name.lower()
        target.mkdir()
        monkeypatch.setattr(inference, name, str(target))

    calls = []
    manager = inference.model_manager

    def fake_predict(path, conf=0.25, imgsz=None):
        calls.append({"conf": conf, "imgsz": imgsz})
        return [_FakeResult()]

    monkeypatch.setattr(manager, "load_model", lambda *a, **k: None)
    monkeypatch.setattr(manager, "predict", fake_predict)
    monkeypatch.setattr(manager, "current_model", SimpleNamespace(names={}, overrides={"imgsz": 640}))
    monkeypatch.setattr(manager, "get_current_device_label", lambda: "CPU")
    yield calls
    session_manager.ACTIVE_SESSIONS.clear()


def _post(client, **fields):
    form = {"session_id": "run_a", **{k: str(v) for k, v in fields.items()}}
    return client.post(
        "/api/inference",
        data=form,
        files={"file": ("leaf.jpg", b"\xff\xd8\xff", "image/jpeg")},
    )


def test_imgsz_is_forwarded_and_reported(client, predict_calls):
    body = data(_post(client, imgsz=320))
    assert predict_calls[-1]["imgsz"] == 320
    assert body["imgsz_used"] == 320


def test_omitted_imgsz_reports_the_model_default(client, predict_calls):
    """不指定時 ultralytics 沿用訓練尺寸，畫面必須標出是多少，而不是空白。"""
    body = data(_post(client))
    assert predict_calls[-1]["imgsz"] is None
    assert body["imgsz_used"] == 640


@pytest.mark.parametrize("bad", [300, 128, 1600])
def test_invalid_imgsz_is_rejected_before_inference(client, predict_calls, bad):
    error(_post(client, imgsz=bad), status_code=400, code="validation_error")
    assert predict_calls == []
