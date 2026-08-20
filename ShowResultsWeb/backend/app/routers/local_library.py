"""
本機資料夾掃描。

使用者用作業系統的檔案總管把訓練成果／資料集放進 LOCAL_LIBRARY_DIR，再按下
掃描按鈕。後端就地讀取，不複製任何位元組，也不需要任何上傳流量。

為什麼是「固定目錄」而不是讓使用者輸入路徑：瀏覽器基於安全機制，永遠不會把
使用者選取的資料夾轉成可用的絕對路徑字串（showDirectoryPicker() 只給檔案控制代碼
與資料夾名稱）。固定目錄讓路徑完全不需要經過瀏覽器，同時也讓 Docker 支援退化成
一條普通的 bind mount。

**本模組只讀不寫**：註冊的 session/dataset 都是就地引用；刪除它們也只會移除
記憶體中的紀錄（session_manager.delete_session 的目錄清理被 "extracted_runs"
子字串條件擋住，LocalLibrary 路徑不會命中）。
"""
import os
import threading
import uuid
from typing import Any, Dict, List, Optional, Tuple, Union

from fastapi import APIRouter

from app.core.config import LOCAL_LIBRARY_DIR, MAX_SESSIONS
from app.schemas import ErrorResponse, LocalLibraryInfoResponse, LocalLibraryScanResponse
from app.services.dataset_analyzer import analyze_dataset
from app.services.dataset_manager import ACTIVE_DATASETS, DATASETS_LOCK, register_dataset
from app.services.session_manager import ACTIVE_SESSIONS, SESSIONS_LOCK, save_sessions_to_disk
from app.utils.dataset_dir import DirArchiveReader
from app.utils.dir_handler import index_single_weight_in_place, index_yolo_runs_in_dir
from app.utils.zip_handler import ZipIndexError

router = APIRouter()

# 一次只允許一個掃描：走訪大型資料夾是重度 I/O，與 datasets.py 的分析同理。
_SCAN_SEMAPHORE = threading.BoundedSemaphore(1)

# 刻意與 sessions.py 各自維護一份。本專案沒有 router 互相 import 的先例，
# 小幅重複比引入新的耦合方向風險更低。
SUPPORTED_WEIGHT_EXTENSIONS = {".pt", ".pth", ".onnx", ".tflite", ".engine", ".torchscript"}
FORMAT_LABELS = {
    ".pt": "PyTorch",
    ".pth": "SSDLite-MobileNetV3 (PyTorch)",
    ".onnx": "ONNX",
    ".tflite": "TFLite",
    ".engine": "TensorRT",
    ".torchscript": "TorchScript",
}


def _resolved(path: str) -> str:
    """去重鍵：絕對路徑 + 大小寫正規化（Windows 上 C:/A 與 c:/a 是同一個檔案）。"""
    return os.path.normcase(os.path.abspath(path))


def _detect_arch(filename: str) -> str:
    """依原始檔名判斷架構，與 sessions.py 的判定規則一致。"""
    if filename.lower().endswith(".pth"):
        return "ssdlite_mobilenet_v3_small" if "small" in filename.lower() else "ssdlite_mobilenet_v3_large"
    return "yolo"


def _existing_weight_keys() -> set:
    """呼叫端必須已持有 SESSIONS_LOCK。"""
    return {
        _resolved(s["weights_path"])
        for s in ACTIVE_SESSIONS.values()
        if s.get("weights_path")
    }


def _scan_models(root: str) -> Tuple[List[str], int, bool]:
    """
    註冊 root 底下的 YOLO run 資料夾與頂層散落權重檔。

    回傳 (新註冊的 session_id 清單, 略過數, 是否因達上限而中止)。
    """
    registered: List[str] = []
    skipped = 0
    capped = False

    found_runs = index_yolo_runs_in_dir(root)

    with SESSIONS_LOCK:
        existing = _existing_weight_keys()

        # 1) 訓練 run 資料夾
        for run in found_runs:
            key = _resolved(run["weights_path"])
            if key in existing:
                skipped += 1
                continue
            if len(ACTIVE_SESSIONS) >= MAX_SESSIONS:
                capped = True
                break

            session_id = f"run_{uuid.uuid4().hex[:8]}"
            folder_name = os.path.basename(run["dir_path"]) or "run"
            ACTIVE_SESSIONS[session_id] = {
                "session_id": session_id,
                "zip_name": folder_name,
                # 任何非 "single_weight" 的值都會讓前端顯示 "Runs Log" 徽章，這正是我們要的
                "source_type": "local_library_run",
                "format_label": "本機資料夾",
                "model_arch": "yolo",
                "custom_name": f"{folder_name}（本機）",
                "metrics_csv_path": None,
                "source": "local_library",
                **run,
            }
            existing.add(key)
            registered.append(session_id)

        # 2) 頂層散落權重檔（不遞迴——避免把 run 資料夾內的 weights/last.pt
        #    誤判成另一個獨立權重檔）
        if not capped:
            try:
                top_level = sorted(
                    entry for entry in os.listdir(root)
                    if os.path.isfile(os.path.join(root, entry))
                )
            except OSError:
                top_level = []

            for filename in top_level:
                ext = os.path.splitext(filename)[1].lower()
                if ext not in SUPPORTED_WEIGHT_EXTENSIONS:
                    continue

                file_path = os.path.join(root, filename)
                key = _resolved(file_path)
                if key in existing:
                    skipped += 1
                    continue
                if len(ACTIVE_SESSIONS) >= MAX_SESSIONS:
                    capped = True
                    break

                info = index_single_weight_in_place(file_path)
                session_id = f"run_{uuid.uuid4().hex[:8]}"
                format_label = FORMAT_LABELS.get(ext, ext.upper())
                ACTIVE_SESSIONS[session_id] = {
                    "session_id": session_id,
                    "zip_name": filename,
                    # 必須是這個字面值：ModelMetricCard 用精確比對決定 "Weight Only" 徽章
                    "source_type": "single_weight",
                    "format_label": format_label,
                    "model_arch": _detect_arch(filename),
                    "custom_name": f"{os.path.splitext(filename)[0]}（本機）",
                    "metrics_csv_path": None,
                    "source": "local_library",
                    **info,
                }
                existing.add(key)
                registered.append(session_id)

    if registered:
        save_sessions_to_disk()
    return registered, skipped, capped


