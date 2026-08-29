"""
本機資料夾掃描的路由測試。

monkeypatch 目標必須是**使用該名稱的模組**，不是 config——與 test_export_routes.py
patch export_service.EXPORTS_DIR 是同一個道理，patch 錯模組會悄悄不生效。
掃描路徑經過兩個模組：router 讀 local_library.LOCAL_LIBRARY_DIR 判斷存在與否，
scanner 讀 library_scanner.MAX_SESSIONS 與 LOCAL_LIBRARY_EXTRACT_DIR。

掃描與註冊是兩個階段：scan 純唯讀只回報候選項，register 才真正載入。
"""
import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

import main
from apitest import data, error
from app.routers import local_library
from app.services import dataset_manager, library_scanner, session_manager

ARGS_YAML = "epochs: 150\noptimizer: MuSGD\nmodel: yolo26n.pt\n"
DATA_YAML = "train: train/images\nval: valid/images\nnc: 2\nnames:\n- Aphid\n- Canker\n"


@pytest.fixture
def client():
    return TestClient(main.app)


@pytest.fixture(autouse=True)
def clean_state(tmp_path, monkeypatch):
    session_manager.ACTIVE_SESSIONS.clear()
    dataset_manager.ACTIVE_DATASETS.clear()
    library_scanner._CANDIDATES.clear()
    monkeypatch.setattr(session_manager, "SESSIONS_FILE", str(tmp_path / "sessions.json"))
    monkeypatch.setattr(dataset_manager, "DATASETS_FILE", str(tmp_path / "datasets.json"))
    # ZIP 解壓落點導到 tmp，避免測試污染真實的 extracted_runs/
    monkeypatch.setattr(library_scanner, "LOCAL_LIBRARY_EXTRACT_DIR", tmp_path / "ll_extract")
    yield
    session_manager.ACTIVE_SESSIONS.clear()
    dataset_manager.ACTIVE_DATASETS.clear()
    library_scanner._CANDIDATES.clear()


def _write_run(base, name):
    run = base / name
    (run / "weights").mkdir(parents=True)
    (run / "weights" / "best.pt").write_bytes(b"weights")
    (run / "args.yaml").write_text(ARGS_YAML, encoding="utf-8")
    return run


def _write_dataset(base, name):
    ds = base / name
    (ds / "train" / "images").mkdir(parents=True)
    (ds / "train" / "labels").mkdir(parents=True)
    (ds / "data.yaml").write_text(DATA_YAML, encoding="utf-8")
    (ds / "train" / "images" / "i1.jpg").write_bytes(b"")
    (ds / "train" / "labels" / "i1.txt").write_text("0 .5 .5 .1 .1\n", encoding="utf-8")
    return ds


def _make_library(tmp_path, monkeypatch, with_run=True, with_dataset=True, loose_weight=None):
    lib = tmp_path / "LocalLibrary"
    lib.mkdir(exist_ok=True)

    if with_run:
        _write_run(lib / "detect", "my_run")
    if with_dataset:
        _write_dataset(lib, "mydata")
    if loose_weight:
        (lib / loose_weight).write_bytes(b"loose")

    monkeypatch.setattr(local_library, "LOCAL_LIBRARY_DIR", lib)
    return lib


