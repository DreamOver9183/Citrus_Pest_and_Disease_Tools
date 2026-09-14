"""
逐張檢視（看圖驗收）的 job 機制：讓模型逐張跑過一個 split，存下每張的標註框與預測框，
之後在畫面上疊圖比對漏抓、誤報與類別錯。

**這是視覺化，不是評估指標。** 指標一律走 evaluation_service 的 `model.val()`；本模組的
逐張計數只用來篩選與排序影像，介面必須標明「非評估指標」。配對規則見 review_boxes。

**硬規則：本模組不得 import model_service**（理由見 evaluation_service 模組註解）。
自建用完即丟的 YOLO 實例。

**不寫權重登錄簿。** 登錄簿記的是「測過什麼、當時多少分」，逐張檢視不產生分數；而且它
只使用既有 session，那些權重在上傳或 LocalLibrary 登記時就已入帳。

**低門檻存檔。** 推論時以 STORE_CONF 存下全部預測，之後在畫面上調門檻只做過濾，不重跑推論。

**影像方向。** 以 PIL 解碼並依 EXIF 轉正後才餵給模型：寬高、推論、瀏覽器顯示（`<img>`
預設依 EXIF 轉正）三者因此是同一個方向，與 ultralytics 訓練時以 exif_size 驗證標註的假設
一致。PIL 也順帶避開 cv2.imread 遇到中文路徑回傳 None 而不報錯的地雷。

**影像保存。** 資料夾來源就地引用（LocalLibrary 絕不寫入）；ZIP 來源保留解壓出的影像供
檢視、刪掉已讀進 JSON 的標註。縮圖一律寫進 job 目錄。

併發模型與 evaluation_service 一致：單一 daemon 執行緒 + 有界 queue.Queue。與評估不同的
是推論逐張進行，所以**刪除執行中的 job 會在下一張之前中止**。
"""
import base64
import gc
import hashlib
import io
import json
import os
import queue
import shutil
import threading
import time
import traceback
import uuid
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from jinja2 import Environment, FileSystemLoader
from PIL import Image, ImageOps

from app.core.config import (
    MAX_EVAL_IMAGES,
    MAX_QUEUED_REVIEWS,
    MAX_REVIEW_JOBS,
    REVIEW_DIR,
    REVIEW_JOB_TTL_HOURS,
)
from app.core.imgsz import model_default_imgsz, normalize_imgsz
from app.services import export_capabilities, registry_service, report_service
from app.services.dataset_resolver import DatasetUnavailable, ResolvedSplit, resolve_split
from app.services.evaluation_service import compare_vocabularies
from app.services.review_boxes import IOU_THRESHOLD, annotate, parse_yolo_labels
from app.utils.dataset_zip import IMAGE_EXTENSIONS

JOB_SCHEMA_VERSION = 1

# 推論時存檔的信心下限。畫面上的門檻只能在這之上調整——低於它的框根本沒存。
STORE_CONF = 0.05
THUMB_MAX_SIDE = 480
THUMB_QUALITY = 80
ITEMS_FILE = "items.json"

STATUS_FILTERS = ("all", "errors", "clean", "fn", "fp", "wrong")
SORT_KEYS = ("errors", "name")

REVIEW_JOBS: Dict[str, Dict[str, Any]] = {}
# 鎖序規則同 evaluation_service：絕不在持有 REVIEW_JOBS_LOCK 時取得 SESSIONS_LOCK / DATASETS_LOCK。
REVIEW_JOBS_LOCK = threading.RLock()

_QUEUE: "queue.Queue[str]" = queue.Queue(maxsize=MAX_QUEUED_REVIEWS)
_WORKER: Optional[threading.Thread] = None
_WORKER_LOCK = threading.Lock()

# items.json 的查詢快取。拖一次門檻滑桿就是一次查詢，沒有理由每次重讀整份 JSON。
_ITEMS_CACHE: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
_ITEMS_CACHE_SIZE = 4
_ITEMS_LOCK = threading.Lock()

STAGES = {
    "queued": "等待中",
    "resolving": "準備資料集",
    "loading": "載入模型與比對類別",
    "predicting": "逐張推論中",
    "done": "完成",
    "failed": "失敗",
}


