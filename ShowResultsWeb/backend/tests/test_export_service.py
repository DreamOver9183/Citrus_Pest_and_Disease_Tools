import os
from pathlib import Path

import pytest

from app.schemas import ExportJobOut
from app.services import export_capabilities, export_service


@pytest.fixture(autouse=True)
def clean_jobs(tmp_path, monkeypatch):
    """EXPORT_JOBS 是模組級 global，且測試不可寫進真實的 exports 目錄。"""
    exports_dir = tmp_path / "exports"
    exports_dir.mkdir()
    monkeypatch.setattr(export_service, "EXPORTS_DIR", exports_dir)
    export_service.EXPORT_JOBS.clear()
    export_capabilities.refresh()
    yield exports_dir
    export_service.EXPORT_JOBS.clear()
    export_capabilities.refresh()


def _session(session_id="run_abc12345", name="my model", arch="yolo", weights="best.pt", tmp_path=None):
    weights_path = str((tmp_path / weights)) if tmp_path else f"/fake/{weights}"
    if tmp_path:
        (tmp_path / weights).write_bytes(b"fake-weights")
    return {
        "session_id": session_id,
        "custom_name": name,
        "model_arch": arch,
        "weights_path": weights_path.replace("\\", "/"),
        "format_label": "PyTorch",
    }


# --- Schema 完整性（最高價值）-----------------------------------------------

def test_job_public_emits_every_schema_field(tmp_path):
    """
    response_model_exclude_unset=True 會把缺席的 key 從 JSON 剪掉並在前端變 undefined。
    _job_public 必須逐欄輸出，四種狀態皆然。
    """
    expected = set(ExportJobOut.model_fields)
    for state, stage in [("queued", "queued"), ("running", "exporting"),
                         ("done", "done"), ("failed", "failed")]:
        job = {
            "job_id": "exp_test0001",
            "session_id": "run_abc12345",
            "session_name": "m",
            "format": "onnx",
            "state": state,
            "stage": stage,
            "job_dir": str(tmp_path),
            "log_tail": [],
        }
        public = export_service._job_public(job)
        assert set(public) == expected, f"state={state} 欄位不齊: {expected ^ set(public)}"


def test_download_url_only_present_when_done(tmp_path):
    base = {"job_id": "exp_1", "job_dir": str(tmp_path), "log_tail": []}
    assert export_service._job_public({**base, "state": "running", "stage": "exporting"})["download_url"] is None
    assert export_service._job_public({**base, "state": "done", "stage": "done"})["download_url"] == "/api/export/exp_1/download"


# --- 成功與失敗路徑 ---------------------------------------------------------

def test_export_happy_path(tmp_path, monkeypatch, clean_jobs):
    def fake_run(job_dir, src_pt, fmt):
        out = Path(job_dir) / "raw_output.onnx"
        out.write_bytes(b"x" * 200_000)
        return out, {"imgsz": 640}

    monkeypatch.setattr(export_service, "_run_export", fake_run)

    job = export_service.submit_export(_session(tmp_path=tmp_path), "onnx")
    assert job["state"] == "queued"
    assert export_service.wait_for_job(job["job_id"], timeout=15)

    final = export_service.get_job(job["job_id"])
    assert final["state"] == "done"
    assert final["stage"] == "done"
    assert final["progress"] == 100
    assert final["artifact_name"] == "my_model.onnx"     # 由 custom_name 清理而來
    assert final["artifact_size_mb"] == pytest.approx(0.19, abs=0.02)
    assert final["download_url"] == f"/api/export/{job['job_id']}/download"
    assert (clean_jobs / job["job_id"] / "manifest.json").exists()
    # 暫存的 .pt 複本在成功後應被刪除
    assert not (clean_jobs / job["job_id"] / "my_model.pt").exists()