def _add_run_zip(lib, zip_name, run_names):
    """建一個內含數個 YOLO run 的訓練成果 ZIP。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for run_name in run_names:
            zf.writestr(f"detect/{run_name}/args.yaml", ARGS_YAML)
            zf.writestr(f"detect/{run_name}/weights/best.pt", b"weights")
            zf.writestr(f"detect/{run_name}/results.csv", "epoch,metrics/mAP50(B)\n1,0.8\n")
    (lib / zip_name).write_bytes(buf.getvalue())


def _add_dataset_zip(lib, zip_name):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("bundle/data.yaml", DATA_YAML)
        zf.writestr("bundle/train/images/i1.jpg", b"")
        zf.writestr("bundle/train/labels/i1.txt", "0 .5 .5 .1 .1\n")
    (lib / zip_name).write_bytes(buf.getvalue())


def _scan(client):
    return data(client.post("/api/local-library/scan"))


def _ids(body, **filters):
    return [
        c["candidate_id"]
        for c in body["candidates"]
        if all(c.get(k) == v for k, v in filters.items())
    ]


# --- GET /api/local-library --------------------------------------------------

def test_info_returns_path_and_never_registers(client, tmp_path, monkeypatch):
    """唯讀端點：重複呼叫都不能改動任何狀態（釘住「不自動掃描」的 API 契約）。"""
    _make_library(tmp_path, monkeypatch)

    for _ in range(3):
        body = data(client.get("/api/local-library"))
        assert body["exists"] is True
        assert body["path"].endswith("LocalLibrary")

    assert session_manager.ACTIVE_SESSIONS == {}
    assert dataset_manager.ACTIVE_DATASETS == {}


def test_info_reports_missing_directory(client, tmp_path, monkeypatch):
    monkeypatch.setattr(local_library, "LOCAL_LIBRARY_DIR", tmp_path / "nope")
    assert data(client.get("/api/local-library"))["exists"] is False


# --- POST /scan：純探索 -------------------------------------------------------

def test_scan_lists_candidates_without_registering_anything(client, tmp_path, monkeypatch):
    """
    掃描是唯讀的。這是與第一版最重要的行為差異，也是整份測試裡最該釘住的一條：
    若哪天 scan 又開始自動註冊，MAX_SESSIONS 會再次決定「使用者拿到哪幾個模型」。
    """
    _make_library(tmp_path, monkeypatch)

    body = _scan(client)

    assert body["total_models"] == 1
    assert body["total_datasets"] == 1
    assert session_manager.ACTIVE_SESSIONS == {}, "掃描不得註冊任何 session"
    assert dataset_manager.ACTIVE_DATASETS == {}, "掃描不得註冊任何 dataset"


def test_scan_is_repeatable_and_ids_are_stable(client, tmp_path, monkeypatch):
    """同一份內容重複掃描要拿到同一組 candidate_id，否則使用者的勾選會失效。"""
    _make_library(tmp_path, monkeypatch)

    first = sorted(c["candidate_id"] for c in _scan(client)["candidates"])
    second = sorted(c["candidate_id"] for c in _scan(client)["candidates"])

    assert first == second


def test_scan_finds_runs_inside_zip(client, tmp_path, monkeypatch):
    """
    ZIP 內的訓練成果必須被找到。

    這是使用者回報的核心缺陷：把 v5.zip / v8.zip 放進資料夾後完全看不到內容——
    .zip 不在權重副檔名清單裡，而 os.walk 不會走進壓縮檔。
    """
    lib = _make_library(tmp_path, monkeypatch, with_run=False, with_dataset=False)
    _add_run_zip(lib, "v5.zip", ["run_v5", "run_v5-2"])

    body = _scan(client)

    assert body["total_models"] == 2
    names = {c["name"] for c in body["candidates"]}
    assert names == {"run_v5", "run_v5-2"}
    assert all(c["source_kind"] == "zip_run" for c in body["candidates"])


def test_scan_finds_multiple_datasets(client, tmp_path, monkeypatch):
    """
    多個資料集必須各自現身。

    第一版對整棵樹只跑一次分析、取分數最高的根目錄，因此第二個資料集會被無聲吞掉。
    """
    lib = _make_library(tmp_path, monkeypatch, with_run=False, with_dataset=False)
    _write_dataset(lib, "ds_a")
    _write_dataset(lib, "ds_b")
    _add_dataset_zip(lib, "ds_c.zip")

    body = _scan(client)

    assert body["total_datasets"] == 3
    assert {c["name"] for c in body["candidates"]} == {"ds_a", "ds_b", "ds_c.zip"}


def test_scan_reports_already_registered_items(client, tmp_path, monkeypatch):
    _make_library(tmp_path, monkeypatch)
    first = _scan(client)
    client.post("/api/local-library/register", json={"candidate_ids": _ids(first)})

    second = _scan(client)
    assert all(c["already_registered"] for c in second["candidates"])


def test_empty_library_is_not_an_error(client, tmp_path, monkeypatch):
    _make_library(tmp_path, monkeypatch, with_run=False, with_dataset=False)
    body = _scan(client)
    assert body["candidates"] == []
    assert "未找到" in body["message"]


def test_missing_directory_returns_error(client, tmp_path, monkeypatch):
    monkeypatch.setattr(local_library, "LOCAL_LIBRARY_DIR", tmp_path / "nope")
    res = client.post("/api/local-library/scan")
    detail = error(res, status_code=422, code="precondition_failed")
    assert "找不到本機資料夾" in detail["message"]


def test_run_weights_not_double_listed_as_loose(client, tmp_path, monkeypatch):
    """run 內的 weights/best.pt 不能又被當成散落權重檔列一次。"""
    _make_library(tmp_path, monkeypatch, with_dataset=False)
    assert _scan(client)["total_models"] == 1


# --- POST /register：只載入勾選的項目 -----------------------------------------

def test_register_only_loads_selected_items(client, tmp_path, monkeypatch):
    """使用者的勾選就是全部——沒勾的絕不能被順便載入。"""
    lib = _make_library(tmp_path, monkeypatch, with_run=False, with_dataset=False)
    _write_run(lib / "detect", "wanted")
    _write_run(lib / "detect", "unwanted")

    body = _scan(client)
    wanted = next(c for c in body["candidates"] if c["name"] == "wanted")

    res = data(client.post("/api/local-library/register",
                      json={"candidate_ids": [wanted["candidate_id"]]}))

    assert len(res["registered_sessions"]) == 1
    assert len(session_manager.ACTIVE_SESSIONS) == 1
    session = session_manager.ACTIVE_SESSIONS[res["registered_sessions"][0]]
    assert session["weights_path"].endswith("wanted/weights/best.pt")
    assert session["source"] == "local_library"
    assert session["source_type"] == "local_library_run"


def test_register_extracts_zip_run_and_leaves_zip_untouched(client, tmp_path, monkeypatch):
    """ZIP 來源要能真的載入，且原始 ZIP 不得被動到。"""
    lib = _make_library(tmp_path, monkeypatch, with_run=False, with_dataset=False)
    _add_run_zip(lib, "v5.zip", ["run_v5"])
    before = sorted(p.name for p in lib.iterdir())

    body = _scan(client)
    res = data(client.post("/api/local-library/register",
                      json={"candidate_ids": _ids(body)}))

    assert len(res["registered_sessions"]) == 1
    session = session_manager.ACTIVE_SESSIONS[res["registered_sessions"][0]]

    import os
    assert os.path.exists(session["weights_path"]), "解壓後的權重必須真的存在"
    assert "ll_extract" in session["weights_path"], "解壓落點必須在受管目錄，不能在使用者資料夾"
    assert sorted(p.name for p in lib.iterdir()) == before, "不得寫入 LOCAL_LIBRARY_DIR"


def test_register_is_idempotent(client, tmp_path, monkeypatch):
    """重複載入同一項目不得產生重複註冊。"""
    _make_library(tmp_path, monkeypatch)
    body = _scan(client)
    ids = _ids(body)

    first = data(client.post("/api/local-library/register", json={"candidate_ids": ids}))
    assert len(first["registered_sessions"]) == 1
    assert len(first["registered_datasets"]) == 1

    second = data(client.post("/api/local-library/register", json={"candidate_ids": ids}))
    assert second["registered_sessions"] == []
    assert second["registered_datasets"] == []
    assert second["skipped"] == 2

    assert len(session_manager.ACTIVE_SESSIONS) == 1
    assert len(dataset_manager.ACTIVE_DATASETS) == 1


def test_register_stops_cleanly_at_max_sessions(client, tmp_path, monkeypatch):
    """達上限時乾淨停止，不報錯，且訊息要說明原因。"""
    monkeypatch.setattr(library_scanner, "MAX_SESSIONS", 1)
    lib = _make_library(tmp_path, monkeypatch, with_dataset=False)
    _write_run(lib / "detect", "run_b")

    body = _scan(client)
    assert body["total_models"] == 2

    res = data(client.post("/api/local-library/register", json={"candidate_ids": _ids(body)}))

    assert len(res["registered_sessions"]) == 1
    assert len(session_manager.ACTIVE_SESSIONS) == 1
    assert "上限" in res["message"]


def test_loose_weight_uses_single_weight_source_type(client, tmp_path, monkeypatch):
    """
    散落權重檔的 source_type 必須是字面值 "single_weight"——
    ModelMetricCard.jsx 用精確比對決定 "Weight Only" 徽章，沒有 fallback。
    """
    _make_library(tmp_path, monkeypatch, with_run=False, with_dataset=False, loose_weight="best.pt")

    body = _scan(client)
    res = data(client.post("/api/local-library/register", json={"candidate_ids": _ids(body)}))
    session = session_manager.ACTIVE_SESSIONS[res["registered_sessions"][0]]

    assert session["source_type"] == "single_weight"
    assert session["model_arch"] == "yolo"


def test_loose_pth_detected_as_ssdlite_without_rename(client, tmp_path, monkeypatch):
    lib = _make_library(tmp_path, monkeypatch, with_run=False, with_dataset=False,
                        loose_weight="best_model.pth")

    body = _scan(client)
    res = data(client.post("/api/local-library/register", json={"candidate_ids": _ids(body)}))
    session = session_manager.ACTIVE_SESSIONS[res["registered_sessions"][0]]

    assert session["model_arch"] == "ssdlite_mobilenet_v3_large"
    assert session["weights_path"].endswith(".pth"), "不能改使用者的檔名"
    assert (lib / "best_model.pth").exists()


def test_register_rejects_empty_selection(client, tmp_path, monkeypatch):
    _make_library(tmp_path, monkeypatch)
    error(client.post("/api/local-library/register", json={"candidate_ids": []}),
          status_code=400, code="validation_error")


def test_register_reports_stale_candidate_ids(client, tmp_path, monkeypatch):
    """掃描結果過期後（例如後端重啟）舊的 ID 要誠實回報，而不是靜默無事發生。"""
    _make_library(tmp_path, monkeypatch)
    body = data(client.post("/api/local-library/register",
                            json={"candidate_ids": ["deadbeefcafe"]}))
    assert "重新掃描" in body["message"]


def test_registered_sessions_are_not_persisted(client, tmp_path, monkeypatch):
    """端到端確認：載入後 sessions.json 不含 LocalLibrary 來源的紀錄。"""
    sessions_file = tmp_path / "sessions.json"
    monkeypatch.setattr(session_manager, "SESSIONS_FILE", str(sessions_file))
    _make_library(tmp_path, monkeypatch, with_dataset=False)

    body = _scan(client)
    res = data(client.post("/api/local-library/register", json={"candidate_ids": _ids(body)}))
    assert len(res["registered_sessions"]) == 1

    if sessions_file.exists():
        written = json.loads(sessions_file.read_text(encoding="utf-8"))
        assert written == {}, "LocalLibrary session 不該被寫入磁碟"


def test_models_only_library_still_works(client, tmp_path, monkeypatch):
    """只有模型、沒有資料集時，資料集偵測失敗不得影響模型。"""
    _make_library(tmp_path, monkeypatch, with_dataset=False)
    body = _scan(client)
    assert body["total_models"] == 1
    assert body["total_datasets"] == 0


def test_dataset_only_library_still_works(client, tmp_path, monkeypatch):
    _make_library(tmp_path, monkeypatch, with_run=False)
    body = _scan(client)
    assert body["total_models"] == 0
    assert body["total_datasets"] == 1
