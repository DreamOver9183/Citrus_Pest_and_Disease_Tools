"""
LocalLibrary 的探索與註冊。

**掃描與註冊刻意分成兩個階段**，這是與第一版最重要的行為差異：

- `discover()` 純唯讀，列出資料夾裡所有能辨識的模型與資料集，不動 ACTIVE_SESSIONS
  也不動 ACTIVE_DATASETS。
- `register()` 只處理使用者實際勾選的項目。

第一版的「掃描即註冊」有兩個實務上的硬傷：`MAX_SESSIONS` 只有 3，資料夾裡若有 6 個
模型，使用者拿到的是前 3 個而非想要的那 3 個；而資料集分析只取全樹分數最高的一個根
目錄，多個資料集會被無聲地收斂成一個。分成兩階段之後，「找得到」與「要不要用」是兩件
獨立的事，上限只在註冊時才生效。

支援的來源形態（四種都會出現在同一份清單裡）：

| 形態 | 探索方式 | 註冊方式 |
|---|---|---|
| YOLO run 資料夾 | `index_yolo_runs_in_dir()` 遞迴走訪 | 就地引用，不複製 |
| 散落權重檔（頂層） | 副檔名比對 | 就地引用，不複製 |
| 訓練成果 ZIP | `peek_yolo_runs_in_zip()` 只讀中央目錄 | 解壓到 `LOCAL_LIBRARY_EXTRACT_DIR` |
| 資料集（資料夾或 ZIP） | `analyze_dataset()` 零解壓分析 | 直接沿用探索階段算好的統計 |

ZIP 是唯一需要寫入磁碟的形態——權重無法從壓縮檔內直接餵給 Ultralytics。落點在受管的
`extracted_runs/local_library/` 而非使用者的資料夾，所以「絕不寫入 LOCAL_LIBRARY_DIR」
的保證仍然成立。
"""
import hashlib
import os
import threading
import uuid
import zipfile
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import LOCAL_LIBRARY_EXTRACT_DIR, MAX_SESSIONS
from app.services.dataset_analyzer import analyze_dataset
from app.services.dataset_manager import ACTIVE_DATASETS, DATASETS_LOCK, register_dataset
from app.services.session_manager import ACTIVE_SESSIONS, SESSIONS_LOCK, save_sessions_to_disk
from app.utils.dataset_dir import DirArchiveReader
from app.utils.dataset_zip import ZipArchiveReader
from app.utils.dir_handler import index_single_weight_in_place, index_yolo_runs_in_dir
from app.utils.zip_handler import ZipIndexError, extract_and_index, peek_yolo_runs_in_zip

# 刻意與 sessions.py 各自維護一份。本專案沒有 router/service 互相 import 路由常數的
# 先例，小幅重複比引入新的耦合方向風險更低。
SUPPORTED_WEIGHT_EXTENSIONS = {".pt", ".pth", ".onnx", ".tflite", ".engine", ".torchscript"}
FORMAT_LABELS = {
    ".pt": "PyTorch",
    ".pth": "SSDLite-MobileNetV3 (PyTorch)",
    ".onnx": "ONNX",
    ".tflite": "TFLite",
    ".engine": "TensorRT",
    ".torchscript": "TorchScript",
}

# 上一次 discover() 的結果，供 register() 用 candidate_id 回查。
# 存的是完整記錄（含探索階段算好的資料集統計），因此註冊不需要重跑任何分析。
_CANDIDATES: Dict[str, dict] = {}
_CANDIDATES_LOCK = threading.RLock()


def resolved(path: str) -> str:
    """去重鍵：絕對路徑 + 大小寫正規化（Windows 上 C:/A 與 c:/a 是同一個檔案）。"""
    return os.path.normcase(os.path.abspath(path))


def _candidate_id(*parts: str) -> str:
    """由來源特徵推導的穩定 ID——同一份內容重新掃描會拿到同一個 ID。"""
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:12]


def _detect_arch(filename: str) -> str:
    """依原始檔名判斷架構，與 sessions.py 的判定規則一致。"""
    lower = filename.lower()
    if lower.endswith(".pth"):
        return "ssdlite_mobilenet_v3_small" if "small" in lower else "ssdlite_mobilenet_v3_large"
    return "yolo"


def _zip_extract_root(zip_path: str) -> str:
    """ZIP 的解壓落點，由路徑推導所以是決定性的（重複註冊不會產生第二份副本）。"""
    stem = os.path.splitext(os.path.basename(zip_path))[0]
    digest = hashlib.sha1(resolved(zip_path).encode("utf-8")).hexdigest()[:8]
    return os.path.join(str(LOCAL_LIBRARY_EXTRACT_DIR), f"{stem}_{digest}")


