"""
模型權重格式匯出的 job 機制。

**硬規則：本模組不得 import model_service。**
匯出一律自建一個用完即丟的 YOLO 實例，理由有三，各自都足以成立：
  1. ModelManager._lock 是非重入的 threading.Lock，且 predict() 全程持有。走
     ModelManager 會讓每個推論請求排在數十秒到數分鐘的匯出後面；若在持鎖狀態下
     再呼叫 load_model() 就直接死鎖。
  2. load_model() 會 del 掉常駐模型 —— 匯出會把使用者在「即時診斷」載入的模型踢掉。
  3. load_model() 會把模型搬到 device（可能是 CUDA），而匯出要固定在 CPU。

併發模型：單一 daemon 執行緒 + 有界 queue.Queue。刻意不用 ThreadPoolExecutor，
因為 concurrent.futures 會註冊 atexit hook 去 join 非 daemon 執行緒，Ctrl-C 會被
卡住整個匯出的時間（而 shutdown(cancel_futures=True) 救不了已在跑的任務）。

沒有 cancel 狀態：執行中的 model.export() 無法從 Python 中止，給一顆按了沒作用的
取消鍵比不給更糟。卡死的 job 由有界佇列降級成誠實的「佇列已滿」。
"""
import gc
import json
import logging
import os
import queue
import re
import shutil
import threading
import time
import traceback
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import (
    EXPORT_JOB_TTL_HOURS,
    EXPORTS_DIR,
    MAX_EXPORT_JOBS,
    MAX_QUEUED_EXPORTS,
)
from app.services.export_capabilities import format_suffix

JOB_SCHEMA_VERSION = 1

# job_id -> job dict
EXPORT_JOBS: Dict[str, Dict[str, Any]] = {}
# 所有對 EXPORT_JOBS 的讀-改-寫都必須持有此鎖。
# 鎖序規則：絕不在持有 EXPORT_JOBS_LOCK 時取得 SESSIONS_LOCK，反之亦然。
EXPORT_JOBS_LOCK = threading.RLock()

_QUEUE: "queue.Queue[str]" = queue.Queue(maxsize=MAX_QUEUED_EXPORTS)
_WORKER: Optional[threading.Thread] = None
_WORKER_LOCK = threading.Lock()

LOG_TAIL_MAXLEN = 40

# stage -> (中文標籤, progress)。progress 無法真實反映匯出進度（ultralytics 只有
# on_export_start / on_export_end 兩個 callback），所以 exporting 階段前端要走
# 不定量動畫而不是顯示這個數字。
STAGES = {
    "queued": ("等待中", 0),
    "staging": ("準備權重", 5),
    "loading": ("載入模型", 15),
    "exporting": ("轉換中", 25),
    "finalizing": ("收尾", 90),
    "done": ("完成", 100),
    "failed": ("失敗", 0),
}

_UNSAFE_NAME_CHARS = re.compile(r'[/\\:*?"<>|\x00-\x1f]')
_WHITESPACE = re.compile(r"\s+")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_stem(name: str, fallback: str) -> str:
    """
    把 custom_name 清成安全的檔名主體。

    這個字串同時會變成磁碟上的檔名與下載時的檔名，所以路徑分隔符必須拿掉。
    中文保留（Starlette 的 FileResponse 會用 RFC 5987 編碼處理）。
    """
    cleaned = _UNSAFE_NAME_CHARS.sub("", name or "")
    cleaned = _WHITESPACE.sub("_", cleaned.strip())
    cleaned = cleaned.strip("._")
    return cleaned[:80] if cleaned else fallback


def _assert_within(base: Path, target: Path) -> bool:
    """以 commonpath 判斷 target 是否確實位於 base 之內。"""
    try:
        base_real = os.path.realpath(base)
        target_real = os.path.realpath(target)
        return os.path.commonpath([base_real, target_real]) == base_real
    except ValueError:
        # 不同磁碟機代號時 commonpath 會拋 ValueError
        return False


