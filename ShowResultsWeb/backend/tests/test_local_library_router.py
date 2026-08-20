"""
本機資料夾掃描的路由測試。

monkeypatch 目標必須是 router 自己 import 進來的名稱（local_library.LOCAL_LIBRARY_DIR），
不是 config.LOCAL_LIBRARY_DIR——與 test_export_routes.py patch export_service.EXPORTS_DIR
是同一個道理，patch 錯模組會悄悄不生效。
"""
import pytest
from fastapi.testclient import TestClient

import main
from app.routers import local_library
from app.services import dataset_manager, session_manager

ARGS_YAML = "epochs: 150\noptimizer: MuSGD\nmodel: yolo26n.pt\n"
DATA_YAML = "train: train/images\nval: valid/images\nnc: 2\nnames:\n- Aphid\n- Canker\n"


@pytest.fixture
def client():
    return TestClient(main.app)


@pytest.fixture(autouse=True)
def clean_state(tmp_path, monkeypatch):
    session_manager.ACTIVE_SESSIONS.clear()
    dataset_manager.ACTIVE_DATASETS.clear()
    monkeypatch.setattr(session_manager, "SESSIONS_FILE", str(tmp_path / "sessions.json"))
    monkeypatch.setattr(dataset_manager, "DATASETS_FILE", str(tmp_path / "datasets.json"))
    yield
    session_manager.ACTIVE_SESSIONS.clear()
    dataset_manager.ACTIVE_DATASETS.clear()


def _make_library(tmp_path, monkeypatch, with_run=True, with_dataset=True, loose_weight=None):
    lib = tmp_path / "LocalLibrary"
    lib.mkdir(exist_ok=True)

    if with_run:
        run = lib / "detect" / "my_run"
        (run / "weights").mkdir(parents=True)
        (run / "weights" / "best.pt").write_bytes(b"weights")
        (run / "args.yaml").write_text(ARGS_YAML, encoding="utf-8")

    if with_dataset:
        ds = lib / "mydata"
        (ds / "train" / "images").mkdir(parents=True)
        (ds / "train" / "labels").mkdir(parents=True)
        (ds / "data.yaml").write_text(DATA_YAML, encoding="utf-8")
        (ds / "train" / "images" / "i1.jpg").write_bytes(b"")
        (ds / "train" / "labels" / "i1.txt").write_text("0 .5 .5 .1 .1\n", encoding="utf-8")

    if loose_weight:
        (lib / loose_weight).write_bytes(b"loose")

    monkeypatch.setattr(local_library, "LOCAL_LIBRARY_DIR", lib)
    return lib


# --- GET /api/local-library --------------------------------------------------

def test_info_returns_path_and_never_registers(client, tmp_path, monkeypatch):
    """唯讀端點：重複呼叫都不能改動任何狀態（釘住「不自動掃描」的 API 契約）。"""
    lib = _make_library(tmp_path, monkeypatch)

    for _ in range(3):
        res = client.get("/api/local-library")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "success"
        assert body["exists"] is True
        assert body["path"].endswith("LocalLibrary")

    assert session_manager.ACTIVE_SESSIONS == {}
    assert dataset_manager.ACTIVE_DATASETS == {}


def test_info_reports_missing_directory(client, tmp_path, monkeypatch):
    monkeypatch.setattr(local_library, "LOCAL_LIBRARY_DIR", tmp_path / "nope")
    body = client.get("/api/local-library").json()
    assert body["exists"] is False


# --- POST /api/local-library/scan --------------------------------------------

def test_scan_registers_run_and_dataset(client, tmp_path, monkeypatch):
    _make_library(tmp_path, monkeypatch)

    body = client.post("/api/local-library/scan").json()

    assert body["status"] == "success"
    assert len(body["registered_sessions"]) == 1
    assert len(body["registered_datasets"]) == 1

    sid = body["registered_sessions"][0]
    session = session_manager.ACTIVE_SESSIONS[sid]
    assert session["source"] == "local_library"
    assert session["source_type"] == "local_library_run"
    assert session["weights_path"].endswith("my_run/weights/best.pt")

    did = body["registered_datasets"][0]
    assert dataset_manager.ACTIVE_DATASETS[did]["source_path"]


def test_rescan_is_idempotent(client, tmp_path, monkeypatch):
    """重複掃描不得產生重複註冊。"""
    _make_library(tmp_path, monkeypatch)

    first = client.post("/api/local-library/scan").json()
    assert len(first["registered_sessions"]) == 1
    assert len(first["registered_datasets"]) == 1

    second = client.post("/api/local-library/scan").json()
    assert second["registered_sessions"] == []
    assert second["registered_datasets"] == []
    assert second["skipped_sessions"] == 1
    assert second["skipped_datasets"] == 1

    assert len(session_manager.ACTIVE_SESSIONS) == 1
    assert len(dataset_manager.ACTIVE_DATASETS) == 1


