import json
import os

import pytest

from app.services import session_manager


@pytest.fixture(autouse=True)
def clean_active_sessions():
    """ACTIVE_SESSIONS is a module-level global; keep tests isolated from each other."""
    session_manager.ACTIVE_SESSIONS.clear()
    yield
    session_manager.ACTIVE_SESSIONS.clear()


def test_load_sessions_from_disk_skips_ghost_sessions(tmp_path, monkeypatch):
    real_weights = tmp_path / "best.pt"
    real_weights.write_bytes(b"fake-weights")

    sessions_file = tmp_path / "sessions.json"
    sessions_file.write_text(
        json.dumps(
            {
                "run_alive": {"session_id": "run_alive", "weights_path": str(real_weights)},
                "run_ghost": {"session_id": "run_ghost", "weights_path": str(tmp_path / "missing.pt")},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(session_manager, "SESSIONS_FILE", str(sessions_file))

    session_manager.load_sessions_from_disk()

    assert "run_alive" in session_manager.ACTIVE_SESSIONS
    assert "run_ghost" not in session_manager.ACTIVE_SESSIONS


def test_load_sessions_from_disk_missing_file_is_noop(tmp_path, monkeypatch):
    monkeypatch.setattr(session_manager, "SESSIONS_FILE", str(tmp_path / "does_not_exist.json"))
    session_manager.load_sessions_from_disk()
    assert session_manager.ACTIVE_SESSIONS == {}


def test_save_and_reload_round_trip(tmp_path, monkeypatch):
    sessions_file = tmp_path / "sessions.json"
    monkeypatch.setattr(session_manager, "SESSIONS_FILE", str(sessions_file))

    weights = tmp_path / "best.pt"
    weights.write_bytes(b"fake-weights")

    session_manager.ACTIVE_SESSIONS["run_x"] = {
        "session_id": "run_x",
        "weights_path": str(weights),
    }
    session_manager.save_sessions_to_disk()

    session_manager.ACTIVE_SESSIONS.clear()
    session_manager.load_sessions_from_disk()

    assert "run_x" in session_manager.ACTIVE_SESSIONS


def test_cleanup_legacy_runs_removes_only_matching_folders(tmp_path, monkeypatch):
    extracted_runs = tmp_path / "extracted_runs"
    extracted_runs.mkdir()

    legacy_dir = extracted_runs / "run_abcd1234"
    legacy_dir.mkdir()
    (legacy_dir / "dummy.txt").write_text("x")

    keep_dir = extracted_runs / "weight"
    keep_dir.mkdir()
    (keep_dir / "dummy.txt").write_text("x")

    not_legacy_dir = extracted_runs / "run_not_hex_pattern_zzzz"
    not_legacy_dir.mkdir()

    temp_dir = extracted_runs / "temp_output"
    temp_dir.mkdir()
    (temp_dir / "stale.png").write_text("x")

    monkeypatch.setattr(session_manager, "EXTRACTED_RUNS_DIR", str(extracted_runs))
    monkeypatch.setattr(session_manager, "TEMP_DIR", str(temp_dir))

    session_manager.cleanup_legacy_runs()

    assert not legacy_dir.exists()
    assert keep_dir.exists()
    assert not_legacy_dir.exists()
    assert temp_dir.exists()
    assert list(temp_dir.iterdir()) == []


# --- LocalLibrary 來源不落地（最高價值測試）---------------------------------

def test_local_library_sessions_are_not_persisted(tmp_path, monkeypatch):
    """
    LocalLibrary 掃描而來的 session 絕不能寫進 sessions.json。

    這是「直到系統關閉」語意的實作機制：不寫入 → 重啟時自然不會被還原。
    同時必須確認過濾是**選擇性**的——一般上傳的 session 仍要正常持久化，
    否則就是把既有功能整組弄壞了。
    """
    target = tmp_path / "sessions.json"
    monkeypatch.setattr(session_manager, "SESSIONS_FILE", str(target))

    normal_weights = tmp_path / "uploaded.pt"
    normal_weights.write_bytes(b"w")
    local_weights = tmp_path / "LocalLibrary" / "scanned.pt"
    local_weights.parent.mkdir()
    local_weights.write_bytes(b"w")

    session_manager.ACTIVE_SESSIONS["run_normal01"] = {
        "session_id": "run_normal01",
        "weights_path": str(normal_weights).replace("\\", "/"),
        "dir_path": str(tmp_path).replace("\\", "/"),
        "source_type": "single_weight",
    }
    session_manager.ACTIVE_SESSIONS["run_local001"] = {
        "session_id": "run_local001",
        "weights_path": str(local_weights).replace("\\", "/"),
        "dir_path": str(local_weights.parent).replace("\\", "/"),
        "source_type": "single_weight",
        "source": "local_library",
    }

    session_manager.save_sessions_to_disk()

    written = json.loads(target.read_text(encoding="utf-8"))
    assert "run_normal01" in written, "一般 session 必須照常持久化"
    assert "run_local001" not in written, "LocalLibrary session 不該被寫入"

    # 重新載入後也不會冒出來
    session_manager.ACTIVE_SESSIONS.clear()
    session_manager.load_sessions_from_disk()
    assert "run_normal01" in session_manager.ACTIVE_SESSIONS
    assert "run_local001" not in session_manager.ACTIVE_SESSIONS