def test_export_failure_maps_message_and_worker_survives(tmp_path, monkeypatch, clean_jobs):
    calls = {"n": 0}

    def flaky(job_dir, src_pt, fmt):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ModuleNotFoundError("No module named 'onnx'")
        out = Path(job_dir) / "ok.onnx"
        out.write_bytes(b"y" * 1000)
        return out, {"imgsz": 640}

    monkeypatch.setattr(export_service, "_run_export", flaky)

    first = export_service.submit_export(_session(tmp_path=tmp_path), "onnx")
    assert export_service.wait_for_job(first["job_id"], timeout=15)
    failed = export_service.get_job(first["job_id"])
    assert failed["state"] == "failed"
    assert "onnx" in failed["message"]
    assert "缺少匯出所需的套件" in failed["message"]

    # worker 必須存活，後續 job 仍能完成
    second = export_service.submit_export(_session(session_id="run_def67890", tmp_path=tmp_path), "onnx")
    assert export_service.wait_for_job(second["job_id"], timeout=15)
    assert export_service.get_job(second["job_id"])["state"] == "done"


def test_failed_job_dir_is_cleaned(tmp_path, monkeypatch, clean_jobs):
    monkeypatch.setattr(export_service, "_run_export",
                        lambda job_dir, src, fmt: (_ for _ in ()).throw(RuntimeError("boom")))
    job = export_service.submit_export(_session(tmp_path=tmp_path), "onnx")
    assert export_service.wait_for_job(job["job_id"], timeout=15)
    assert export_service.get_job(job["job_id"])["state"] == "failed"
    assert not (clean_jobs / job["job_id"]).exists()


# --- 檔名清理 ---------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("runs - YOLO26n_v8", "runs_-_YOLO26n_v8"),
    ("a/b:c*d?e", "abcde"),
    ("柑橘 病蟲害 模型", "柑橘_病蟲害_模型"),
    ("", "FALLBACK"),
    ("///", "FALLBACK"),
    ("...", "FALLBACK"),
])
def test_safe_stem(raw, expected):
    assert export_service.safe_stem(raw, "FALLBACK") == expected


def test_safe_stem_is_never_a_path(tmp_path):
    stem = export_service.safe_stem("../../etc/passwd", "fallback")
    assert "/" not in stem and "\\" not in stem


# --- 下載路徑安全 -----------------------------------------------------------

def test_resolve_artifact_rejects_path_outside_exports(tmp_path, clean_jobs):
    outside = tmp_path / "secret.txt"
    outside.write_text("nope", encoding="utf-8")
    export_service.EXPORT_JOBS["exp_evil"] = {
        "job_id": "exp_evil", "state": "done", "stage": "done",
        "artifact_path": str(outside), "job_dir": str(clean_jobs / "exp_evil"),
        "log_tail": [],
    }
    assert export_service.resolve_artifact("exp_evil") is None


def test_resolve_artifact_rejects_unfinished_job(clean_jobs):
    export_service.EXPORT_JOBS["exp_run"] = {
        "job_id": "exp_run", "state": "running", "stage": "exporting",
        "artifact_path": None, "job_dir": str(clean_jobs / "exp_run"), "log_tail": [],
    }
    assert export_service.resolve_artifact("exp_run") is None
    assert export_service.resolve_artifact("exp_missing") is None


# --- 清理與淘汰 -------------------------------------------------------------

def test_purge_exports_for_session_only_targets_that_session(tmp_path, monkeypatch, clean_jobs):
    monkeypatch.setattr(export_service, "_run_export",
                        lambda job_dir, src, fmt: (_write(Path(job_dir) / "o.onnx"), {"imgsz": 640}))

    a = export_service.submit_export(_session(session_id="run_aaaa1111", tmp_path=tmp_path), "onnx")
    export_service.wait_for_job(a["job_id"], timeout=15)
    b = export_service.submit_export(_session(session_id="run_bbbb2222", name="other", tmp_path=tmp_path), "onnx")
    export_service.wait_for_job(b["job_id"], timeout=15)

    removed = export_service.purge_exports_for_session("run_aaaa1111")
    assert removed == 1
    assert a["job_id"] not in export_service.EXPORT_JOBS
    assert b["job_id"] in export_service.EXPORT_JOBS
    assert not (clean_jobs / a["job_id"]).exists()
    assert (clean_jobs / b["job_id"]).exists()


def test_purge_flags_running_job_instead_of_deleting(clean_jobs):
    export_service.EXPORT_JOBS["exp_running"] = {
        "job_id": "exp_running", "session_id": "run_x", "state": "running",
        "stage": "exporting", "job_dir": str(clean_jobs / "exp_running"), "log_tail": [],
    }
    export_service.purge_exports_for_session("run_x")
    assert "exp_running" in export_service.EXPORT_JOBS
    assert export_service.EXPORT_JOBS["exp_running"]["purge_on_finish"] is True


