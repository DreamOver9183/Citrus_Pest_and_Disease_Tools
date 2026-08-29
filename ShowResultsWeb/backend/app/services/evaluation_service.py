"""
驗證評估的 job 機制：讓載入的模型實際跑過資料集，算出**當下的**指標。

在此之前，「消融分析」顯示的每一個數字都來自訓練當時寫進 results.png 的舊值，而不同
模型的數字可能來自不同的資料集與不同的 split——這讓消融比較在方法學上是無效的，因為
消融研究的前提就是共同的評估協定。本模組提供那個共同協定。

**硬規則：本模組不得 import model_service。** 理由與 export_service 完全相同（見該模組
的模組註解）：`ModelManager._lock` 是非重入鎖且 `predict()` 全程持有，走 ModelManager
會讓每個推論請求排在整場評估後面，而在持鎖狀態下再呼叫 `load_model()` 會直接死鎖；
`load_model()` 還會把使用者在「即時診斷」載入的模型踢掉。評估自建用完即丟的 YOLO 實例。

**為什麼用 ultralytics 的 `model.val()` 而不自己算 mAP：** 自行實作 IoU 配對與 PR 積分
很容易在細節上算錯（插值方式、NMS 前後順序、重複配對的處理），而一個「自己算的、和
ultralytics 對不上的 mAP」在學術場合是負分。`val()` 同時會產出 confusion_matrix.png
與 BoxPR_curve.png，正好是既有 /api/metrics 已在展示的圖種。

併發模型與 export_service 一致：單一 daemon 執行緒 + 有界 queue.Queue。不用
ThreadPoolExecutor（atexit hook 會 join 非 daemon 執行緒，Ctrl-C 會被卡住整場評估）。
同樣沒有 cancel：執行中的 val() 無法從 Python 中止。
"""
import gc
import json
import logging
import os
import queue
import re
import shutil
import statistics
import threading
import time
import traceback
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from app.core.config import (
    EVAL_DIR,
    EVAL_JOB_TTL_HOURS,
    MAX_EVAL_JOBS,
    MAX_QUEUED_EVALS,
)
from app.services import registry_service
from app.services.dataset_resolver import DatasetUnavailable, ResolvedSplit, resolve_split

JOB_SCHEMA_VERSION = 1

EVAL_JOBS: Dict[str, Dict[str, Any]] = {}
# 鎖序規則：絕不在持有 EVAL_JOBS_LOCK 時取得 SESSIONS_LOCK / DATASETS_LOCK，反之亦然。
EVAL_JOBS_LOCK = threading.RLock()

_QUEUE: "queue.Queue[str]" = queue.Queue(maxsize=MAX_QUEUED_EVALS)
_WORKER: Optional[threading.Thread] = None
_WORKER_LOCK = threading.Lock()

LOG_TAIL_MAXLEN = 40

# 極小物件的門檻：框面積佔整張影像的比例。這個資料集的 Canker 有 31.5% 的框落在此
# 門檻以下，而 Sooty_Mold 一個也沒有——正是 P2 檢測層要解決的那個分布。
TINY_BOX_AREA_RATIO = 0.001

# 混淆矩陣的累積門檻。ultralytics 的 DetectionValidator 用 confusion_matrix_conf
#（預設 0.25）與 process_batch(iou_thres=0.45)。這兩個值必須跟著 Micro-Accuracy 一起
# 被記錄下來——Jaccard index 是**門檻相依**的單點量測，脫離門檻就無法解讀，也無法
# 跨紀錄比較。mAP 沒有這個問題（它對所有門檻積分），兩者不可並列解讀。
CM_CONF_THRESHOLD = 0.25
CM_IOU_THRESHOLD = 0.45

STAGES = {
    "queued": ("等待中", 0),
    "resolving": ("準備資料集", 5),
    "checking": ("比對類別詞彙", 15),
    "validating": ("推論與評估中", 25),
    "profiling": ("統計標註尺寸", 88),
    "done": ("完成", 100),
    "failed": ("失敗", 0),
}

# ultralytics 用 colorstr() 在訊息裡嵌 ANSI 色碼，原樣送到前端會變成亂碼。
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class _LogTailHandler(logging.Handler):
    """把 ultralytics 的 log 收進 job 的環形緩衝，作為評估階段唯一的真實回饋。"""

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


# --------------------------------------------------------------------------- #
# 類別詞彙比對
# --------------------------------------------------------------------------- #