def _registered_weight_keys() -> set:
    with SESSIONS_LOCK:
        return {
            resolved(s["weights_path"]) for s in ACTIVE_SESSIONS.values() if s.get("weights_path")
        }


def _registered_dataset_keys() -> set:
    with DATASETS_LOCK:
        return {
            resolved(d["source_path"]) for d in ACTIVE_DATASETS.values() if d.get("source_path")
        }


def _metric_hint(metrics: dict) -> str:
    """從 results.csv 的最後一列挑一個有代表性的指標做為清單上的說明文字。"""
    for key in ("mAP50", "mAP50-95", "precision", "recall"):
        value = metrics.get(key)
        if value:
            try:
                return f"{key} {float(value):.3f}"
            except (TypeError, ValueError):
                return f"{key} {value}"
    return ""


def _model_detail(epochs: Any, metrics: dict) -> str:
    bits = []
    if epochs not in (None, "", "N/A"):
        bits.append(f"{epochs} epochs")
    hint = _metric_hint(metrics or {})
    if hint:
        bits.append(hint)
    return " · ".join(bits) or "無訓練指標"


def _dataset_detail(stats: dict) -> str:
    fmt = str(stats.get("format", "")).upper() or "未知"
    return (
        f"{fmt} · {stats.get('total_images', 0):,} 張影像 · "
        f"{stats.get('total_annotations', 0):,} 個標註"
    )


# --------------------------------------------------------------------------- 探索


def _discover_models(root: str) -> List[dict]:
    found: List[dict] = []

    # 1) 訓練 run 資料夾（遞迴）
    for run in index_yolo_runs_in_dir(root):
        found.append({
            "candidate_id": _candidate_id("run_dir", resolved(run["weights_path"])),
            "kind": "model",
            "source_kind": "run_dir",
            "name": os.path.basename(run["dir_path"]) or "run",
            "rel_path": os.path.relpath(run["dir_path"], root).replace("\\", "/"),
            "size_mb": run["weights_size_mb"],
            "detail": _model_detail(run.get("epochs"), run.get("metrics_summary")),
            "_weights_key": resolved(run["weights_path"]),
            "_run": run,
        })

    try:
        top_level = sorted(os.listdir(root))
    except OSError:
        top_level = []

    for entry in top_level:
        entry_path = os.path.join(root, entry)
        if not os.path.isfile(entry_path):
            continue
        ext = os.path.splitext(entry)[1].lower()

        # 2) 頂層散落權重檔。不遞迴是刻意的——避免把 run 資料夾內的 weights/last.pt
        #    誤判成另一個獨立權重檔。
        if ext in SUPPORTED_WEIGHT_EXTENSIONS:
            found.append({
                "candidate_id": _candidate_id("weight_file", resolved(entry_path)),
                "kind": "model",
                "source_kind": "weight_file",
                "name": entry,
                "rel_path": entry,
                "size_mb": round(os.path.getsize(entry_path) / (1024 * 1024), 2),
                "detail": FORMAT_LABELS.get(ext, ext.upper()),
                "_weights_key": resolved(entry_path),
                "_path": entry_path,
                "_ext": ext,
            })
            continue

        # 3) 訓練成果 ZIP：只讀中央目錄，一個 run 一個候選項
        if ext == ".zip":
            extract_root = _zip_extract_root(entry_path)
            for run in peek_yolo_runs_in_zip(entry_path):
                inner = run["inner_dir"]
                future_weights = os.path.join(
                    extract_root, *(inner.split("/") if inner else []), "weights", "best.pt"
                )
                found.append({
                    "candidate_id": _candidate_id("zip_run", resolved(entry_path), inner),
                    "kind": "model",
                    "source_kind": "zip_run",
                    "name": run["name"],
                    "rel_path": f"{entry} › {inner}" if inner else entry,
                    "size_mb": run["weights_size_mb"],
                    "detail": _model_detail(run.get("epochs"), run.get("metrics_summary")),
                    # 解壓落點是決定性的，所以「是否已註冊」在解壓前就能算出來
                    "_weights_key": resolved(future_weights),
                    "_zip_path": entry_path,
                    "_inner_dir": inner,
                })

    return found