def test_eviction_drops_oldest_finished_never_running(clean_jobs, monkeypatch):
    monkeypatch.setattr(export_service, "MAX_EXPORT_JOBS", 2)
    for i, (state, created) in enumerate([
        ("done", "2026-01-01T00:00:00+00:00"),
        ("running", "2026-01-02T00:00:00+00:00"),
        ("done", "2026-01-03T00:00:00+00:00"),
    ]):
        jid = f"exp_{i}"
        export_service.EXPORT_JOBS[jid] = {
            "job_id": jid, "state": state, "stage": state, "created_at": created,
            "job_dir": str(clean_jobs / jid), "log_tail": [],
        }
    with export_service.EXPORT_JOBS_LOCK:
        export_service._evict_finished_locked()

    assert "exp_0" not in export_service.EXPORT_JOBS      # 最舊的已完成被淘汰
    assert "exp_1" in export_service.EXPORT_JOBS          # 執行中的絕不淘汰
    assert "exp_2" in export_service.EXPORT_JOBS


def test_delete_running_job_defers_to_worker(clean_jobs):
    export_service.EXPORT_JOBS["exp_r"] = {
        "job_id": "exp_r", "state": "running", "stage": "exporting",
        "job_dir": str(clean_jobs / "exp_r"), "log_tail": [],
    }
    export_service.delete_export_job("exp_r")
    assert "exp_r" in export_service.EXPORT_JOBS
    assert export_service.EXPORT_JOBS["exp_r"]["purge_on_finish"] is True

    with pytest.raises(KeyError):
        export_service.delete_export_job("exp_nope")


# --- 啟動重建 ---------------------------------------------------------------

def test_load_from_disk_keeps_only_valid_done_jobs(clean_jobs):
    import json

    def make(job_id, state, with_artifact, session_id="run_ok", schema=1):
        d = clean_jobs / job_id
        d.mkdir()
        artifact = d / "m.onnx"
        if with_artifact:
            artifact.write_bytes(b"z" * 100)
        (d / "manifest.json").write_text(json.dumps({
            "schema_version": schema, "job_id": job_id, "state": state,
            "session_id": session_id, "artifact_path": str(artifact),
            "stage": state, "log_tail": [],
        }), encoding="utf-8")

    make("exp_good", "done", True)
    make("exp_noartifact", "done", False)
    make("exp_running", "running", True)
    make("exp_orphan", "done", True, session_id="run_gone")
    make("exp_oldschema", "done", True, schema=0)
    (clean_jobs / "exp_nomanifest").mkdir()

    export_service.load_export_jobs_from_disk(known_session_ids={"run_ok"})

    assert set(export_service.EXPORT_JOBS) == {"exp_good"}
    for gone in ["exp_noartifact", "exp_running", "exp_orphan", "exp_oldschema", "exp_nomanifest"]:
        assert not (clean_jobs / gone).exists(), f"{gone} 應被清除"


def _write(path: Path) -> Path:
    path.write_bytes(b"o" * 5000)
    return path


def test_running_job_elapsed_uses_monotonic_clock(clean_jobs):
    """
    回歸測試：進行中 job 的 elapsed_seconds 必須用 time.monotonic() 相減。

    _started_monotonic 來自 time.monotonic()（原點任意、通常很小），若拿
    time.time()（epoch，約 1.7e9）去相減，UI 會顯示「29785752 分 60 秒」這種值。
    完成的 job 走另一條路徑所以看不出來，只有進行中的會露餡。
    """
    import time as _time

    job = {
        "job_id": "exp_running1",
        "session_id": "run_x",
        "state": "running",
        "stage": "exporting",
        "started_at": "2026-01-01T00:00:00+00:00",
        "finished_at": None,
        "elapsed_seconds": None,
        "_started_monotonic": _time.monotonic() - 3.0,
        "log_tail": [],
    }
    public = export_service._job_public(job)

    assert public["elapsed_seconds"] is not None
    # 約 3 秒；若誤用 epoch 時鐘會是十億等級
    assert 2.0 <= public["elapsed_seconds"] <= 10.0, (
        f"elapsed_seconds={public['elapsed_seconds']} —— 疑似混用了 time.time() 與 time.monotonic()"
    )