def _job_public(job: Dict[str, Any]) -> Dict[str, Any]:
    """
    job 的對外形狀。

    **逐欄列舉，任何欄位都要顯式給值。** 路由使用 response_model_exclude_unset=True，
    而路由回的是普通 dict —— 「未設定」等於「不在 dict 裡」，缺的 key 會直接從 JSON
    消失並在前端變成 undefined。絕不使用 {**base, **conditional} 這種寫法。
    """
    stage = job.get("stage") or "queued"
    label, progress = STAGES.get(stage, ("處理中", 0))
    started = job.get("started_at")
    finished = job.get("finished_at")
    elapsed = job.get("elapsed_seconds")
    if elapsed is None and started and not finished:
        try:
            elapsed = round(time.monotonic() - job["_started_monotonic"], 1)
        except (KeyError, TypeError):
            elapsed = None

    return {
        "job_id": job.get("job_id"),
        "session_id": job.get("session_id"),
        "session_name": job.get("session_name"),
        "format": job.get("format"),
        "state": job.get("state"),
        "stage": stage,
        "stage_label": label,
        "progress": 100 if job.get("state") == "done" else progress,
        "message": job.get("message"),
        "created_at": job.get("created_at"),
        "started_at": started,
        "finished_at": finished,
        "elapsed_seconds": elapsed,
        "artifact_name": job.get("artifact_name"),
        "artifact_size_mb": job.get("artifact_size_mb"),
        "imgsz": job.get("imgsz"),
        "download_url": (
            f"/api/export/{job['job_id']}/download" if job.get("state") == "done" else None
        ),
        "log_tail": list(job.get("log_tail") or []),
    }


def get_jobs_snapshot(session_id: Optional[str] = None, active_only: bool = False) -> Dict[str, Any]:
    with EXPORT_JOBS_LOCK:
        jobs = list(EXPORT_JOBS.values())
    out = {}
    for job in jobs:
        if session_id and job.get("session_id") != session_id:
            continue
        if active_only and job.get("state") not in ("queued", "running"):
            continue
        out[job["job_id"]] = _job_public(job)
    return out


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    with EXPORT_JOBS_LOCK:
        job = EXPORT_JOBS.get(job_id)
        return _job_public(job) if job else None


# --------------------------------------------------------------------------- #
# 匯出本體
# --------------------------------------------------------------------------- #

# ultralytics 用 colorstr() 在訊息裡嵌 ANSI 色碼（例如 "\x1b[34m\x1b[1mONNX:\x1b[0m"）。
# 終端機看得懂，但這些字串會原樣送到前端變成亂碼，所以收進緩衝前先剝掉。
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


class _LogTailHandler(logging.Handler):
    """把 ultralytics 的 log 收進 job 的環形緩衝，作為 exporting 階段唯一的真實回饋。"""

    def __init__(self, sink: deque):
        super().__init__(level=logging.INFO)
        self.sink = sink

    def emit(self, record):
        try:
            msg = _ANSI_RE.sub("", record.getMessage()).strip()
            if msg:
                self.sink.append(msg[:200])
        except Exception:
            pass


def _run_export(job_dir: Path, src_pt: Path, fmt: str) -> Tuple[Path, Dict[str, Any]]:
    """
    實際執行匯出，回傳 (產物路徑, 中繼資料)。

    中繼資料目前只帶 imgsz —— 使用者拿 .onnx 去部署時必須知道輸入解析度，而那個值
    只存在於 checkpoint 的訓練參數裡。趁模型還活著時讀出來，比事後去解析產物便宜。

    這是測試的接縫：所有單元測試都 monkeypatch 這個函式，因為真實匯出需要真實的
    YOLO checkpoint（而 .gitignore 排除 *.pt）。
    """
    from ultralytics import YOLO  # 延後 import，讓沒有匯出需求的路徑不用付這個成本

    model = YOLO(str(src_pt))
    try:
        # device="cpu"：kwargs 優先於 export() 的方法預設。匯出是一次性工作，
        # CPU 已足夠，且不與使用者的即時推論爭 VRAM，也避免 exporter 因為
        # device 是 cuda 而去要求 onnxruntime-gpu。
        # 不傳 imgsz：export() 會從 model.args["imgsz"] 注入訓練時的解析度，那才是對的預設。
        result = model.export(format=fmt, device="cpu", verbose=False)
        meta: Dict[str, Any] = {}
        try:
            meta["imgsz"] = model.model.args.get("imgsz")
        except (AttributeError, TypeError):
            meta["imgsz"] = None
        return Path(str(result)), meta
    finally:
        del model
        gc.collect()


