"""
資料集分析結果的持久化。

刻意鏡射 session_manager 的四函式形狀（save / load / delete / 清理），但有一個
關鍵差異：**這裡不碰檔案系統上的資料集內容**。

分析採 stats-only 設計——ZIP 從未被解壓，磁碟上沒有任何與 dataset_id 對應的
目錄，因此 delete_dataset() 只是一個 dict 刪除。這一點必須維持：
session_manager.delete_session() 用字串切割從 dir_path 反推要刪的目錄，若把那套
邏輯套用在 extracted_runs/datasets/<id> 上，會算出 extracted_runs/datasets 並
rmtree 整個根目錄。test_delete_dataset_touches_no_filesystem 就是在釘住這件事。
"""
import json
import os
import threading
from typing import Any, Dict

from app.core.config import EXTRACTED_RUNS_DIR, MAX_DATASETS

# dataset_id -> 統計 dict
ACTIVE_DATASETS: Dict[str, Dict[str, Any]] = {}
# 所有對 ACTIVE_DATASETS 的讀-改-寫都必須持有此鎖
DATASETS_LOCK = threading.RLock()

DATASETS_FILE = os.path.join(EXTRACTED_RUNS_DIR, "datasets.json")

# 與 dataset_analyzer.SCHEMA_VERSION 對應；不符的舊記錄在載入時丟棄
DATASET_SCHEMA_VERSION = 1


def _assert_within(base: str, target: str) -> bool:
    """
    以 commonpath 判斷 target 是否確實位於 base 之內。

    目前沒有呼叫點——stats-only 設計下沒有目錄要刪。保留它是為了：若日後加入
    縮圖預覽而需要選擇性解壓，能直接用這個正確的原語，而不會有人再用
    session_manager 那種字串切割重寫一次。
    """
    base_real = os.path.realpath(base)
    target_real = os.path.realpath(target)
    try:
        return os.path.commonpath([base_real, target_real]) == base_real
    except ValueError:
        # 不同磁碟機代號時 commonpath 會拋 ValueError，視為不在範圍內
        return False


def save_datasets_to_disk() -> None:
    try:
        os.makedirs(os.path.dirname(DATASETS_FILE), exist_ok=True)
        with DATASETS_LOCK:
            # 與 session 同理：有 source_path 就代表來自 LocalLibrary 掃描，不落地。
            # ZIP 分析出的資料集永遠沒有 source_path（它們沒有對應的實體目錄），
            # 因此這個條件本身就足以區分兩種來源，不需要額外的標記欄位。
            snapshot = {
                k: v for k, v in ACTIVE_DATASETS.items()
                if not v.get("source_path")
            }
        with open(DATASETS_FILE, "w", encoding="utf-8") as handle:
            json.dump(snapshot, handle, ensure_ascii=False, indent=2)
    except Exception as exc:
        print(f"[DatasetManager] Error saving datasets: {exc}")


def load_datasets_from_disk() -> None:
    """
    啟動時還原分析歷史。

    session_manager 的 ghost filter 靠「權重檔是否還在」判斷記錄是否有效；這裡沒有
    磁碟產物可檢查，改以 schema_version 相符為準，避免舊格式記錄讓前端解析失敗。
    """
    if not os.path.exists(DATASETS_FILE):
        return
    try:
        with open(DATASETS_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception as exc:
        print(f"[DatasetManager] Error loading datasets: {exc}")
        return

    restored = 0
    with DATASETS_LOCK:
        ACTIVE_DATASETS.clear()
        for dataset_id, stats in (data or {}).items():
            if not isinstance(stats, dict):
                continue
            if stats.get("schema_version") != DATASET_SCHEMA_VERSION:
                print(f"[DatasetManager] Skipping {dataset_id}: schema version mismatch")
                continue
            ACTIVE_DATASETS[dataset_id] = stats
            restored += 1
    print(f"[DatasetManager] Restored {restored} dataset analysis record(s)")


def register_dataset(stats: Dict[str, Any]) -> Dict[str, Any]:
    """寫入一筆分析結果並淘汰過舊的記錄，回傳當下的完整快照。"""
    dataset_id = stats["dataset_id"]
    with DATASETS_LOCK:
        ACTIVE_DATASETS[dataset_id] = stats
        _evict_oldest_locked()
        snapshot = dict(ACTIVE_DATASETS)
    save_datasets_to_disk()
    return snapshot


def _evict_oldest_locked() -> None:
    """必須在持有 DATASETS_LOCK 的情況下呼叫。"""
    if len(ACTIVE_DATASETS) <= MAX_DATASETS:
        return
    ordered = sorted(ACTIVE_DATASETS.items(), key=lambda kv: kv[1].get("created_at", ""))
    for dataset_id, _ in ordered[: len(ACTIVE_DATASETS) - MAX_DATASETS]:
        del ACTIVE_DATASETS[dataset_id]


def delete_dataset(dataset_id: str) -> Dict[str, Any]:
    """
    刪除一筆分析記錄。

    只動記憶體與 datasets.json，不觸碰檔案系統上的任何目錄——沒有東西可刪，
    因為分析從頭到尾沒有解壓過任何檔案。
    """
    with DATASETS_LOCK:
        if dataset_id not in ACTIVE_DATASETS:
            raise KeyError(dataset_id)
        del ACTIVE_DATASETS[dataset_id]
        snapshot = dict(ACTIVE_DATASETS)
    save_datasets_to_disk()
    return snapshot


def get_datasets_snapshot() -> Dict[str, Any]:
    with DATASETS_LOCK:
        return dict(ACTIVE_DATASETS)