def test_loose_weight_uses_single_weight_source_type(client, tmp_path, monkeypatch):
    """
    散落權重檔的 source_type 必須是字面值 "single_weight"——
    ModelMetricCard.jsx 用精確比對決定 "Weight Only" 徽章，沒有 fallback。
    """
    _make_library(tmp_path, monkeypatch, with_run=False, with_dataset=False, loose_weight="best.pt")

    body = client.post("/api/local-library/scan").json()
    sid = body["registered_sessions"][0]
    session = session_manager.ACTIVE_SESSIONS[sid]

    assert session["source_type"] == "single_weight"
    assert session["model_arch"] == "yolo"


def test_loose_pth_detected_as_ssdlite_without_rename(client, tmp_path, monkeypatch):
    lib = _make_library(tmp_path, monkeypatch, with_run=False, with_dataset=False,
                        loose_weight="best_model.pth")

    body = client.post("/api/local-library/scan").json()
    session = session_manager.ACTIVE_SESSIONS[body["registered_sessions"][0]]

    assert session["model_arch"] == "ssdlite_mobilenet_v3_large"
    assert session["weights_path"].endswith(".pth"), "不能改使用者的檔名"
    assert (lib / "best_model.pth").exists()


def test_run_weights_not_double_registered_as_loose(client, tmp_path, monkeypatch):
    """run 內的 weights/best.pt 不能又被當成散落權重檔註冊一次。"""
    _make_library(tmp_path, monkeypatch, with_dataset=False)
    body = client.post("/api/local-library/scan").json()
    assert len(body["registered_sessions"]) == 1


def test_models_only_library_still_succeeds(client, tmp_path, monkeypatch):
    """只有模型、沒有資料集時，資料集偵測失敗不得影響模型註冊。"""
    _make_library(tmp_path, monkeypatch, with_dataset=False)
    body = client.post("/api/local-library/scan").json()
    assert body["status"] == "success"
    assert len(body["registered_sessions"]) == 1
    assert body["registered_datasets"] == []


def test_dataset_only_library_still_succeeds(client, tmp_path, monkeypatch):
    _make_library(tmp_path, monkeypatch, with_run=False)
    body = client.post("/api/local-library/scan").json()
    assert body["status"] == "success"
    assert body["registered_sessions"] == []
    assert len(body["registered_datasets"]) == 1


def test_empty_library_is_not_an_error(client, tmp_path, monkeypatch):
    _make_library(tmp_path, monkeypatch, with_run=False, with_dataset=False)
    body = client.post("/api/local-library/scan").json()
    assert body["status"] == "success"
    assert body["registered_sessions"] == []
    assert body["registered_datasets"] == []
    assert "未找到" in body["message"]


def test_missing_directory_returns_error(client, tmp_path, monkeypatch):
    monkeypatch.setattr(local_library, "LOCAL_LIBRARY_DIR", tmp_path / "nope")
    body = client.post("/api/local-library/scan").json()
    assert body["status"] == "error"
    assert "找不到本機資料夾" in body["message"]


def test_scan_stops_cleanly_at_max_sessions(client, tmp_path, monkeypatch):
    """達上限時乾淨停止，不報錯。"""
    monkeypatch.setattr(local_library, "MAX_SESSIONS", 1)
    lib = _make_library(tmp_path, monkeypatch, with_dataset=False)
    # 第二個 run
    run2 = lib / "detect" / "run_b"
    (run2 / "weights").mkdir(parents=True)
    (run2 / "weights" / "best.pt").write_bytes(b"weights")
    (run2 / "args.yaml").write_text(ARGS_YAML, encoding="utf-8")

    body = client.post("/api/local-library/scan").json()

    assert body["status"] == "success"
    assert len(body["registered_sessions"]) == 1
    assert len(session_manager.ACTIVE_SESSIONS) == 1
    assert "上限" in body["message"]


def test_scanned_sessions_are_not_persisted(client, tmp_path, monkeypatch):
    """端到端確認：掃描後 sessions.json 不含 LocalLibrary 來源的紀錄。"""
    import json
    sessions_file = tmp_path / "sessions.json"
    monkeypatch.setattr(session_manager, "SESSIONS_FILE", str(sessions_file))
    _make_library(tmp_path, monkeypatch, with_dataset=False)

    body = client.post("/api/local-library/scan").json()
    assert len(body["registered_sessions"]) == 1

    if sessions_file.exists():
        written = json.loads(sessions_file.read_text(encoding="utf-8"))
        assert written == {}, "LocalLibrary session 不該被寫入磁碟"