def _scan_dataset(root: str) -> Tuple[Optional[str], int]:
    """
    對整棵樹跑一次資料集偵測與分析。

    回傳 (新註冊的 dataset_id 或 None, 略過數)。找不到可辨識的資料集不算錯誤——
    這是混合內容的掃描，資料夾裡可能就是只有模型。
    """
    try:
        stats = analyze_dataset(DirArchiveReader(root), zip_name=os.path.basename(root), zip_size_bytes=None)
    except ZipIndexError:
        return None, 0
    except Exception as exc:  # noqa: BLE001 - 資料集偵測失敗不得影響已註冊的模型
        print(f"[LocalLibrary] Dataset analysis failed: {exc}")
        return None, 0

    detected_root = os.path.join(root, stats["root_prefix"].rstrip("/")) if stats["root_prefix"] else root
    stats["source_path"] = _resolved(detected_root)
    stats["zip_name"] = os.path.basename(detected_root.rstrip(os.sep)) or os.path.basename(root)

    with DATASETS_LOCK:
        duplicate = any(
            _resolved(d["source_path"]) == stats["source_path"]
            for d in ACTIVE_DATASETS.values()
            if d.get("source_path")
        )
    if duplicate:
        return None, 1

    register_dataset(stats)
    return stats["dataset_id"], 0


# 路由順序無關緊要（兩條路徑都是字面值，沒有 path parameter），
# 但仍維持「唯讀查詢在前、動作在後」的可讀性慣例。
@router.get("/local-library", response_model=LocalLibraryInfoResponse, response_model_exclude_unset=True)
def get_local_library_info():
    """回傳資料夾的絕對路徑供 UI 顯示。純唯讀，不會註冊任何東西。"""
    return {
        "status": "success",
        "path": str(LOCAL_LIBRARY_DIR).replace("\\", "/"),
        "exists": LOCAL_LIBRARY_DIR.exists(),
    }


@router.post(
    "/local-library/scan",
    response_model=Union[LocalLibraryScanResponse, ErrorResponse],
    response_model_exclude_unset=True,
)
def scan_local_library():
    """
    掃描本機資料夾並註冊找到的模型與資料集。

    不接受任何請求參數——掃描目標永遠是伺服器端設定好的 LOCAL_LIBRARY_DIR，
    路徑完全不經過瀏覽器。
    """
    if not LOCAL_LIBRARY_DIR.exists():
        return {
            "status": "error",
            "message": f"找不到本機資料夾：{LOCAL_LIBRARY_DIR}。請先建立此資料夾並放入模型或資料集。",
        }

    if not _SCAN_SEMAPHORE.acquire(blocking=False):
        return {"status": "error", "message": "目前已有掃描正在進行中，請稍候再試"}

    try:
        root = str(LOCAL_LIBRARY_DIR)

        # 模型與資料集彼此獨立：任一邊失敗都不該連累另一邊
        registered_sessions, skipped_sessions, capped = _scan_models(root)
        dataset_id, skipped_datasets = _scan_dataset(root)
        registered_datasets = [dataset_id] if dataset_id else []

        parts = []
        if registered_sessions:
            parts.append(f"新增 {len(registered_sessions)} 個模型")
        if registered_datasets:
            parts.append(f"新增 {len(registered_datasets)} 個資料集")
        skipped_total = skipped_sessions + skipped_datasets
        if skipped_total:
            parts.append(f"{skipped_total} 筆已存在略過")
        if capped:
            parts.append(f"已達模型數量上限（{MAX_SESSIONS}）")
        if not parts:
            parts.append("未找到可辨識的模型或資料集")

        with SESSIONS_LOCK:
            sessions_snapshot = dict(ACTIVE_SESSIONS)
        with DATASETS_LOCK:
            datasets_snapshot = dict(ACTIVE_DATASETS)

        return {
            "status": "success",
            "registered_sessions": registered_sessions,
            "registered_datasets": registered_datasets,
            "skipped_sessions": skipped_sessions,
            "skipped_datasets": skipped_datasets,
            "message": "；".join(parts),
            "sessions": sessions_snapshot,
            "datasets": datasets_snapshot,
        }
    finally:
        _SCAN_SEMAPHORE.release()
