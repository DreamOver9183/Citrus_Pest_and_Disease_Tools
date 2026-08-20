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
