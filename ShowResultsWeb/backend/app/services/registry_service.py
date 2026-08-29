"""權重登錄簿：把「這顆權重是什麼、怎麼訓練的、實測多少」寫進資料庫並查回來。

**這一層是附加的，不是取代。** `sessions.json`／`datasets.json`／評估 job 的
`manifest.json` 全部原封不動；登錄簿記的是與 session 生命週期脫鉤的長期事實。
兩者的分界：session 回答「現在載入了什麼」，登錄簿回答「這台機器看過哪些權重」。

三條在實作時反覆會被誘惑打破的規則：

1. **SHA-256 只在註冊／上傳時算，絕不在 `library_scanner.discover()` 裡算。**
   掃描是唯讀探索、要維持秒級；對整個 LocalLibrary 的每個 .pt 做雜湊會讓它變成分鐘級，
   而使用者按下「掃描」時根本還沒決定要不要用這些權重。
2. **絕不在持有 `SESSIONS_LOCK` / `EVAL_JOBS_LOCK` 時做 DB I/O。** 沿用
   `evaluation_service` 既有的鎖序規則；資料庫可能是網路上的 PostgreSQL，在鎖內等待
   網路往返會讓推論請求全部排隊。
3. **寫入失敗絕不讓主流程失敗。** 每個寫入函式都吞掉例外並只印日誌。上傳一顆模型不該
   因為資料庫沒起來而失敗——那會讓「資料庫是附加層」這句話變成謊話。

排序與彙總刻意在 Python 端做（過濾仍在 SQL）：登錄簿的規模是單機使用者手上的數十顆
權重，而「每顆權重歷次評估中的最佳 mAP」用 SQL 寫成跨方言都成立的形式並不划算。
"""
import hashlib
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func, or_, select

from app.db import engine as db_engine
from app.db.models import Evaluation, TrainingRun, Weight

_HASH_CHUNK = 1024 * 1024

# results.csv 的欄名經過 dir_handler/zip_handler 的清洗（去掉 "metrics/" 與 "(B)"），
# 因此這裡比對的是清洗後的樣子。用小寫比對以吸收版本間的大小寫差異。
_TRAIN_METRIC_KEYS = {
    "map50": ("map50", "map_50", "map@50"),
    "map50_95": ("map50-95", "map50_95", "map_50_95", "map@50-95"),
    "precision": ("precision", "p"),
    "recall": ("recall", "r"),
}

# 提升為資料表欄位的超參數子集（完整內容仍以 hyperparameters JSON 為準）
_HYPER_INT_KEYS = ("epochs", "imgsz", "batch", "patience", "seed")
_HYPER_FLOAT_KEYS = ("lr0", "lrf", "momentum", "weight_decay")
_HYPER_STR_KEYS = ("optimizer",)


# --------------------------------------------------------------------------- #
# 小工具
# --------------------------------------------------------------------------- #

def sha256_of_file(path: str) -> Optional[str]:
    """串流計算檔案雜湊。讀不到檔案時回 None，不拋例外。"""
    if not path or not os.path.isfile(path):
        return None
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(_HASH_CHUNK), b""):
                digest.update(chunk)
    except OSError as exc:
        print(f"[Registry] Could not hash {path}: {exc}")
        return None
    return digest.hexdigest()


def _as_int(value: Any) -> Optional[int]:
    try:
        if value is None or isinstance(value, bool):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> Optional[float]:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _pick_metric(metrics: Dict[str, Any], aliases) -> Optional[float]:
    lowered = {str(k).strip().lower(): v for k, v in (metrics or {}).items()}
    for alias in aliases:
        if alias in lowered:
            parsed = _as_float(lowered[alias])
            if parsed is not None:
                return round(parsed, 6)
    return None


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        stamped = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return stamped.isoformat()
    return str(value)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# 寫入
# --------------------------------------------------------------------------- #