def compare_vocabularies(model_names: Dict[int, str], dataset_names: List[str]) -> Dict[str, Any]:
    """
    比對模型 checkpoint 的類別表與資料集 data.yaml 的類別表。

    這是整個評估最重要的正確性前提：兩者不一致時，算出來的每一個數字都是垃圾，
    而且**不會有任何錯誤訊息**——ultralytics 只會照索引配對。這不是假想風險：
    model_service 的 SSD 類別表寫死 12 類，而實際的 v5 資料集是 8 類。

    回傳 status:
      - "match"      完全一致，可放心解讀結果
      - "name_drift" 數量相同但名稱有出入 → 允許執行，但結果與報告要標警告
      - "mismatch"   數量不同 → 呼叫端必須拒絕執行
    """
    model_list = [model_names[k] for k in sorted(model_names)] if model_names else []
    dataset_list = list(dataset_names or [])

    if len(model_list) != len(dataset_list):
        return {
            "status": "mismatch",
            "model_nc": len(model_list),
            "dataset_nc": len(dataset_list),
            "model_names": model_list,
            "dataset_names": dataset_list,
            "differences": [],
            "message": (
                f"模型有 {len(model_list)} 個類別，資料集有 {len(dataset_list)} 個。"
                "類別數不同時算出的指標沒有意義，已拒絕執行。"
            ),
        }

    differences = [
        {"index": i, "model": m, "dataset": d}
        for i, (m, d) in enumerate(zip(model_list, dataset_list))
        if m != d
    ]
    if not differences:
        return {
            "status": "match",
            "model_nc": len(model_list),
            "dataset_nc": len(dataset_list),
            "model_names": model_list,
            "dataset_names": dataset_list,
            "differences": [],
            "message": None,
        }

    return {
        "status": "name_drift",
        "model_nc": len(model_list),
        "dataset_nc": len(dataset_list),
        "model_names": model_list,
        "dataset_names": dataset_list,
        "differences": differences,
        "message": (
            f"類別數相同但有 {len(differences)} 個名稱不一致。指標仍以索引配對計算，"
            "解讀時請確認兩邊指的是同一批類別。"
        ),
    }


# --------------------------------------------------------------------------- #
# 邊界框級別的 TP/FP/FN 指標（依《效能指標定義與評測方法》§2）
# --------------------------------------------------------------------------- #
#
# 該文件對影像辨識模組的定義（物件偵測任務中 TN 無限且不可統計，一律簡化為 TN = 0）：
#
#     Precision = TP / (TP + FP)
#     Recall    = TP / (TP + FN)
#     F1-Score  = 2 · Precision · Recall / (Precision + Recall)
#     Accuracy  = TP / (TP + FP + FN) = 1 / (1/Precision + 1/Recall − 1)
#
# 最後一項就是使用者要的 **Micro-Accuracy（Jaccard index）**——當 TN = 0 時，
# 準確率的定義自然化簡成交集除以聯集。兩個名字指的是同一個量。
#
# 「Micro（微平均）」的意思是先把所有類別的 TP/FP/FN **加總**再相除，而不是各類別先
# 算出比率再平均（後者是 macro）。這個差別在類別數量極不均衡時很大：本資料集的
# Sooty_Mold 與 Canker 框數差一個數量級，macro 會讓框數極少的類別擁有和主力類別相同的
# 話語權。micro 反映的是「整個測試集上的整體正確比例」。


def accuracy_from_precision_recall(precision, recall):
    """由 P/R 反推 Accuracy：1 / (1/P + 1/R − 1)。

    這是上面那條恆等式的另一半，存在的意義是**交叉驗算**：對同一組 TP/FP/FN，
    它必須與 TP/(TP+FP+FN) 給出相同的值。單元測試用它證明兩條路徑一致。
    P 或 R 為 0 時無定義（分母會爆），回 None。
    """
    try:
        p, r = float(precision), float(recall)
    except (TypeError, ValueError):
        return None
    if p <= 0 or r <= 0:
        return None
    denom = (1.0 / p) + (1.0 / r) - 1.0
    if denom <= 0:
        return None
    return round(1.0 / denom, 4)


def _safe_ratio(numerator, denominator):
    return round(numerator / denominator, 4) if denominator > 0 else None