class ReviewFailed(Exception):
    """訊息直接顯示給使用者的失敗。"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# 能力閘
# --------------------------------------------------------------------------- #

def session_review_gate(session: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """
    這個 session 能不能做逐張檢視。

    架構依 model_arch 判斷（上傳的 .pth 會被改名成 .pt，副檔名不代表是 YOLO）；
    格式再看副檔名：.pt 一律可用，.tflite 要看這台機器有沒有 LiteRT runtime。
    """
    arch = (session.get("model_arch") or "yolo").lower()
    if arch != "yolo":
        return False, "逐張檢視目前只支援 YOLO 架構（SSDLite 的推論流程不同）。"
    suffix = Path(session.get("weights_path") or "").suffix.lower()
    if suffix == ".pt":
        return True, None
    if suffix == ".tflite":
        return export_capabilities.tflite_inference_available()
    label = suffix.lstrip(".").upper() or "未知"
    return False, f"逐張檢視支援 .pt 與 .tflite 權重，此模型為 {label} 格式。"


# --------------------------------------------------------------------------- #
# 測試接縫（真實模型與影像被 .gitignore 排除，測試一律 monkeypatch 這兩個）
# --------------------------------------------------------------------------- #

def _load_model(weights: str):
    from ultralytics import YOLO

    return YOLO(weights)


def _predict_image(model, image: Image.Image, imgsz: Optional[int]) -> List[Dict[str, Any]]:
    """
    單張推論，回傳像素座標的框。

    直接餵 PIL 影像：ultralytics 會自行轉成 BGR，而影像已在 _load_image 轉正、不帶 EXIF，
    不會被再轉一次。
    """
    kwargs: Dict[str, Any] = {"conf": STORE_CONF, "verbose": False}
    if imgsz:
        kwargs["imgsz"] = imgsz
    result = model.predict(image, **kwargs)[0]
    boxes = getattr(result, "boxes", None)
    if boxes is None or len(boxes) == 0:
        return []
    return [
        {"cls": int(cls), "conf": round(float(conf), 4), "box": [round(float(v), 2) for v in xyxy]}
        for xyxy, conf, cls in zip(boxes.xyxy.tolist(), boxes.conf.tolist(), boxes.cls.tolist())
    ]


def _fixed_input_size(weights: str) -> Optional[int]:
    """TFLite 的輸入尺寸在匯出時就固定了，從檔內嵌的 metadata 讀出。非 TFLite 回 None。"""
    if not str(weights).lower().endswith(".tflite"):
        return None
    try:
        from ultralytics.nn.backends.base import read_tflite_metadata

        metadata = read_tflite_metadata(weights) or {}
    except Exception:  # noqa: BLE001 — metadata 讀不到時退回使用者指定的尺寸
        return None
    return normalize_imgsz(metadata.get("imgsz"))


# --------------------------------------------------------------------------- #
# 影像與標註
# --------------------------------------------------------------------------- #

def _list_images(images_dir: str) -> List[str]:
    """依檔名排序，讓不同 job（例如 320 與 640）的同一張影像能按檔名對齊。"""
    return sorted(
        name for name in os.listdir(images_dir)
        if os.path.splitext(name)[1].lower() in IMAGE_EXTENSIONS
        and os.path.isfile(os.path.join(images_dir, name))
    )


def _image_set_key(names: List[str]) -> str:
    return hashlib.sha1("\n".join(names).encode("utf-8")).hexdigest()[:16]


def _load_image(path: str) -> Image.Image:
    with Image.open(path) as im:
        return ImageOps.exif_transpose(im).convert("RGB")


def _read_labels(path: str, width: int, height: int, nc: int):
    """缺 label 檔回傳 (空清單, None)——與空檔一樣是負樣本，但另外計數。"""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except FileNotFoundError:
        return [], None
    return parse_yolo_labels(text, width, height, nc)


def _write_thumbnail(image: Image.Image, dest: Path) -> None:
    thumb = image.copy()
    thumb.thumbnail((THUMB_MAX_SIDE, THUMB_MAX_SIDE))
    thumb.save(dest, "JPEG", quality=THUMB_QUALITY)


# --------------------------------------------------------------------------- #
# job 對外形狀
# --------------------------------------------------------------------------- #

def _job_public(job: Dict[str, Any]) -> Dict[str, Any]:
    """逐欄列舉，任何欄位都要顯式給值。"""
    stage = job.get("stage") or "queued"
    state = job.get("state")
    total = job.get("image_count") or 0
    processed = job.get("processed") or 0
    if state == "done":
        progress = 100
    elif stage == "predicting" and total:
        progress = min(99, int(processed * 100 / total))
    else:
        progress = 0

    elapsed = job.get("elapsed_seconds")
    if elapsed is None and job.get("started_at") and not job.get("finished_at"):
        try:
            elapsed = round(time.monotonic() - job["_started_monotonic"], 1)
        except (KeyError, TypeError):
            elapsed = None

    return {
        "job_id": job.get("job_id"),
        "session_id": job.get("session_id"),
        "session_name": job.get("session_name"),
        "weight_format": job.get("weight_format"),
        "weight_sha256": job.get("weight_sha256"),
        "dataset_id": job.get("dataset_id"),
        "dataset_name": job.get("dataset_name"),
        "split": job.get("split"),
        "image_set_key": job.get("image_set_key"),
        "imgsz_requested": job.get("imgsz_requested"),
        "imgsz_used": job.get("imgsz_used"),
        "state": state,
        "stage": stage,
        "stage_label": STAGES.get(stage, "處理中"),
        "progress": progress,
        "processed": processed,
        "image_count": job.get("image_count"),
        "message": job.get("message"),
        "created_at": job.get("created_at"),
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
        "elapsed_seconds": elapsed,
        "vocab_check": job.get("vocab_check"),
        "class_names": list(job.get("class_names") or []),
        "label_issues": dict(job.get("label_issues") or {}),
        "unreadable": list(job.get("unreadable") or []),
        "store_conf": STORE_CONF,
        "iou_threshold": IOU_THRESHOLD,
    }


def get_jobs_snapshot() -> Dict[str, Any]:
    with REVIEW_JOBS_LOCK:
        jobs = [_job_public(j) for j in REVIEW_JOBS.values()]
    jobs.sort(key=lambda j: j.get("created_at") or "", reverse=True)
    return {"jobs": jobs}


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    with REVIEW_JOBS_LOCK:
        job = REVIEW_JOBS.get(job_id)
        return _job_public(job) if job else None


def job_state(job_id: str) -> Optional[str]:
    with REVIEW_JOBS_LOCK:
        job = REVIEW_JOBS.get(job_id)
        return job.get("state") if job else None


# --------------------------------------------------------------------------- #
# 執行流程
# --------------------------------------------------------------------------- #

def _update(job_id: str, **fields) -> None:
    with REVIEW_JOBS_LOCK:
        job = REVIEW_JOBS.get(job_id)
        if job is not None:
            job.update(fields)


def _alive(job_id: str) -> bool:
    with REVIEW_JOBS_LOCK:
        return job_id in REVIEW_JOBS


def _fail(job_id: str, message: str) -> None:
    with REVIEW_JOBS_LOCK:
        job = REVIEW_JOBS.get(job_id)
        if job is None:
            return
        job.update(state="failed", stage="failed", message=message, finished_at=_now_iso())
        started = job.get("_started_monotonic")
        if started:
            job["elapsed_seconds"] = round(time.monotonic() - started, 1)


def _process_job(job_id: str) -> None:
    with REVIEW_JOBS_LOCK:
        job = REVIEW_JOBS.get(job_id)
        if job is None:
            return
        job.update(state="running", started_at=_now_iso(), _started_monotonic=time.monotonic())
        stats = job["_dataset_stats"]
        weights = job["source_weights"]
        split = job["split"]
        requested = job["imgsz_requested"]
        job_dir = Path(job["job_dir"])

    # 權重雜湊在背景算（同 evaluation_service）：只為了讓匯出的 HTML 能追溯是哪一顆權重
    _update(job_id, weight_sha256=registry_service.sha256_of_file(weights) if weights else None)

    resolved: Optional[ResolvedSplit] = None
    model = None
    finished = False
    try:
        # --- 1. 資料集 ---
        _update(job_id, stage="resolving")
        job_dir.mkdir(parents=True, exist_ok=True)
        resolved = resolve_split(stats, split, str(job_dir / "data"))
        names = _list_images(resolved.images_dir)
        if not names:
            raise ReviewFailed(f"「{split}」split 內沒有任何影像。")
        # dataset_resolver 只對 ZIP 來源套上限；資料夾來源在這裡補上
        if len(names) > MAX_EVAL_IMAGES:
            raise ReviewFailed(
                f"「{split}」split 有 {len(names):,} 張影像，超過單次上限 {MAX_EVAL_IMAGES:,} 張。"
            )
        _update(job_id, image_count=len(names), image_set_key=_image_set_key(names))

        # --- 2. 模型與類別詞彙（必須在逐張推論之前） ---
        _update(job_id, stage="loading")
        model = _load_model(weights)
        dataset_names = list(stats.get("declared_names") or [])
        vocab = compare_vocabularies(dict(model.names or {}), dataset_names)
        _update(job_id, vocab_check=vocab)
        if vocab["status"] == "mismatch":
            raise ReviewFailed(vocab["message"])
        class_names = list(vocab["model_names"] or dataset_names)

        fixed = _fixed_input_size(weights)
        if fixed is not None and requested is not None and requested != fixed:
            raise ReviewFailed(
                f"TFLite 的輸入尺寸在匯出時已固定為 {fixed}，無法改用 {requested} 推論。"
            )
        imgsz_used = fixed or requested or model_default_imgsz(model)
        _update(job_id, class_names=class_names, imgsz_used=imgsz_used)

        # --- 3. 逐張推論 ---
        _update(job_id, stage="predicting")
        thumbs_dir = job_dir / "thumbs"
        thumbs_dir.mkdir(exist_ok=True)
        images: List[Dict[str, Any]] = []
        unreadable: List[str] = []
        issues = {"polygon": 0, "malformed": 0, "class_out_of_range": 0, "missing": 0}

        for position, name in enumerate(names):
            if not _alive(job_id):
                return
            try:
                image = _load_image(os.path.join(resolved.images_dir, name))
            except Exception:  # noqa: BLE001
                # 刻意寬鬆：ultralytics 會 patch 全域的 PIL.Image.open，解碼失敗時改去 import
                # pi_heif，沒裝就拋 ModuleNotFoundError 而不是 OSError。一張壞圖只該被略過並
                # 列出，不該讓整批 401 張的檢視失敗。
                unreadable.append(name)
            else:
                index = len(images)
                width, height = image.size
                preds = _predict_image(model, image, imgsz_used)
                label_path = os.path.join(resolved.labels_dir, Path(name).stem + ".txt")
                gt, skipped = _read_labels(label_path, width, height, len(class_names))
                if skipped is None:
                    issues["missing"] += 1
                else:
                    for key, count in skipped.items():
                        issues[key] += count
                _write_thumbnail(image, thumbs_dir / f"{index}.jpg")
                images.append({
                    "index": index, "name": name, "width": width, "height": height,
                    "gt": gt, "preds": preds, "label_missing": skipped is None,
                })
            _update(job_id, processed=position + 1)

        with open(job_dir / ITEMS_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "schema_version": JOB_SCHEMA_VERSION,
                "class_names": class_names,
                "imgsz_used": imgsz_used,
                "store_conf": STORE_CONF,
                "images": images,
            }, f, ensure_ascii=False)

        if resolved.extracted:
            # 標註已讀進 items.json；影像留著供檢視
            shutil.rmtree(resolved.labels_dir, ignore_errors=True)

        with REVIEW_JOBS_LOCK:
            job = REVIEW_JOBS.get(job_id)
            if job is None:
                return
            job.update(
                state="done", stage="done", message=vocab.get("message"),
                finished_at=_now_iso(),
                elapsed_seconds=round(time.monotonic() - job["_started_monotonic"], 1),
                label_issues=issues, unreadable=unreadable, images_dir=resolved.images_dir,
            )
        _write_manifest(job_id)
        finished = True

    except (DatasetUnavailable, ReviewFailed) as exc:
        _fail(job_id, str(exc))
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        _fail(job_id, f"逐張檢視失敗：{exc}")
    finally:
        if model is not None:
            del model
        gc.collect()
        if not finished or not _alive(job_id):
            # 失敗、或執行中被刪除：不會再被檢視，影像、縮圖與解壓內容都不留
            shutil.rmtree(job_dir, ignore_errors=True)


def _write_manifest(job_id: str) -> None:
    with REVIEW_JOBS_LOCK:
        job = REVIEW_JOBS.get(job_id)
        if job is None or job.get("state") != "done":
            return
        payload = _job_public(job)
        payload["schema_version"] = JOB_SCHEMA_VERSION
        payload["images_dir"] = job.get("images_dir")
        job_dir = Path(job["job_dir"])
    try:
        with open(job_dir / "manifest.json", "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except OSError as exc:
        print(f"[ReviewService] Could not write manifest for {job_id}: {exc}")


def _worker_loop() -> None:
    while True:
        job_id = _QUEUE.get()
        try:
            _process_job(job_id)
        except Exception as exc:  # 保險：worker 絕不能因單一 job 而終止
            print(f"[ReviewService] Worker error on {job_id}: {exc}")
            traceback.print_exc()
        finally:
            _QUEUE.task_done()


def _ensure_worker() -> None:
    global _WORKER
    with _WORKER_LOCK:
        if _WORKER is None or not _WORKER.is_alive():
            _WORKER = threading.Thread(target=_worker_loop, name="review-worker", daemon=True)
            _WORKER.start()


# --------------------------------------------------------------------------- #
# 提交與生命週期
# --------------------------------------------------------------------------- #

def _drop_cache(job_id: str) -> None:
    with _ITEMS_LOCK:
        _ITEMS_CACHE.pop(job_id, None)


def _evict_finished_locked() -> None:
    """呼叫端必須已持有 REVIEW_JOBS_LOCK。永不淘汰執行中的 job。"""
    finished = [(jid, j) for jid, j in REVIEW_JOBS.items() if j.get("state") in ("done", "failed")]
    finished.sort(key=lambda kv: kv[1].get("created_at") or "")
    while len(REVIEW_JOBS) > MAX_REVIEW_JOBS and finished:
        jid, job = finished.pop(0)
        REVIEW_JOBS.pop(jid, None)
        _drop_cache(jid)
        shutil.rmtree(Path(job["job_dir"]), ignore_errors=True)


def sweep_expired() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=REVIEW_JOB_TTL_HOURS)
    with REVIEW_JOBS_LOCK:
        for jid in list(REVIEW_JOBS):
            job = REVIEW_JOBS[jid]
            if job.get("state") not in ("done", "failed"):
                continue
            try:
                created = job.get("created_at")
                if created and datetime.fromisoformat(created) < cutoff:
                    REVIEW_JOBS.pop(jid, None)
                    _drop_cache(jid)
                    shutil.rmtree(Path(job["job_dir"]), ignore_errors=True)
            except ValueError:
                continue


def submit_review(
    session: Dict[str, Any], dataset: Dict[str, Any], split: str, imgsz: Optional[int]
) -> Dict[str, Any]:
    """建立並排入一個逐張檢視 job。佇列滿時拋 queue.Full。呼叫端需先通過 session_review_gate。"""
    sweep_expired()

    weights = session.get("weights_path") or ""
    job_id = f"rev_{uuid.uuid4().hex[:8]}"
    job = {
        "job_id": job_id,
        "session_id": session.get("session_id"),
        "session_name": session.get("custom_name") or session.get("session_id") or "model",
        "weight_format": Path(weights).suffix.lstrip(".").lower() or None,
        "weight_sha256": None,
        "dataset_id": dataset.get("dataset_id"),
        "dataset_name": dataset.get("zip_name") or dataset.get("dataset_id"),
        "split": split,
        "image_set_key": None,
        "imgsz_requested": imgsz,
        "imgsz_used": None,
        "state": "queued",
        "stage": "queued",
        "processed": 0,
        "image_count": None,
        "message": None,
        "created_at": _now_iso(),
        "started_at": None,
        "finished_at": None,
        "elapsed_seconds": None,
        "vocab_check": None,
        "class_names": [],
        "label_issues": {},
        "unreadable": [],
        "images_dir": None,
        "source_weights": weights,
        "job_dir": str(REVIEW_DIR / job_id),
        "_dataset_stats": dataset,
    }

    with REVIEW_JOBS_LOCK:
        REVIEW_JOBS[job_id] = job
        _evict_finished_locked()

    try:
        _QUEUE.put_nowait(job_id)
    except queue.Full:
        with REVIEW_JOBS_LOCK:
            REVIEW_JOBS.pop(job_id, None)
        raise

    _ensure_worker()
    return _job_public(job)


def delete_job(job_id: str) -> bool:
    """刪除 job。執行中的 job 會在下一張影像之前停下，worker 收尾時再清一次目錄。"""
    with REVIEW_JOBS_LOCK:
        job = REVIEW_JOBS.pop(job_id, None)
    if job is None:
        return False
    _drop_cache(job_id)
    shutil.rmtree(Path(job["job_dir"]), ignore_errors=True)
    return True


def load_jobs_from_disk() -> None:
    """
    啟動時還原已完成的逐張檢視。

    比照 evaluation_service 不過濾「來源 session 已消失」：結果已完整存在 items.json，
    不需要模型還在記憶體裡；而多數 session 來自不落地的 LocalLibrary，過濾等於每次重啟刪光。
    """
    if not REVIEW_DIR.exists():
        return
    for entry in sorted(REVIEW_DIR.iterdir()):
        manifest = entry / "manifest.json"
        if not entry.is_dir() or not manifest.exists() or not (entry / ITEMS_FILE).exists():
            shutil.rmtree(entry, ignore_errors=True)
            continue
        try:
            with open(manifest, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError):
            shutil.rmtree(entry, ignore_errors=True)
            continue
        if payload.get("schema_version") != JOB_SCHEMA_VERSION or payload.get("state") != "done":
            shutil.rmtree(entry, ignore_errors=True)
            continue

        job_id = payload.get("job_id") or entry.name
        payload["job_dir"] = str(entry)
        payload["_dataset_stats"] = {}
        with REVIEW_JOBS_LOCK:
            REVIEW_JOBS[job_id] = payload

    print(f"[ReviewService] Restored {len(REVIEW_JOBS)} review job(s)")


# --------------------------------------------------------------------------- #
# 查詢
# --------------------------------------------------------------------------- #

def _load_items(job_id: str) -> Optional[Dict[str, Any]]:
    with REVIEW_JOBS_LOCK:
        job = REVIEW_JOBS.get(job_id)
        if job is None or job.get("state") != "done":
            return None
        path = Path(job["job_dir"]) / ITEMS_FILE
    with _ITEMS_LOCK:
        cached = _ITEMS_CACHE.get(job_id)
        if cached is not None:
            _ITEMS_CACHE.move_to_end(job_id)
            return cached
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    with _ITEMS_LOCK:
        _ITEMS_CACHE[job_id] = payload
        while len(_ITEMS_CACHE) > _ITEMS_CACHE_SIZE:
            _ITEMS_CACHE.popitem(last=False)
    return payload


def _item_view(job_id: str, image: Dict[str, Any], ann: Dict[str, Any]) -> Dict[str, Any]:
    index = image["index"]
    return {
        "index": index,
        "name": image["name"],
        "width": image["width"],
        "height": image["height"],
        "thumb_url": f"/api/reviews/{job_id}/image/{index}?variant=thumb",
        "image_url": f"/api/reviews/{job_id}/image/{index}",
        "gt": ann["gt"],
        "preds": ann["preds"],
        "counts": ann["counts"],
        "errors": ann["errors"],
        "label_missing": bool(image.get("label_missing")),
    }


def _status_matches(status: str, ann: Dict[str, Any]) -> bool:
    counts = ann["counts"]
    return {
        "all": True,
        "errors": ann["errors"] > 0,
        "clean": ann["errors"] == 0,
        "fn": counts["fn"] > 0,
        "fp": counts["fp"] > 0,
        "wrong": counts["wrong"] > 0,
    }[status]


def query_items(
    job_id: str,
    conf: float,
    classes: Optional[List[int]] = None,
    status: str = "all",
    sort: str = "errors",
    offset: int = 0,
    limit: int = 24,
) -> Optional[Dict[str, Any]]:
    """
    以目前的門檻重新配對、依類別與狀態篩選、排序、分頁。

    `summary` 以**類別篩選後、狀態篩選前**的影像計算，讓畫面上的狀態選項能同時顯示各自的張數。
    """
    items = _load_items(job_id)
    if items is None:
        return None

    involved = []
    for image in items["images"]:
        ann = annotate(image["gt"], image["preds"], conf, classes)
        if ann["involved"]:
            involved.append((image, ann))

    summary = {
        "images": len(involved),
        "clean": sum(1 for _, a in involved if a["errors"] == 0),
        "with_fn": sum(1 for _, a in involved if a["counts"]["fn"]),
        "with_fp": sum(1 for _, a in involved if a["counts"]["fp"]),
        "with_wrong": sum(1 for _, a in involved if a["counts"]["wrong"]),
        **{key: sum(a["counts"][key] for _, a in involved) for key in ("tp", "fp", "fn", "wrong")},
    }

    selected = [(image, ann) for image, ann in involved if _status_matches(status, ann)]
    if sort == "errors":
        selected.sort(key=lambda pair: (-pair[1]["errors"], pair[0]["name"]))
    else:
        selected.sort(key=lambda pair: pair[0]["name"])

    page = selected[offset:offset + limit]
    return {
        "items": [_item_view(job_id, image, ann) for image, ann in page],
        "total": len(selected),
        "offset": offset,
        "limit": limit,
        "conf": conf,
        "summary": summary,
        "class_names": list(items.get("class_names") or []),
    }


def get_item(job_id: str, name: str, conf: float) -> Optional[Dict[str, Any]]:
    """以檔名取單張（燈箱與跨 job 並排用）。只查 JSON 清單，不碰檔案系統。"""
    items = _load_items(job_id)
    if items is None:
        return None
    for image in items["images"]:
        if image["name"] == name:
            return _item_view(job_id, image, annotate(image["gt"], image["preds"], conf))
    return None


def image_path(job_id: str, index: int, variant: str = "full") -> Optional[str]:
    """
    回傳影像的實體路徑。

    以**索引**查 items 清單取得檔名，而不是接受使用者傳入的檔名，再確認路徑落在預期目錄內——
    資料夾來源的影像在 LocalLibrary 裡，擋路徑穿越不能只靠字串檢查。
    """
    with REVIEW_JOBS_LOCK:
        job = REVIEW_JOBS.get(job_id)
        if job is None or job.get("state") != "done":
            return None
        job_dir = job["job_dir"]
        images_dir = job.get("images_dir")
    items = _load_items(job_id)
    if items is None or not (0 <= index < len(items["images"])):
        return None

    if variant == "thumb":
        base, target = job_dir, os.path.join(job_dir, "thumbs", f"{index}.jpg")
    else:
        if not images_dir:
            return None
        base, target = images_dir, os.path.join(images_dir, items["images"][index]["name"])
    try:
        base_real = os.path.realpath(base)
        target_real = os.path.realpath(target)
        if os.path.commonpath([base_real, target_real]) != base_real:
            return None
    except ValueError:
        return None
    return target_real if os.path.isfile(target_real) else None


# --------------------------------------------------------------------------- #
# 自足 HTML 匯出
# --------------------------------------------------------------------------- #

# 與 frontend/src/components/review/reviewStyles.js 的 BOX_STYLES 一一對應。匯出檔離開這台
# 機器就沒有 Nocturne 的 CSS 變數可用，所以這裡放的是 nocturne-tokens.css 裡的實際色值。
EXPORT_COLORS = {
    "tp": "#60ad64",     # --color-success-500
    "fp": "#dd7769",     # --color-danger-500
    "fn": "#c78b28",     # --color-warning-500
    "wrong": "#1aaac4",  # --color-cat-12-500
}
EXPORT_MAX_SIDE = 640
EXPORT_QUALITY = 75
EXPORT_LIMIT_DEFAULT = 100
# 每張約 50 KB；上限讓一份報告維持在寄得出去的大小
EXPORT_LIMIT_MAX = 300

STATUS_LABELS = {
    "all": "全部", "errors": "有錯誤", "clean": "全對",
    "fn": "有漏抓", "fp": "有誤報", "wrong": "有類別錯",
}


def _export_image_uri(path: Optional[str]) -> Optional[str]:
    """轉正、縮小、重新編碼成 JPEG data URI。重新編碼後不帶 EXIF，SVG <image> 不會再轉一次。"""
    if not path:
        return None
    try:
        image = _load_image(path)
    except Exception:  # noqa: BLE001 — 讀不到就只畫框，不讓整份匯出失敗
        return None
    image.thumbnail((EXPORT_MAX_SIDE, EXPORT_MAX_SIDE))
    buf = io.BytesIO()
    image.save(buf, "JPEG", quality=EXPORT_QUALITY)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _export_shapes(item: Dict[str, Any], class_names: List[str]) -> Dict[str, Any]:
    """框與標籤的繪製資料，規則與前端 BoxOverlay 的「兩者＋顯示標籤」模式相同。"""
    def name_of(cls: int) -> str:
        return class_names[cls] if 0 <= cls < len(class_names) else str(cls)

    width, height = item["width"], item["height"]
    font = max(12, round(max(width, height) / 40))
    gt_by_id = {g["id"]: g for g in item["gt"]}

    drawn = []
    for g in item["gt"]:
        text = None
        if g["status"] == "fn":
            text = f"漏：{name_of(g['cls'])}"
        elif g["status"] == "wrong":
            text = f"標註：{name_of(g['cls'])}"
        drawn.append((g, True, text))
    for p in item["preds"]:
        text = f"{name_of(p['cls'])} {p['conf']:.2f}"
        if p["status"] == "fp":
            text = f"誤報：{text}"
        elif p["status"] == "wrong":
            origin = gt_by_id.get(p["pair"])
            text = f"錯判：{name_of(origin['cls']) if origin else '?'}→{text}"
        drawn.append((p, False, text))

    shapes = []
    for box, dashed, text in drawn:
        x1, y1, x2, y2 = box["box"]
        shape = {
            "x": x1, "y": y1, "w": max(0.0, x2 - x1), "h": max(0.0, y2 - y1),
            "color": EXPORT_COLORS[box["status"]], "dashed": dashed, "label": None,
        }
        if text:
            text_w = sum(font if ord(ch) > 0x2E80 else font * 0.6 for ch in text) + font * 0.5
            text_h = font * 1.3
            label_y = y1 - text_h if y1 - text_h >= 0 else y1
            label_x = max(0.0, min(x1, width - text_w))
            shape["label"] = {
                "x": round(label_x, 1), "y": round(label_y, 1),
                "w": round(text_w, 1), "h": round(text_h, 1),
                "tx": round(label_x + font * 0.25, 1), "ty": round(label_y + font, 1),
                "text": text,
            }
        shapes.append(shape)
    return {"font": font, "shapes": shapes}


def render_export(
    job_id: str,
    conf: float,
    classes: Optional[List[int]] = None,
    status: str = "errors",
    sort: str = "errors",
    limit: int = EXPORT_LIMIT_DEFAULT,
    title: Optional[str] = None,
) -> Optional[Tuple[str, str]]:
    """
    以目前的篩選條件匯出一份自足 HTML，回傳 (html, 檔名)。

    比照成果報告「一個檔案就是全部」：影像以 base64 內嵌、框以 SVG 在伺服器端畫好，
    離線可開、無 JS 也正確、可直接列印成 PDF。**不落地到 REPORTS_DIR**——那裡是評估報告
    的清單，混進逐張檢視的匯出只會讓兩者都更難找。
    """
    job = get_job(job_id)
    if job is None or job["state"] != "done":
        return None
    result = query_items(job_id, conf, classes, status, sort, 0, limit)
    if result is None:
        return None

    class_names = result["class_names"]
    figures = []
    for item in result["items"]:
        path = image_path(job_id, item["index"], "full") or image_path(job_id, item["index"], "thumb")
        figures.append({
            "name": item["name"],
            "width": item["width"],
            "height": item["height"],
            "uri": _export_image_uri(path),
            "counts": item["counts"],
            "label_missing": item["label_missing"],
            **_export_shapes(item, class_names),
        })

    # autoescape 一律開啟：檔名、類別名與標題都來自使用者的資料
    env = Environment(loader=FileSystemLoader(str(report_service.TEMPLATE_DIR)), autoescape=True)
    report_title = title or f"逐張檢視：{job['session_name']}（{job['dataset_name']} / {job['split']}）"
    html = env.get_template("review_report.html.j2").render(
        title=report_title,
        job=job,
        env=report_service._environment_info(),
        conf=conf,
        iou=IOU_THRESHOLD,
        status_label=STATUS_LABELS.get(status, status),
        class_filter=[class_names[c] for c in (classes or []) if 0 <= c < len(class_names)],
        summary=result["summary"],
        total=result["total"],
        figures=figures,
        colors=EXPORT_COLORS,
    )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"{report_service._safe_stem(report_title, 'review')}_{stamp}.html"
    return html, filename