def _probe_dataset(reader, label: str, source_path: str, size_mb: Optional[float]) -> Optional[dict]:
    """對單一來源跑一次零解壓分析；辨識不出資料集不算錯誤，回 None。"""
    try:
        stats = analyze_dataset(reader, zip_name=label, zip_size_bytes=None)
    except ZipIndexError:
        return None
    except Exception as exc:  # noqa: BLE001 - 單一來源失敗不得中斷整體掃描
        print(f"[LibraryScanner] Dataset probe failed for {source_path}: {exc}")
        return None

    prefix = stats.get("root_prefix") or ""
    detected_root = os.path.join(source_path, *prefix.rstrip("/").split("/")) if prefix else source_path
    return {
        "stats": stats,
        "detected_root": detected_root,
        "size_mb": size_mb,
    }


def _discover_datasets(root: str) -> List[dict]:
    found: List[dict] = []
    seen_roots: set = set()

    def add(probe: Optional[dict], source_kind: str, name: str, rel_path: str, container: str):
        if probe is None:
            return
        key = resolved(probe["detected_root"])
        # 同一個資料集可能同時被「根目錄整棵樹」與「該子目錄自己」偵測到，取先到者
        if key in seen_roots:
            return
        seen_roots.add(key)

        stats = probe["stats"]
        found.append({
            "candidate_id": _candidate_id("dataset", source_kind, key),
            "kind": "dataset",
            "source_kind": source_kind,
            "name": name,
            "rel_path": rel_path,
            "size_mb": probe["size_mb"],
            "detail": _dataset_detail(stats),
            "_dataset_key": key,
            "_detected_root": probe["detected_root"],
            "_container": container,
            "_stats": stats,
        })

    try:
        top_level = sorted(os.listdir(root))
    except OSError:
        top_level = []

    # 1) 每個頂層子資料夾各自探測一次。逐個探測而非只對整棵樹跑一次，是為了讓多個
    #    並存的資料集都能各自現身——全樹單次分析只會回報分數最高的那一個。
    for entry in top_level:
        entry_path = os.path.join(root, entry)
        if os.path.isdir(entry_path):
            add(
                _probe_dataset(DirArchiveReader(entry_path), entry, entry_path, None),
                "dataset_dir", entry, entry, entry_path,
            )
            continue

        # 2) 資料集 ZIP：零解壓分析，與上傳路徑走完全相同的程式碼
        if os.path.splitext(entry)[1].lower() != ".zip":
            continue
        size_bytes = os.path.getsize(entry_path)
        try:
            with zipfile.ZipFile(entry_path) as zip_ref:
                probe = _probe_dataset(
                    ZipArchiveReader(zip_ref, zip_size_bytes=size_bytes),
                    entry, entry_path, round(size_bytes / (1024 * 1024), 2),
                )
        except (zipfile.BadZipFile, OSError):
            continue
        add(probe, "dataset_zip", entry, entry, entry_path)

    # 3) 最後才探測根目錄本身，涵蓋「使用者把 data.yaml 與 train/ 直接丟在頂層」。
    #    放最後是因為子目錄的判定更精確，先到者優先。
    add(
        _probe_dataset(DirArchiveReader(root), os.path.basename(root) or "LocalLibrary", root, None),
        "dataset_dir", os.path.basename(root) or "LocalLibrary", ".", root,
    )

    return found


def discover(root: str) -> List[dict]:
    """列出資料夾內所有可辨識的模型與資料集。純唯讀，不註冊任何東西。"""
    candidates = _discover_models(root) + _discover_datasets(root)

    weight_keys = _registered_weight_keys()
    dataset_keys = _registered_dataset_keys()
    for candidate in candidates:
        key = candidate.get("_weights_key") or candidate.get("_dataset_key")
        candidate["already_registered"] = key in (
            weight_keys if candidate["kind"] == "model" else dataset_keys
        )

    with _CANDIDATES_LOCK:
        _CANDIDATES.clear()
        _CANDIDATES.update({c["candidate_id"]: c for c in candidates})

    return candidates


def public_view(candidate: dict) -> dict:
    """只把前端需要的欄位送出去，內部欄位（統計快取、絕對路徑）留在後端。"""
    return {k: v for k, v in candidate.items() if not k.startswith("_")}


# --------------------------------------------------------------------------- 註冊


def _ensure_zip_extracted(zip_path: str) -> List[dict]:
    """把 ZIP 解到受管目錄並索引其中的 run。同一個 ZIP 只解一次。"""
    extract_root = _zip_extract_root(zip_path)
    if os.path.isdir(extract_root) and os.listdir(extract_root):
        return index_yolo_runs_in_dir(extract_root)
    return extract_and_index(zip_path, extract_root)