def micro_accuracy_from_matrix(matrix, nc=None, class_names=None):
    """由 ultralytics 的混淆矩陣算出邊界框級別的 TP/FP/FN 與四項衍生指標。

    矩陣是 `(nc+1) x (nc+1)`，慣例為 `matrix[預測類別, 真實類別]`，最後一列／行是
    background（已於 ultralytics 8.4.122 的 `ConfusionMatrix.process_batch` 確認）。
    對每個**真實**類別 i：

        TP_i = M[i][i]
        FP_i = ΣM[i][:] − TP_i     （含誤判成別類，以及對到 background 的多餘預測）
        FN_i = ΣM[:][i] − TP_i     （含漏檢，以及被判成別類的框）

    一個分類錯誤的框同時計入 FP 與 FN，這是定義使然，不是重複計算。

    分母為 0（完全沒有預測也沒有標註）時回 `None` 而不是 0.0——「沒有東西可算」與
    「算出來是零」是兩件不同的事，混為一談會在帳本裡留下假的 0 分紀錄。

    **門檻的誠實聲明**：TP/FP/FN 來自 ultralytics 累積的混淆矩陣，其配對門檻是該套件的
    預設值 conf=0.25 / IoU=0.45，而指標定義文件 §2 寫的是 IoU ≥ 0.5。這 0.05 的落差
    無法在不改寫 ultralytics 內部呼叫的前提下消除（`process_batch` 的 iou_thres 在
    `models/yolo/detect/val.py` 中是寫死的），因此選擇**把實際使用的門檻一起存進每一筆
    紀錄**（conf_threshold / iou_threshold 兩欄），而不是宣稱 0.5 卻用 0.45 去算。
    見 architecture.md §10 的「已知落差」。

    刻意寫成不依賴 numpy 的純函式：它是單元測試的接縫，測試餵手算過答案的合成矩陣
    即可驗證，不需要真實權重與影像（兩者都被 .gitignore 排除）。
    """
    empty = {
        "micro_accuracy": None, "micro_precision": None,
        "micro_recall": None, "micro_f1": None,
        "tp": 0, "fp": 0, "fn": 0,
        "conf_threshold": CM_CONF_THRESHOLD, "iou_threshold": CM_IOU_THRESHOLD,
        "per_class": [],
    }
    if matrix is None:
        return empty
    try:
        rows = [[float(v) for v in row] for row in matrix]
    except (TypeError, ValueError):
        return empty
    size = len(rows)
    if size == 0 or any(len(row) != size for row in rows):
        return empty

    # 未指定 nc 時，最後一列／行是 background，其餘才是真實類別
    real = size - 1 if nc is None else max(0, min(int(nc), size))

    names = list(class_names or [])
    total_tp = total_fp = total_fn = 0.0
    per_class = []
    for i in range(real):
        tp = rows[i][i]
        fp = sum(rows[i]) - tp
        fn = sum(rows[r][i] for r in range(size)) - tp
        total_tp += tp
        total_fp += fp
        total_fn += fn
        precision = _safe_ratio(tp, tp + fp)
        recall = _safe_ratio(tp, tp + fn)
        f1 = (
            round(2 * precision * recall / (precision + recall), 4)
            if precision and recall and (precision + recall) > 0
            else None
        )
        per_class.append({
            "class_id": i,
            "name": names[i] if i < len(names) else str(i),
            "tp": int(tp), "fp": int(fp), "fn": int(fn),
            "precision": precision,
            "recall": recall,
            "f1": f1,
            # 逐類別的 Accuracy，也就是該類別自己的 Jaccard index
            "accuracy": _safe_ratio(tp, tp + fp + fn),
        })

    micro_precision = _safe_ratio(total_tp, total_tp + total_fp)
    micro_recall = _safe_ratio(total_tp, total_tp + total_fn)
    micro_f1 = (
        round(2 * micro_precision * micro_recall / (micro_precision + micro_recall), 4)
        if micro_precision and micro_recall and (micro_precision + micro_recall) > 0
        else None
    )
    return {
        "micro_accuracy": _safe_ratio(total_tp, total_tp + total_fp + total_fn),
        "micro_precision": micro_precision,
        "micro_recall": micro_recall,
        "micro_f1": micro_f1,
        "tp": int(total_tp), "fp": int(total_fp), "fn": int(total_fn),
        "conf_threshold": CM_CONF_THRESHOLD,
        "iou_threshold": CM_IOU_THRESHOLD,
        "per_class": per_class,
    }


# --------------------------------------------------------------------------- #
# 標註尺寸剖面（不需推論，直接讀標註文字檔）
# --------------------------------------------------------------------------- #