def record_weight(
    session_data: Dict[str, Any],
    hyperparameters: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """把一顆剛註冊的權重寫進登錄簿，回傳它的 SHA-256（失敗時 None）。

    同一個 sha256 重複呼叫只會更新 `last_seen_at` 與來源欄位，不會產生第二列——
    使用者重掃 LocalLibrary 是常態操作，每次都新增一列會讓帳本立刻沒有可讀性。
    """
    weights_path = session_data.get("weights_path")
    sha = sha256_of_file(weights_path) if weights_path else None
    if sha is None:
        return None
    if not db_engine.is_available():
        return sha

    try:
        with db_engine.session_scope() as session:
            if session is None:
                return sha
            weight = session.execute(
                select(Weight).where(Weight.sha256 == sha)
            ).scalar_one_or_none()

            if weight is None:
                weight = Weight(sha256=sha, first_seen_at=_now())
                session.add(weight)

            weight.filename = os.path.basename(weights_path)
            weight.display_name = session_data.get("custom_name") or weight.filename
            weight.format_label = session_data.get("format_label")
            weight.model_arch = session_data.get("model_arch")
            weight.size_mb = _as_float(session_data.get("weights_size_mb"))
            weight.source_type = session_data.get("source_type")
            weight.source = session_data.get("source")
            weight.source_path = weights_path
            weight.last_seen_at = _now()

            _upsert_training_run(session, weight, session_data, hyperparameters)
        return sha
    except Exception as exc:  # noqa: BLE001 — 登錄簿失敗不得讓註冊失敗
        print(f"[Registry] record_weight failed for {weights_path}: {exc}")
        return sha


def _upsert_training_run(session, weight: Weight, session_data, hyperparameters) -> None:
    """寫入訓練紀錄。沒有 args.yaml 也沒有 results.csv 時就不建立這一列。"""
    hyper = dict(hyperparameters or {})
    metrics = dict(session_data.get("metrics_summary") or {})
    if not hyper and not metrics:
        return

    session.flush()  # 讓新建的 weight 拿到 id
    run = session.execute(
        select(TrainingRun).where(TrainingRun.weight_id == weight.id)
    ).scalar_one_or_none()
    if run is None:
        run = TrainingRun(weight_id=weight.id)
        session.add(run)

    run.hyperparameters = hyper
    run.final_metrics = metrics
    run.recorded_at = _now()

    for key in _HYPER_INT_KEYS:
        setattr(run, key, _as_int(hyper.get(key)))
    for key in _HYPER_FLOAT_KEYS:
        setattr(run, key, _as_float(hyper.get(key)))
    for key in _HYPER_STR_KEYS:
        raw = hyper.get(key)
        setattr(run, key, str(raw) if raw is not None else None)

    # model_cfg 的來源鍵在 args.yaml 裡叫 "model"，與 session dict 的 model_cfg 同義
    model_cfg = hyper.get("model") or session_data.get("model_cfg")
    run.model_cfg = str(model_cfg) if model_cfg else None

    # session dict 已解析過的 epochs/optimizer 是 args.yaml 缺席時的後備
    if run.epochs is None:
        run.epochs = _as_int(session_data.get("epochs"))
    if run.optimizer is None:
        opt = session_data.get("optimizer")
        run.optimizer = str(opt) if opt and opt != "N/A" else None

    for field, aliases in _TRAIN_METRIC_KEYS.items():
        setattr(run, field, _pick_metric(metrics, aliases))


def record_evaluation(job: Dict[str, Any], weight_sha: Optional[str]) -> bool:
    """把一次已完成的評估寫進登錄簿。`job` 是 `_job_public()` 的輸出。

    沒有 weight_sha（例如權重檔在評估期間被移走）就不寫——一筆無法歸屬到任何權重的
    指標在帳本裡是雜訊，不是資料。
    """
    if not weight_sha or not db_engine.is_available():
        return False

    try:
        with db_engine.session_scope() as session:
            if session is None:
                return False
            weight = session.execute(
                select(Weight).where(Weight.sha256 == weight_sha)
            ).scalar_one_or_none()
            if weight is None:
                print(f"[Registry] No weight row for {weight_sha[:12]}, skipping evaluation")
                return False

            job_id = job.get("job_id")
            row = session.execute(
                select(Evaluation).where(Evaluation.job_id == job_id)
            ).scalar_one_or_none()
            if row is None:
                row = Evaluation(job_id=job_id, weight_id=weight.id)
                session.add(row)

            overall = job.get("overall") or {}
            micro = job.get("micro") or {}
            vocab = job.get("vocab_check") or {}

            row.weight_id = weight.id
            row.dataset_name = job.get("dataset_name")
            row.dataset_format = job.get("dataset_format")
            row.split = job.get("split")
            row.image_count = _as_int(job.get("image_count"))

            row.map50 = _as_float(overall.get("map50"))
            row.map50_95 = _as_float(overall.get("map50_95"))
            row.precision = _as_float(overall.get("precision"))
            row.recall = _as_float(overall.get("recall"))
            row.f1 = _as_float(overall.get("f1"))
            row.fitness = _as_float(overall.get("fitness"))

            row.micro_accuracy = _as_float(micro.get("micro_accuracy"))
            row.micro_precision = _as_float(micro.get("micro_precision"))
            row.micro_recall = _as_float(micro.get("micro_recall"))
            row.micro_f1 = _as_float(micro.get("micro_f1"))
            row.micro_tp = _as_int(micro.get("tp"))
            row.micro_fp = _as_int(micro.get("fp"))
            row.micro_fn = _as_int(micro.get("fn"))
            row.conf_threshold = _as_float(micro.get("conf_threshold"))
            row.iou_threshold = _as_float(micro.get("iou_threshold"))

            row.speed_ms = dict(job.get("speed_ms") or {})
            row.per_class = list(job.get("per_class") or [])
            row.size_profile = list(job.get("size_profile") or [])
            row.vocab_status = vocab.get("status")
            row.vocab_message = vocab.get("message")
            row.started_at = job.get("started_at")
            row.finished_at = job.get("finished_at")
            row.elapsed_seconds = _as_float(job.get("elapsed_seconds"))

            # 類別表在註冊時讀不到（要載入 checkpoint 才有），評估時順手補上。
            names = vocab.get("model_names") or []
            if names and not weight.class_names:
                weight.class_names = list(names)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[Registry] record_evaluation failed for {job.get('job_id')}: {exc}")
        return False


# --------------------------------------------------------------------------- #
# 讀取
# --------------------------------------------------------------------------- #

WEIGHT_ORDER_FIELDS = (
    "last_seen_at",
    "first_seen_at",
    "display_name",
    "size_mb",
    "epochs",
    "best_map50",
    "best_map50_95",
    "best_micro_accuracy",
    "evaluation_count",
)

EVALUATION_ORDER_FIELDS = (
    "finished_at",
    "map50",
    "map50_95",
    "precision",
    "recall",
    "f1",
    "fitness",
    "micro_accuracy",
    "image_count",
    "elapsed_seconds",
)


def _training_run_view(run: Optional[TrainingRun]) -> Optional[Dict[str, Any]]:
    if run is None:
        return None
    return {
        "hyperparameters": run.hyperparameters or {},
        "final_metrics": run.final_metrics or {},
        "epochs": run.epochs,
        "optimizer": run.optimizer,
        "model_cfg": run.model_cfg,
        "imgsz": run.imgsz,
        "batch": run.batch,
        "lr0": run.lr0,
        "lrf": run.lrf,
        "momentum": run.momentum,
        "weight_decay": run.weight_decay,
        "patience": run.patience,
        "seed": run.seed,
        "map50": run.map50,
        "map50_95": run.map50_95,
        "precision": run.precision,
        "recall": run.recall,
        "recorded_at": _iso(run.recorded_at),
    }


def _evaluation_view(row: Evaluation, weight_name: Optional[str] = None) -> Dict[str, Any]:
    return {
        "job_id": row.job_id,
        "weight_sha256": row.weight.sha256 if row.weight else None,
        "weight_name": weight_name or (row.weight.display_name if row.weight else None),
        "dataset_name": row.dataset_name,
        "dataset_format": row.dataset_format,
        "split": row.split,
        "image_count": row.image_count,
        "map50": row.map50,
        "map50_95": row.map50_95,
        "precision": row.precision,
        "recall": row.recall,
        "f1": row.f1,
        "fitness": row.fitness,
        "micro_accuracy": row.micro_accuracy,
        "micro_precision": row.micro_precision,
        "micro_recall": row.micro_recall,
        "micro_f1": row.micro_f1,
        "micro_tp": row.micro_tp,
        "micro_fp": row.micro_fp,
        "micro_fn": row.micro_fn,
        "conf_threshold": row.conf_threshold,
        "iou_threshold": row.iou_threshold,
        "speed_ms": row.speed_ms or {},
        "per_class": row.per_class or [],
        "size_profile": row.size_profile or [],
        "vocab_status": row.vocab_status,
        "vocab_message": row.vocab_message,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
        "elapsed_seconds": row.elapsed_seconds,
    }


def _weight_view(weight: Weight) -> Dict[str, Any]:
    evaluations = list(weight.evaluations or [])
    run = weight.training_run

    def _best(attr: str) -> Optional[float]:
        values = [getattr(e, attr) for e in evaluations if getattr(e, attr) is not None]
        return max(values) if values else None

    return {
        "sha256": weight.sha256,
        "filename": weight.filename,
        "display_name": weight.display_name,
        "format_label": weight.format_label,
        "model_arch": weight.model_arch,
        "size_mb": weight.size_mb,
        "source_type": weight.source_type,
        "source": weight.source,
        "source_path": weight.source_path,
        "class_names": list(weight.class_names or []),
        "first_seen_at": _iso(weight.first_seen_at),
        "last_seen_at": _iso(weight.last_seen_at),
        "evaluation_count": len(evaluations),
        "best_map50": _best("map50"),
        "best_map50_95": _best("map50_95"),
        "best_micro_accuracy": _best("micro_accuracy"),
        "training_run": _training_run_view(run),
    }


def _sort_key(field: str):
    def key(item: Dict[str, Any]):
        value = item.get(field)
        if field in ("epochs",):
            value = (item.get("training_run") or {}).get("epochs")
        # None 一律排到最後，不論升冪降冪——「沒有這個數字」不該被當成 0 名列前茅
        return (value is None, value if value is not None else "")
    return key


def query_weights(
    q: Optional[str] = None,
    model_arch: Optional[str] = None,
    order_by: str = "last_seen_at",
    order: str = "desc",
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """回傳 {"weights": [...], "total": n}。資料庫不可用時由呼叫端負責回 503。"""
    if order_by not in WEIGHT_ORDER_FIELDS:
        order_by = "last_seen_at"

    with db_engine.session_scope() as session:
        if session is None:
            return {"weights": [], "total": 0}

        stmt = select(Weight)
        if model_arch:
            stmt = stmt.where(Weight.model_arch == model_arch)
        if q:
            needle = f"%{q.strip()}%"
            stmt = stmt.where(
                or_(Weight.display_name.ilike(needle), Weight.filename.ilike(needle))
            )
        rows = session.execute(stmt).scalars().unique().all()
        views = [_weight_view(w) for w in rows]

    views.sort(key=_sort_key(order_by), reverse=(order or "desc").lower() != "asc")
    total = len(views)
    start = max(offset, 0)
    end = start + limit if limit and limit > 0 else None
    return {"weights": views[start:end], "total": total}


def get_weight_detail(sha256: str) -> Optional[Dict[str, Any]]:
    with db_engine.session_scope() as session:
        if session is None:
            return None
        weight = session.execute(
            select(Weight).where(Weight.sha256 == sha256)
        ).scalar_one_or_none()
        if weight is None:
            return None
        view = _weight_view(weight)
        evaluations = sorted(
            (_evaluation_view(e, weight.display_name) for e in weight.evaluations or []),
            key=lambda e: e.get("finished_at") or "",
            reverse=True,
        )
        return {
            "weight": view,
            "training_run": view.get("training_run"),
            "evaluations": evaluations,
        }


def query_evaluations(
    weight_sha: Optional[str] = None,
    dataset_name: Optional[str] = None,
    split: Optional[str] = None,
    order_by: str = "finished_at",
    order: str = "desc",
    limit: int = 100,
    offset: int = 0,
) -> Dict[str, Any]:
    if order_by not in EVALUATION_ORDER_FIELDS:
        order_by = "finished_at"

    with db_engine.session_scope() as session:
        if session is None:
            return {"evaluations": [], "total": 0}

        stmt = select(Evaluation).join(Weight, Evaluation.weight_id == Weight.id)
        if weight_sha:
            stmt = stmt.where(Weight.sha256 == weight_sha)
        if dataset_name:
            stmt = stmt.where(Evaluation.dataset_name == dataset_name)
        if split:
            stmt = stmt.where(Evaluation.split == split)
        rows = session.execute(stmt).scalars().unique().all()
        views = [_evaluation_view(row) for row in rows]

    views.sort(key=_sort_key(order_by), reverse=(order or "desc").lower() != "asc")
    total = len(views)
    start = max(offset, 0)
    end = start + limit if limit and limit > 0 else None
    return {"evaluations": views[start:end], "total": total}


_BEST_METRICS = (
    ("map50", "mAP@50"),
    ("map50_95", "mAP@50-95"),
    ("precision", "Precision"),
    ("recall", "Recall"),
    ("micro_accuracy", "Micro-Accuracy (Jaccard)"),
)


def stats() -> Dict[str, Any]:
    """總覽：筆數、已評估過的資料集、各指標的最佳紀錄。"""
    payload = {
        "backend": db_engine.backend_name(),
        "available": db_engine.is_available(),
        "total_weights": 0,
        "total_training_runs": 0,
        "total_evaluations": 0,
        "datasets_evaluated": [],
        "best": [],
    }
    try:
        return _stats_locked(payload)
    except db_engine.RegistryUnavailable:
        # 這個端點是前端判斷「登錄簿在不在」的唯一依據，**絕不能失敗**。
        # 資料庫在執行期掛掉時，誠實回報 available:false 而不是丟錯。
        payload["available"] = False
        return payload


def _stats_locked(payload: Dict[str, Any]) -> Dict[str, Any]:
    with db_engine.session_scope() as session:
        if session is None:
            return payload

        payload["total_weights"] = session.execute(
            select(func.count()).select_from(Weight)
        ).scalar_one()
        payload["total_training_runs"] = session.execute(
            select(func.count()).select_from(TrainingRun)
        ).scalar_one()
        payload["total_evaluations"] = session.execute(
            select(func.count()).select_from(Evaluation)
        ).scalar_one()
        payload["datasets_evaluated"] = sorted(
            name
            for name in session.execute(
                select(Evaluation.dataset_name).distinct()
            ).scalars().all()
            if name
        )

        best = []
        for field, label in _BEST_METRICS:
            column = getattr(Evaluation, field)
            row = session.execute(
                select(Evaluation)
                .where(column.is_not(None))
                .order_by(column.desc())
                .limit(1)
            ).scalar_one_or_none()
            if row is None:
                continue
            best.append({
                "metric": label,
                "value": getattr(row, field),
                "weight_sha256": row.weight.sha256 if row.weight else None,
                "weight_name": row.weight.display_name if row.weight else None,
                "dataset_name": row.dataset_name,
                "split": row.split,
            })
        payload["best"] = best
    return payload


def delete_weight(sha256: str) -> Optional[Dict[str, Any]]:
    """刪除一顆權重及其訓練紀錄與所有評估（cascade）。找不到回 None。"""
    with db_engine.session_scope() as session:
        if session is None:
            return None
        weight = session.execute(
            select(Weight).where(Weight.sha256 == sha256)
        ).scalar_one_or_none()
        if weight is None:
            return None
        removed = len(weight.evaluations or [])
        session.delete(weight)
        return {"sha256": sha256, "deleted_evaluations": removed}


__all__ = [
    "EVALUATION_ORDER_FIELDS",
    "WEIGHT_ORDER_FIELDS",
    "delete_weight",
    "get_weight_detail",
    "query_evaluations",
    "query_weights",
    "record_evaluation",
    "record_weight",
    "sha256_of_file",
    "stats",
]