def _friendly_error(exc: BaseException) -> str:
    if isinstance(exc, (ModuleNotFoundError, ImportError)):
        missing = getattr(exc, "name", None) or str(exc)
        return (
            f"缺少匯出所需的套件：{missing}。"
            "系統已停用自動安裝，請確認該套件已列入 requirements 並重建環境。"
        )
    if isinstance(exc, AssertionError):
        # ultralytics 的斷言訊息本身就寫得可讀，直接沿用
        return str(exc) or "匯出前置條件檢查失敗"
    if isinstance(exc, MemoryError):
        return "記憶體不足，無法完成匯出。請關閉其他模型或改用較小的權重。"
    return f"匯出失敗: {exc}"


def _write_manifest(job: Dict[str, Any], job_dir: Path) -> None:
    payload = _job_public(job)
    payload["schema_version"] = JOB_SCHEMA_VERSION
    payload["artifact_path"] = job.get("artifact_path")
    try:
        with open(job_dir / "manifest.json", "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
    except Exception as exc:
        print(f"[ExportService] Error writing manifest for {job.get('job_id')}: {exc}")


def _process_job(job_id: str) -> None:
    with EXPORT_JOBS_LOCK:
        job = EXPORT_JOBS.get(job_id)
        if job is None:
            return
        job["state"] = "running"
        job["stage"] = "staging"
        job["started_at"] = _now_iso()
        job["_started_monotonic"] = time.monotonic()
        src_weights = job["source_weights"]
        fmt = job["format"]
        job_dir = Path(job["job_dir"])
        stem = job["safe_stem"]

    log_tail = job["log_tail"]
    handler = _LogTailHandler(log_tail)
    ul_logger = logging.getLogger("ultralytics")
    ul_logger.addHandler(handler)

    try:
        job_dir.mkdir(parents=True, exist_ok=True)
        staged = job_dir / f"{stem}.pt"
        # 複製到專屬目錄再匯出：exporter 會把產物寫在來源檔旁邊，複製正是用來
        # 改寫那個落點，避免污染使用者的 run 目錄。
        shutil.copy2(src_weights, staged)

        with EXPORT_JOBS_LOCK:
            job["stage"] = "loading"

        with EXPORT_JOBS_LOCK:
            job["stage"] = "exporting"

        artifact, export_meta = _run_export(job_dir, staged, fmt)

        with EXPORT_JOBS_LOCK:
            job["stage"] = "finalizing"

        if not artifact.exists():
            raise FileNotFoundError(f"匯出程序未產生預期的檔案: {artifact}")

        # 統一命名為 <safe_stem><suffix>，避免三個 session 都下載出 best.onnx
        final_name = f"{stem}{format_suffix(fmt)}"
        final_path = job_dir / final_name
        if artifact.resolve() != final_path.resolve():
            if final_path.exists():
                final_path.unlink()
            shutil.move(str(artifact), str(final_path))

        try:
            staged.unlink(missing_ok=True)
        except OSError:
            pass

        size_mb = round(final_path.stat().st_size / 1024 / 1024, 2)
        with EXPORT_JOBS_LOCK:
            job["state"] = "done"
            job["stage"] = "done"
            job["message"] = None
            job["artifact_path"] = str(final_path)
            job["artifact_name"] = final_name
            job["artifact_size_mb"] = size_mb
            job["imgsz"] = (export_meta or {}).get("imgsz")
            job["finished_at"] = _now_iso()
            job["elapsed_seconds"] = round(time.monotonic() - job["_started_monotonic"], 1)
            _write_manifest(job, job_dir)

    except BaseException as exc:  # noqa: BLE001 - 任何失敗都要變成 job 狀態，不能讓 worker 死掉
        traceback.print_exc()
        with EXPORT_JOBS_LOCK:
            job["state"] = "failed"
            job["stage"] = "failed"
            job["message"] = _friendly_error(exc)
            job["finished_at"] = _now_iso()
            started = job.get("_started_monotonic")
            job["elapsed_seconds"] = round(time.monotonic() - started, 1) if started else None
        try:
            shutil.rmtree(job_dir, ignore_errors=True)
        except Exception:
            pass
    finally:
        ul_logger.removeHandler(handler)
        gc.collect()
        # session 在匯出期間被刪除時，worker 負責收尾（刪除當下不能動這筆紀錄，
        # 否則 worker 會對被抽走的 dict KeyError）
        with EXPORT_JOBS_LOCK:
            if job.get("purge_on_finish"):
                EXPORT_JOBS.pop(job_id, None)
                shutil.rmtree(job_dir, ignore_errors=True)
            done_event = job.get("_done_event")
        if done_event is not None:
            done_event.set()


def _worker_loop() -> None:
    while True:
        job_id = _QUEUE.get()
        try:
            _process_job(job_id)
        except Exception as exc:  # 保險：worker 絕不能因單一 job 而終止
            print(f"[ExportService] Worker error on {job_id}: {exc}")
            traceback.print_exc()
        finally:
            _QUEUE.task_done()


def _ensure_worker() -> None:
    global _WORKER
    with _WORKER_LOCK:
        if _WORKER is None or not _WORKER.is_alive():
            _WORKER = threading.Thread(target=_worker_loop, name="export-worker", daemon=True)
            _WORKER.start()


# --------------------------------------------------------------------------- #
# 提交與生命週期
# --------------------------------------------------------------------------- #

def submit_export(session: Dict[str, Any], fmt: str) -> Dict[str, Any]:
    """
    建立並排入一個匯出 job。呼叫端需先通過能力閘與 session 閘。

    回傳對外的 job dict；佇列滿時拋 queue.Full。
    """
    _sweep_expired()

    job_id = f"exp_{uuid.uuid4().hex[:8]}"
    session_name = session.get("custom_name") or session.get("session_id") or "model"
    stem = safe_stem(session_name, fallback=session.get("session_id") or job_id)

    job = {
        "job_id": job_id,
        "session_id": session.get("session_id"),
        "session_name": session_name,
        "format": fmt,
        "state": "queued",
        "stage": "queued",
        "message": None,
        "created_at": _now_iso(),
        "started_at": None,
        "finished_at": None,
        "elapsed_seconds": None,
        "artifact_path": None,
        "artifact_name": None,
        "artifact_size_mb": None,
        "imgsz": None,
        "source_weights": session.get("weights_path"),
        "job_dir": str(EXPORTS_DIR / job_id),
        "safe_stem": stem,
        "log_tail": deque(maxlen=LOG_TAIL_MAXLEN),
        "purge_on_finish": False,
        "_done_event": threading.Event(),
    }

    with EXPORT_JOBS_LOCK:
        EXPORT_JOBS[job_id] = job
        _evict_finished_locked()
        public = _job_public(job)

    try:
        _QUEUE.put_nowait(job_id)
    except queue.Full:
        with EXPORT_JOBS_LOCK:
            EXPORT_JOBS.pop(job_id, None)
        raise

    _ensure_worker()
    return public


def wait_for_job(job_id: str, timeout: float = 30.0) -> bool:
    """等待 job 結束（測試用，避免 sleep 造成 flaky）。"""
    with EXPORT_JOBS_LOCK:
        job = EXPORT_JOBS.get(job_id)
        event = job.get("_done_event") if job else None
    if event is None:
        return False
    return event.wait(timeout)


def _evict_finished_locked() -> None:
    """必須持有 EXPORT_JOBS_LOCK。淘汰最舊的已完成 job，永不淘汰執行中的。"""
    if len(EXPORT_JOBS) <= MAX_EXPORT_JOBS:
        return
    finished = [j for j in EXPORT_JOBS.values() if j.get("state") in ("done", "failed")]
    finished.sort(key=lambda j: j.get("created_at") or "")
    excess = len(EXPORT_JOBS) - MAX_EXPORT_JOBS
    for job in finished[:excess]:
        EXPORT_JOBS.pop(job["job_id"], None)
        shutil.rmtree(job["job_dir"], ignore_errors=True)


def _sweep_expired() -> None:
    """刪除超過 TTL 的已完成 job。啟動與每次提交時各掃一次，不另開背景執行緒。"""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=EXPORT_JOB_TTL_HOURS)
    with EXPORT_JOBS_LOCK:
        stale = []
        for job in EXPORT_JOBS.values():
            if job.get("state") not in ("done", "failed"):
                continue
            created = job.get("created_at")
            try:
                if created and datetime.fromisoformat(created) < cutoff:
                    stale.append(job)
            except ValueError:
                continue
        for job in stale:
            EXPORT_JOBS.pop(job["job_id"], None)
            shutil.rmtree(job["job_dir"], ignore_errors=True)