def _register_model(candidate: dict) -> Optional[dict]:
    """回傳要寫進 ACTIVE_SESSIONS 的記錄；無法註冊則回 None。"""
    kind = candidate["source_kind"]

    if kind == "run_dir":
        run = candidate["_run"]
        folder = candidate["name"]
        return {
            # 任何非 "single_weight" 的值都會讓前端顯示 "Runs Log" 徽章，這正是我們要的
            "source_type": "local_library_run",
            "zip_name": folder,
            "format_label": "本機資料夾",
            "model_arch": "yolo",
            "custom_name": f"{folder}（本機）",
            **run,
        }

    if kind == "weight_file":
        filename = candidate["name"]
        ext = candidate["_ext"]
        return {
            # 必須是這個字面值：ModelMetricCard 用精確比對決定 "Weight Only" 徽章
            "source_type": "single_weight",
            "zip_name": filename,
            "format_label": FORMAT_LABELS.get(ext, ext.upper()),
            "model_arch": _detect_arch(filename),
            "custom_name": f"{os.path.splitext(filename)[0]}（本機）",
            **index_single_weight_in_place(candidate["_path"]),
        }

    if kind == "zip_run":
        runs = _ensure_zip_extracted(candidate["_zip_path"])
        target = candidate["_weights_key"]
        run = next((r for r in runs if resolved(r["weights_path"]) == target), None)
        if run is None:
            return None
        folder = candidate["name"]
        return {
            "source_type": "local_library_run",
            "zip_name": os.path.basename(candidate["_zip_path"]),
            "format_label": "本機 ZIP",
            "model_arch": "yolo",
            "custom_name": f"{folder}（本機）",
            **run,
        }

    return None


def register(candidate_ids: List[str]) -> Dict[str, Any]:
    """
    註冊使用者勾選的候選項。

    模型與資料集彼此獨立：任一邊失敗都不該連累另一邊，因此每個項目各自 try/except。
    """
    with _CANDIDATES_LOCK:
        selected = [_CANDIDATES[cid] for cid in candidate_ids if cid in _CANDIDATES]
        unknown = [cid for cid in candidate_ids if cid not in _CANDIDATES]

    registered_sessions: List[str] = []
    registered_datasets: List[str] = []
    skipped = 0
    capped = False
    failed: List[str] = []

    for candidate in selected:
        if candidate["kind"] != "model":
            continue
        try:
            if candidate["_weights_key"] in _registered_weight_keys():
                skipped += 1
                continue
            with SESSIONS_LOCK:
                if len(ACTIVE_SESSIONS) >= MAX_SESSIONS:
                    capped = True
                    break
            record = _register_model(candidate)
            if record is None:
                failed.append(candidate["name"])
                continue

            session_id = f"run_{uuid.uuid4().hex[:8]}"
            with SESSIONS_LOCK:
                ACTIVE_SESSIONS[session_id] = {
                    "metrics_csv_path": None,
                    **record,
                    # session_id 與 source 放在 record 之後展開，確保不會被來源資料覆寫
                    "session_id": session_id,
                    "source": "local_library",
                }
            registered_sessions.append(session_id)
        except Exception as exc:  # noqa: BLE001
            print(f"[LibraryScanner] Failed to register model {candidate['name']}: {exc}")
            failed.append(candidate["name"])

    for candidate in selected:
        if candidate["kind"] != "dataset":
            continue
        try:
            if candidate["_dataset_key"] in _registered_dataset_keys():
                skipped += 1
                continue
            # 探索階段已經算好統計，這裡不需要重跑任何分析
            stats = dict(candidate["_stats"])
            stats["source_path"] = candidate["_dataset_key"]
            stats["zip_name"] = candidate["name"]
            # source_path 是「資料夾路徑 + 內層前綴」黏成的去重鍵，且經過 normcase，
            # 對 ZIP 來源（…/foo.zip/inner）根本不是可開啟的路徑。額外記下容器本身與
            # 內層前綴，讓後續要真正讀取檔案的功能（驗證評估）不必反解字串。
            stats["source_container"] = candidate["_container"]
            stats["source_inner_prefix"] = (stats.get("root_prefix") or "").strip("/")
            register_dataset(stats)
            registered_datasets.append(stats["dataset_id"])
        except Exception as exc:  # noqa: BLE001
            print(f"[LibraryScanner] Failed to register dataset {candidate['name']}: {exc}")
            failed.append(candidate["name"])

    if registered_sessions:
        save_sessions_to_disk()

    return {
        "registered_sessions": registered_sessions,
        "registered_datasets": registered_datasets,
        "skipped": skipped,
        "capped": capped,
        "failed": failed,
        "unknown": unknown,
    }