def box_size_profile(labels_dir: str, class_names: List[str]) -> List[Dict[str, Any]]:
    """
    統計每個類別的標註框尺寸分布。

    這是「為什麼需要 P2 檢測層」的證據來源：把每類別的 AP 與中位框面積並排，就能看出
    低 AP 是否集中在小物件類別。成本近乎零——只讀 .txt，不碰任何影像像素。

    面積以「佔整張影像的比例」表示（YOLO 標註本來就是正規化座標），因此不需要讀圖片
    尺寸，也讓不同解析度的影像可以直接比較。
    """
    areas: Dict[int, List[float]] = defaultdict(list)

    if os.path.isdir(labels_dir):
        for name in os.listdir(labels_dir):
            if not name.lower().endswith(".txt") or name == "classes.txt":
                continue
            try:
                with open(os.path.join(labels_dir, name), "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        parts = line.split()
                        if len(parts) < 5:
                            continue
                        try:
                            cls = int(float(parts[0]))
                            areas[cls].append(float(parts[3]) * float(parts[4]))
                        except ValueError:
                            continue
            except OSError:
                continue

    profile = []
    for idx, cls_name in enumerate(class_names):
        values = areas.get(idx, [])
        if values:
            profile.append({
                "class_id": idx,
                "name": cls_name,
                "boxes": len(values),
                "median_area_pct": round(statistics.median(values) * 100, 4),
                "min_area_pct": round(min(values) * 100, 4),
                "max_area_pct": round(max(values) * 100, 4),
                "tiny_pct": round(
                    sum(1 for v in values if v < TINY_BOX_AREA_RATIO) / len(values) * 100, 1
                ),
            })
        else:
            profile.append({
                "class_id": idx, "name": cls_name, "boxes": 0,
                "median_area_pct": None, "min_area_pct": None,
                "max_area_pct": None, "tiny_pct": None,
            })
    return profile


# --------------------------------------------------------------------------- #
# 實際執行（測試接縫）
# --------------------------------------------------------------------------- #

def write_data_yaml(images_dir: str, class_names: List[str], dest: Path) -> Path:
    """
    合成一份 ultralytics 能吃的 data.yaml。

    刻意**不重用資料集自帶的 data.yaml**：實測那份的 `path:` 指向訓練當時他機的絕對
    路徑（f:\\115柑橘病蟲害專題\\...），而且其中的子目錄在資料集內根本不存在。沿用它
    會讓 val() 掃到 0 張影像，且極難追查。這裡只從磁碟上實際存在的目錄反推。

    ultralytics 由影像路徑推導標註路徑（把 /images/ 換成 /labels/），所以 images_dir
    的父層必須同時有 labels/——dataset_resolver 的兩條路徑都保證了這件事。
    """
    split_dir = os.path.dirname(images_dir)          # <base>/<split>
    base = os.path.dirname(split_dir)                # <base>
    split_name = os.path.basename(split_dir)

    content = {
        "path": base.replace("\\", "/"),
        "train": f"{split_name}/images",
        "val": f"{split_name}/images",
        "names": {i: n for i, n in enumerate(class_names)},
    }
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        yaml.safe_dump(content, f, allow_unicode=True, sort_keys=False)
    return dest


def _run_validation(job_dir: Path, weights: str, data_yaml: Path, log_sink: deque) -> Dict[str, Any]:
    """
    跑 model.val() 並把 DetMetrics 正規化成純資料。

    這是測試的接縫：單元測試一律 monkeypatch 這個函式，因為真實評估需要真實的
    checkpoint 與影像（兩者都被 .gitignore 排除）。
    """
    from ultralytics import YOLO  # 延後 import，讓不評估的路徑不用付這個成本

    logger = logging.getLogger("ultralytics")
    handler = _LogTailHandler(log_sink)
    logger.addHandler(handler)

    model = None
    try:
        model = YOLO(weights)
        model_names = dict(model.names or {})

        results = model.val(
            data=str(data_yaml),
            split="val",
            device="cpu",
            project=str(job_dir),
            name="val",
            exist_ok=True,
            plots=True,
            verbose=False,
        )

        box = results.box
        names = getattr(results, "names", None) or model_names
        name_list = [names[k] for k in sorted(names)] if names else []

        # Micro-Accuracy 的來源。ultralytics 在 finalize_metrics() 無條件把驗證器的
        # ConfusionMatrix 掛到 metrics 上（8.4.122 已確認），但用 getattr 取值仍是必要的：
        # 這個屬性不在 DetMetrics 的類別定義裡，換一個 ultralytics 版本就可能沒有。
        # 取不到時降級成「沒有這項指標」，而不是讓整場評估失敗。
        cm = getattr(results, "confusion_matrix", None)
        micro = micro_accuracy_from_matrix(
            getattr(cm, "matrix", None), class_names=name_list
        )
        micro_by_class = {entry["class_id"]: entry for entry in micro["per_class"]}

        per_class = []
        for i, class_idx in enumerate(box.ap_class_index):
            p, r, ap50, ap = box.class_result(i)
            idx = int(class_idx)
            per_class.append({
                "class_id": idx,
                "name": name_list[idx] if idx < len(name_list) else str(idx),
                "precision": round(float(p), 4),
                "recall": round(float(r), 4),
                "ap50": round(float(ap50), 4),
                "ap50_95": round(float(ap), 4),
                # 逐類別 Accuracy（Jaccard）。與上面 ultralytics 的 P/R 不同源：
                # 那兩個取自 PR 曲線的最佳 F1 點，這個來自固定門檻的混淆矩陣。
                "accuracy": (micro_by_class.get(idx) or {}).get("accuracy"),
            })

        speed = getattr(results, "speed", None) or {}
        precision = round(float(box.mp), 4)
        recall = round(float(box.mr), 4)
        map50 = round(float(box.map50), 4)
        map50_95 = round(float(box.map), 4)
        pr_sum = precision + recall
        return {
            "model_names": model_names,
            "overall": {
                "map50": map50,
                "map50_95": map50_95,
                "precision": precision,
                "recall": recall,
                # F1 由 P/R 導出；fitness 沿用 ultralytics 的加權（0.1·mAP50 + 0.9·mAP50-95），
                # 刻意不自創權重，才能和 ultralytics 自己印出來的數字對得上。
                "f1": round(2 * precision * recall / pr_sum, 4) if pr_sum > 0 else 0.0,
                "fitness": round(0.1 * map50 + 0.9 * map50_95, 4),
            },
            "micro": micro,
            "per_class": per_class,
            "speed_ms": {k: round(float(v), 2) for k, v in speed.items()},
            "plots": _collect_plots(job_dir / "val"),
        }
    finally:
        logger.removeHandler(handler)
        if model is not None:
            del model
        gc.collect()


_PLOT_FILES = {
    "confusion_matrix": "confusion_matrix.png",
    "confusion_matrix_normalized": "confusion_matrix_normalized.png",
    "pr_curve": "BoxPR_curve.png",
    "f1_curve": "BoxF1_curve.png",
    "p_curve": "BoxP_curve.png",
    "r_curve": "BoxR_curve.png",
}


def _collect_plots(val_dir: Path) -> Dict[str, str]:
    """挑出 val() 產出的圖表。缺哪張就不列，不硬湊。"""
    found = {}
    for key, filename in _PLOT_FILES.items():
        candidate = val_dir / filename
        if candidate.exists():
            found[key] = str(candidate).replace("\\", "/")
    return found


def peek_model_names(weights: str) -> Dict[int, str]:
    """
    只為了取類別表而載入模型。

    測試會 monkeypatch 這個函式。分開成獨立函式是因為詞彙比對必須在跑完整場評估
    **之前**發生——讓使用者等 60 秒才得知類別對不上是最糟的順序。
    """
    from ultralytics import YOLO

    model = None
    try:
        model = YOLO(weights)
        return dict(model.names or {})
    finally:
        if model is not None:
            del model
        gc.collect()


# --------------------------------------------------------------------------- #
# job 對外形狀
# --------------------------------------------------------------------------- #

def _job_public(job: Dict[str, Any]) -> Dict[str, Any]:
    """
    job 的對外形狀。

    **逐欄列舉，任何欄位都要顯式給值。** 路由使用 response_model_exclude_unset=True，
    未設定的 key 會直接從 JSON 消失並在前端變成 undefined。
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
        "weight_sha256": job.get("weight_sha256"),
        "dataset_id": job.get("dataset_id"),
        "dataset_name": job.get("dataset_name"),
        "dataset_format": job.get("dataset_format"),
        "split": job.get("split"),
        "state": job.get("state"),
        "stage": stage,
        "stage_label": label,
        "progress": 100 if job.get("state") == "done" else progress,
        "message": job.get("message"),
        "created_at": job.get("created_at"),
        "started_at": started,
        "finished_at": finished,
        "elapsed_seconds": elapsed,
        "image_count": job.get("image_count"),
        "vocab_check": job.get("vocab_check"),
        "overall": job.get("overall"),
        "micro": job.get("micro"),
        "per_class": job.get("per_class") or [],
        "size_profile": job.get("size_profile") or [],
        "speed_ms": job.get("speed_ms") or {},
        "plot_urls": job.get("plot_urls") or {},
        "log_tail": list(job.get("log_tail") or []),
    }


def get_jobs_snapshot() -> Dict[str, Any]:
    with EVAL_JOBS_LOCK:
        jobs = [_job_public(j) for j in EVAL_JOBS.values()]
    jobs.sort(key=lambda j: j.get("created_at") or "", reverse=True)
    return {"jobs": jobs}


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    with EVAL_JOBS_LOCK:
        job = EVAL_JOBS.get(job_id)
        return _job_public(job) if job else None


# --------------------------------------------------------------------------- #
# 執行流程
# --------------------------------------------------------------------------- #

def _set_stage(job_id: str, stage: str, message: Optional[str] = None) -> None:
    with EVAL_JOBS_LOCK:
        job = EVAL_JOBS.get(job_id)
        if job is None:
            return
        job["stage"] = stage
        if message is not None:
            job["message"] = message


def _fail(job_id: str, message: str) -> None:
    with EVAL_JOBS_LOCK:
        job = EVAL_JOBS.get(job_id)
        if job is None:
            return
        job["state"] = "failed"
        job["stage"] = "failed"
        job["message"] = message
        job["finished_at"] = _now_iso()
        started = job.get("_started_monotonic")
        if started:
            job["elapsed_seconds"] = round(time.monotonic() - started, 1)


def _process_job(job_id: str) -> None:
    with EVAL_JOBS_LOCK:
        job = EVAL_JOBS.get(job_id)
        if job is None:
            return
        job["state"] = "running"
        job["started_at"] = _now_iso()
        job["_started_monotonic"] = time.monotonic()
        stats = job["_dataset_stats"]
        weights = job["source_weights"]
        split = job["split"]
        job_dir = Path(job["job_dir"])
        log_sink = job["log_tail"]

    # 權重雜湊在**背景執行緒**算，不在 submit 的請求路徑上：一顆 best.pt 動輒數十 MB，
    # 沒有理由讓使用者按下「開始評估」時多等那段 I/O。放在這裡仍然遠早於 val()，
    # 也保證是在權重檔還存在的時候算的（整場評估要跑數分鐘，期間 session 可能被刪除）。
    weight_sha = registry_service.sha256_of_file(weights) if weights else None
    with EVAL_JOBS_LOCK:
        if job_id in EVAL_JOBS:
            EVAL_JOBS[job_id]["weight_sha256"] = weight_sha

    resolved: Optional[ResolvedSplit] = None
    try:
        # --- 1. 把資料集變成磁碟上的實體目錄 ---
        _set_stage(job_id, "resolving")
        job_dir.mkdir(parents=True, exist_ok=True)
        resolved = resolve_split(stats, split, str(job_dir / "data"))
        if resolved.image_count == 0:
            _fail(job_id, f"「{split}」split 內沒有任何影像。")
            return
        with EVAL_JOBS_LOCK:
            if job_id in EVAL_JOBS:
                EVAL_JOBS[job_id]["image_count"] = resolved.image_count

        # --- 2. 類別詞彙比對（必須在跑完整場評估之前） ---
        _set_stage(job_id, "checking")
        dataset_names = list(stats.get("declared_names") or [])
        model_names = peek_model_names(weights)
        vocab = compare_vocabularies(model_names, dataset_names)
        with EVAL_JOBS_LOCK:
            if job_id in EVAL_JOBS:
                EVAL_JOBS[job_id]["vocab_check"] = vocab
        if vocab["status"] == "mismatch":
            _fail(job_id, vocab["message"])
            return

        # 名稱以模型為準：ultralytics 照索引配對，用模型的名字才對得上輸出
        class_names = vocab["model_names"] or dataset_names

        # --- 3. 實際評估 ---
        _set_stage(job_id, "validating")
        data_yaml = write_data_yaml(resolved.images_dir, class_names, job_dir / "data.yaml")
        outcome = _run_validation(job_dir, weights, data_yaml, log_sink)

        # --- 4. 標註尺寸剖面 ---
        _set_stage(job_id, "profiling")
        profile = box_size_profile(resolved.labels_dir, class_names)

        # 影像已經用不到了，在標記 done 之前就清掉。順序很重要：若留到 finally，
        # 「狀態是 done」與「暫存已清空」之間會有一段時間差，觀察者看到的 done
        # 就不是誠實的狀態。
        _cleanup_extracted(resolved)
        resolved = None

        with EVAL_JOBS_LOCK:
            job = EVAL_JOBS.get(job_id)
            if job is None:
                return
            job["overall"] = outcome["overall"]
            job["micro"] = outcome.get("micro")
            job["per_class"] = outcome["per_class"]
            job["size_profile"] = profile
            job["speed_ms"] = outcome["speed_ms"]
            job["plot_paths"] = outcome["plots"]
            job["plot_urls"] = {
                key: f"/api/evaluations/{job_id}/plot/{key}" for key in outcome["plots"]
            }
            job["state"] = "done"
            job["stage"] = "done"
            job["message"] = vocab.get("message")
            job["finished_at"] = _now_iso()
            job["elapsed_seconds"] = round(time.monotonic() - job["_started_monotonic"], 1)
        _write_manifest(job_id)

        # 寫進權重登錄簿。**必須在鎖外**——資料庫可能是網路上的 PostgreSQL，在
        # EVAL_JOBS_LOCK 內等待網路往返會讓所有輪詢請求跟著卡住。
        # record_evaluation() 自己吞掉所有例外：登錄簿失敗不該讓一場跑了數分鐘、
        # 結果已經正確寫進 manifest 的評估被標成失敗。
        registry_service.record_evaluation(get_job(job_id) or {}, weight_sha)

    except DatasetUnavailable as exc:
        _fail(job_id, str(exc))
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        _fail(job_id, f"評估失敗：{exc}")
    finally:
        # 失敗路徑的保險網。成功路徑已在標記 done 之前清過，rmtree 是冪等的。
        _cleanup_extracted(resolved)


def _cleanup_extracted(resolved: Optional[ResolvedSplit]) -> None:
    """
    移除為了本次評估解壓出來的 split。

    只清 extracted=True 的來源——資料夾來源指向的是使用者自己的檔案，那裡一個位元組
    都不能動。
    """
    if resolved is None or not resolved.extracted:
        return
    # images_dir 是 <dest_root>/<split>/images，往上兩層即為本次解壓的根目錄
    shutil.rmtree(Path(resolved.images_dir).parent.parent, ignore_errors=True)


def _write_manifest(job_id: str) -> None:
    """讓完成的結果能跨重啟存活（圖表檔本來就在磁碟上）。"""
    with EVAL_JOBS_LOCK:
        job = EVAL_JOBS.get(job_id)
        if job is None or job.get("state") != "done":
            return
        payload = _job_public(job)
        payload["schema_version"] = JOB_SCHEMA_VERSION
        payload["plot_paths"] = job.get("plot_paths") or {}
        job_dir = Path(job["job_dir"])
    try:
        job_dir.mkdir(parents=True, exist_ok=True)
        with open(job_dir / "manifest.json", "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except OSError as exc:
        print(f"[EvaluationService] Could not write manifest for {job_id}: {exc}")


def _worker_loop() -> None:
    while True:
        job_id = _QUEUE.get()
        try:
            _process_job(job_id)
        except Exception as exc:  # 保險：worker 絕不能因單一 job 而終止
            print(f"[EvaluationService] Worker error on {job_id}: {exc}")
            traceback.print_exc()
        finally:
            _QUEUE.task_done()


def _ensure_worker() -> None:
    global _WORKER
    with _WORKER_LOCK:
        if _WORKER is None or not _WORKER.is_alive():
            _WORKER = threading.Thread(target=_worker_loop, name="eval-worker", daemon=True)
            _WORKER.start()


# --------------------------------------------------------------------------- #
# 提交與生命週期
# --------------------------------------------------------------------------- #

def _evict_finished_locked() -> None:
    """呼叫端必須已持有 EVAL_JOBS_LOCK。永不淘汰執行中的 job。"""
    finished = [
        (jid, j) for jid, j in EVAL_JOBS.items()
        if j.get("state") in ("done", "failed")
    ]
    while len(EVAL_JOBS) > MAX_EVAL_JOBS and finished:
        finished.sort(key=lambda kv: kv[1].get("created_at") or "")
        jid, job = finished.pop(0)
        EVAL_JOBS.pop(jid, None)
        shutil.rmtree(Path(job["job_dir"]), ignore_errors=True)


def sweep_expired() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=EVAL_JOB_TTL_HOURS)
    with EVAL_JOBS_LOCK:
        for jid in list(EVAL_JOBS):
            job = EVAL_JOBS[jid]
            if job.get("state") not in ("done", "failed"):
                continue
            created = job.get("created_at")
            try:
                if created and datetime.fromisoformat(created) < cutoff:
                    EVAL_JOBS.pop(jid, None)
                    shutil.rmtree(Path(job["job_dir"]), ignore_errors=True)
            except ValueError:
                continue


def submit_evaluation(session: Dict[str, Any], dataset: Dict[str, Any], split: str) -> Dict[str, Any]:
    """
    建立並排入一個評估 job。佇列滿時拋 queue.Full。

    呼叫端需先確認 session 是 YOLO 架構、dataset 可解析。
    """
    sweep_expired()

    job_id = f"eval_{uuid.uuid4().hex[:8]}"
    job = {
        "job_id": job_id,
        "session_id": session.get("session_id"),
        "session_name": session.get("custom_name") or session.get("session_id") or "model",
        "weight_sha256": None,
        "dataset_id": dataset.get("dataset_id"),
        "dataset_name": dataset.get("zip_name") or dataset.get("dataset_id"),
        "dataset_format": dataset.get("format"),
        "split": split,
        "state": "queued",
        "stage": "queued",
        "message": None,
        "created_at": _now_iso(),
        "started_at": None,
        "finished_at": None,
        "elapsed_seconds": None,
        "image_count": None,
        "vocab_check": None,
        "overall": None,
        "micro": None,
        "per_class": None,
        "size_profile": None,
        "speed_ms": None,
        "plot_paths": None,
        "plot_urls": None,
        "source_weights": session.get("weights_path"),
        "job_dir": str(EVAL_DIR / job_id),
        "log_tail": deque(maxlen=LOG_TAIL_MAXLEN),
        "_dataset_stats": dataset,
    }

    with EVAL_JOBS_LOCK:
        EVAL_JOBS[job_id] = job
        _evict_finished_locked()

    try:
        _QUEUE.put_nowait(job_id)
    except queue.Full:
        with EVAL_JOBS_LOCK:
            EVAL_JOBS.pop(job_id, None)
        raise

    _ensure_worker()
    return _job_public(job)


def delete_job(job_id: str) -> bool:
    with EVAL_JOBS_LOCK:
        job = EVAL_JOBS.pop(job_id, None)
    if job is None:
        return False
    shutil.rmtree(Path(job["job_dir"]), ignore_errors=True)
    return True


def plot_path(job_id: str, key: str) -> Optional[str]:
    """回傳圖表的實體路徑，並確認它確實落在該 job 的目錄內。"""
    with EVAL_JOBS_LOCK:
        job = EVAL_JOBS.get(job_id)
        if job is None:
            return None
        path = (job.get("plot_paths") or {}).get(key)
        job_dir = job["job_dir"]
    if not path:
        return None
    try:
        base = os.path.realpath(job_dir)
        target = os.path.realpath(path)
        if os.path.commonpath([base, target]) != base:
            return None
    except ValueError:
        return None
    return target if os.path.exists(target) else None


def load_jobs_from_disk() -> None:
    """
    啟動時還原已完成的評估結果。

    **刻意不比照 export_service 的孤兒清除邏輯去過濾「來源 session 已消失」的紀錄。**
    匯出產物只有搭配該 session 的下載連結才有意義，但評估結果是一次**測量**：指標、
    逐類別拆解與圖表本身就是完整的資訊，不需要模型還在記憶體裡也能解讀。

    而且在這個專案裡那個過濾等於「永遠刪光」——絕大多數 session 來自 LocalLibrary
    掃描，依設計不落地持久化，重啟後 session id 必然不存在。一次評估要跑數分鐘，
    因為模型沒被重新載入就把測量結果丟掉是不能接受的。

    只還原 state 為 done 且 manifest 完整的紀錄。
    """
    if not EVAL_DIR.exists():
        return
    for entry in sorted(EVAL_DIR.iterdir()):
        manifest = entry / "manifest.json"
        if not entry.is_dir() or not manifest.exists():
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
        payload["log_tail"] = deque(payload.get("log_tail") or [], maxlen=LOG_TAIL_MAXLEN)
        payload["_dataset_stats"] = {}
        with EVAL_JOBS_LOCK:
            EVAL_JOBS[job_id] = payload

    # 補寫登錄簿。用途是自我修復：評估完成當下若資料庫剛好不可用（容器還在暖機、
    # 或使用者根本沒開 DB），那筆指標就只存在於 manifest 裡。下次啟動時補進去。
    # record_evaluation() 以 job_id 做 upsert，已入帳的重複呼叫不會產生第二列。
    with EVAL_JOBS_LOCK:
        pending = [
            (dict(job), job.get("weight_sha256"))
            for job in EVAL_JOBS.values()
            if job.get("weight_sha256")
        ]
    for job, sha in pending:
        registry_service.record_evaluation(job, sha)

    print(f"[EvaluationService] Restored {len(EVAL_JOBS)} evaluation result(s)")