def delete_export_job(job_id: str) -> None:
    """刪除一筆匯出紀錄與其產物。執行中的 job 改為標記，由 worker 收尾。"""
    with EXPORT_JOBS_LOCK:
        job = EXPORT_JOBS.get(job_id)
        if job is None:
            raise KeyError(job_id)
        if job.get("state") in ("queued", "running"):
            job["purge_on_finish"] = True
            return
        EXPORT_JOBS.pop(job_id, None)
        job_dir = job["job_dir"]
    shutil.rmtree(job_dir, ignore_errors=True)


def purge_exports_for_session(session_id: str) -> int:
    """
    session 被刪除時清掉它的所有匯出。

    由 router 呼叫而非 session_manager：後者已 import model_service，再互相 import
    會形成循環，而且在 SESSIONS_LOCK 內取得 EXPORT_JOBS_LOCK 會製造鎖序風險。
    """
    removed = 0
    to_remove: List[str] = []
    with EXPORT_JOBS_LOCK:
        for job_id, job in list(EXPORT_JOBS.items()):
            if job.get("session_id") != session_id:
                continue
            if job.get("state") in ("queued", "running"):
                job["purge_on_finish"] = True
                continue
            to_remove.append(job["job_dir"])
            EXPORT_JOBS.pop(job_id, None)
            removed += 1
    for job_dir in to_remove:
        shutil.rmtree(job_dir, ignore_errors=True)
    return removed


