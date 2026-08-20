"""
回歸測試：delete_session 絕不能刪掉「容器目錄」本身。

session_manager.delete_session() 用字串切割從 dir_path 反推要刪除的目標，並靠一份
白名單擋下容器目錄。若某個容器名不在白名單裡，刪一個 session 會 rmtree 掉整個
容器根目錄，連帶清空其他功能的所有資料。

datasets/ 曾踩過這個坑（見 dataset_manager.py 的模組註解），exports/ 是同一類風險。
"""
import os

import pytest

from app.services import session_manager


@pytest.fixture(autouse=True)
def clean_active_sessions():
    session_manager.ACTIVE_SESSIONS.clear()
    yield
    session_manager.ACTIVE_SESSIONS.clear()


def _make_session(tmp_path, container: str, monkeypatch):
    """建立一個 dir_path 落在 extracted_runs/<container>/<leaf> 底下的 session。"""
    extracted = tmp_path / "extracted_runs"
    container_dir = extracted / container
    leaf = container_dir / "leaf_item"
    (leaf / "weights").mkdir(parents=True)
    weights = leaf / "weights" / "best.pt"
    weights.write_bytes(b"fake")

    # 容器目錄下的哨兵：代表其他功能的資料，絕不能因刪 session 而消失
    sentinel = container_dir / "sentinel.txt"
    sentinel.write_text("important", encoding="utf-8")

    monkeypatch.setattr(session_manager, "SESSIONS_FILE", str(extracted / "sessions.json"))
    session_manager.ACTIVE_SESSIONS["run_test1234"] = {
        "session_id": "run_test1234",
        "dir_path": str(leaf).replace("\\", "/"),
        "weights_path": str(weights).replace("\\", "/"),
        "model_arch": "yolo",
    }
    return container_dir, sentinel, leaf


@pytest.mark.parametrize("container", ["exports", "datasets", "weight", "images", "reports"])
def test_delete_session_never_removes_container_dir(tmp_path, monkeypatch, container):
    container_dir, sentinel, leaf = _make_session(tmp_path, container, monkeypatch)

    session_manager.delete_session("run_test1234")

    assert "run_test1234" not in session_manager.ACTIVE_SESSIONS
    assert container_dir.exists(), f"容器目錄 {container}/ 不該被刪除"
    assert sentinel.exists(), f"{container}/ 下的其他資料不該被連帶刪除"
    assert sentinel.read_text(encoding="utf-8") == "important"


def test_delete_session_removes_its_own_leaf_under_weight(tmp_path, monkeypatch):
    """相對地，weight/ 底下屬於該 session 的葉目錄本來就該被清掉。"""
    container_dir, sentinel, leaf = _make_session(tmp_path, "weight", monkeypatch)

    session_manager.delete_session("run_test1234")

    assert container_dir.exists()
    assert sentinel.exists()
    assert not leaf.exists(), "weight/ 底下該 session 自己的目錄應被刪除"


def test_delete_session_never_touches_paths_outside_extracted_runs(tmp_path, monkeypatch):
    """
    回歸測試：LocalLibrary 來源的 session，其 dir_path 完全不含 "extracted_runs"。

    既有的參數化測試只涵蓋「extracted_runs/ 底下的各種容器名稱」，從未測過
    「路徑根本不在 extracted_runs 之內」這個形狀——而那正是 LocalLibrary 的形狀。
    刪除這種 session 只能移除記憶體項目，絕不能碰使用者的實體檔案。
    """
    library = tmp_path / "LocalLibrary" / "my_run"
    (library / "weights").mkdir(parents=True)
    weights = library / "weights" / "best.pt"
    weights.write_bytes(b"user-owned")
    (library / "args.yaml").write_text("epochs: 10\n", encoding="utf-8")

    monkeypatch.setattr(session_manager, "SESSIONS_FILE", str(tmp_path / "sessions.json"))
    session_manager.ACTIVE_SESSIONS["run_locallib1"] = {
        "session_id": "run_locallib1",
        "dir_path": str(library).replace("\\", "/"),
        "weights_path": str(weights).replace("\\", "/"),
        "model_arch": "yolo",
        "source": "local_library",
    }

    session_manager.delete_session("run_locallib1")

    assert "run_locallib1" not in session_manager.ACTIVE_SESSIONS
    assert library.exists(), "使用者的資料夾絕不能被刪除"
    assert weights.exists(), "使用者的權重檔絕不能被刪除"
    assert weights.read_bytes() == b"user-owned"
    assert (tmp_path / "LocalLibrary").exists()