def resolve_artifact(job_id: str) -> Optional[Path]:
    """
    取得可供下載的產物路徑。

    只接受 state=="done" 的 job，且路徑必須確實落在 EXPORTS_DIR 之內——即使路徑是
    伺服器自己產生的也要驗，避免任何一條路徑注入的可能。
    """
    with EXPORT_JOBS_LOCK:
        job = EXPORT_JOBS.get(job_id)
        if job is None or job.get("state") != "done":
            return None
        artifact_path = job.get("artifact_path")
    if not artifact_path:
        return None
    path = Path(artifact_path)
    if not _assert_within(EXPORTS_DIR, path) or not path.exists():
        return None
    return path


def load_export_jobs_from_disk(known_session_ids: Optional[set] = None) -> None:
    """
    啟動時重建已完成的匯出紀錄。

    執行中的 job 無法續跑（執行緒已消失），所以只留 done 且產物仍在、且所屬 session
    仍存在的紀錄，其餘目錄直接清除。這是 session_manager ghost filter 的對應物。
    """
    _sweep_expired()
    if not EXPORTS_DIR.exists():
        return

    restored = 0
    for job_dir in sorted(EXPORTS_DIR.iterdir()):
        if not job_dir.is_dir():
            continue
        manifest = job_dir / "manifest.json"
        if not manifest.exists():
            shutil.rmtree(job_dir, ignore_errors=True)
            continue
        try:
            with open(manifest, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception:
            shutil.rmtree(job_dir, ignore_errors=True)
            continue

        artifact_path = data.get("artifact_path")
        ok = (
            data.get("schema_version") == JOB_SCHEMA_VERSION
            and data.get("state") == "done"
            and artifact_path
            and Path(artifact_path).exists()
            and (known_session_ids is None or data.get("session_id") in known_session_ids)
        )
        if not ok:
            shutil.rmtree(job_dir, ignore_errors=True)
            continue

        job = dict(data)
        job["job_dir"] = str(job_dir)
        job["log_tail"] = deque(data.get("log_tail") or [], maxlen=LOG_TAIL_MAXLEN)
        job["purge_on_finish"] = False
        job["_done_event"] = threading.Event()
        job["_done_event"].set()
        job.setdefault("safe_stem", Path(artifact_path).stem)
        job.setdefault("source_weights", None)
        with EXPORT_JOBS_LOCK:
            EXPORT_JOBS[job["job_id"]] = job
        restored += 1

    print(f"[ExportService] Restored {restored} export artifact(s)")
