import os
import zipfile
import yaml

from app.utils.dir_handler import index_yolo_runs_in_dir

class ZipIndexError(Exception):
    """Raised when a ZIP archive cannot be extracted or indexed safely."""


def is_member_within(base_dir: str, member_name: str) -> bool:
    """
    判斷 ZIP 成員解出後是否仍落在 base_dir 之內（路徑穿越防禦的共用述詞）。

    成員本身即等於 base_dir（例如目錄項目 "./"）視為安全。
    Windows 絕對路徑（如 "C:/evil"）亦會被擋下，因為 os.path.join 會捨棄 base。
    """
    base_abs = os.path.abspath(base_dir)
    member_path = os.path.abspath(os.path.join(base_dir, member_name))
    if member_path == base_abs:
        return True
    return member_path.startswith(base_abs + os.sep)


def _safe_extract(zip_ref: zipfile.ZipFile, extract_to: str) -> None:
    """Prevent path traversal entries from escaping the target directory."""
    for member in zip_ref.infolist():
        if not is_member_within(extract_to, member.filename):
            raise ZipIndexError(f"ZIP 檔包含不安全路徑: {member.filename}")
    zip_ref.extractall(extract_to)

def extract_and_index(zip_path: str, extract_to: str):
    """
    解壓縮 ZIP 檔案到指定獨立目錄，並深層走訪以檢索所有有效的 YOLO 模型訓練目錄
    """
    os.makedirs(extract_to, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            _safe_extract(zip_ref, extract_to)
    except zipfile.BadZipFile as exc:
        raise ZipIndexError("ZIP 檔案損毀或格式不正確") from exc
    except ZipIndexError:
        raise
    except PermissionError as exc:
        raise ZipIndexError("解壓縮時缺少檔案存取權限") from exc
    except OSError as exc:
        raise ZipIndexError(f"解壓縮時發生系統錯誤: {exc}") from exc
        
    # 走訪與索引邏輯與 LocalLibrary 掃描共用同一份定義，避免兩處各自漂移
    return index_yolo_runs_in_dir(extract_to)

def index_single_weight(file_path: str, dest_dir: str) -> dict:
    """
    處理單一權重檔案的複製與 Session 資訊生成。
    回傳字典結構包含供 ACTIVE_SESSIONS 使用的元資料。
    """
    import shutil
    
    os.makedirs(dest_dir, exist_ok=True)
    safe_name = os.path.basename(file_path)
    
    # Ultralytics 嚴格檢查 PyTorch 權重必須為 .pt 副檔名
    if safe_name.lower().endswith(".pth"):
        safe_name = safe_name[:-4] + ".pt"
        
    dest_path = os.path.join(dest_dir, safe_name)
    
    # 若為同一個檔案則跳過複製（例如在 temp 已有，或本來就只產生在 dest_dir）
    if os.path.abspath(file_path) != os.path.abspath(dest_path):
        shutil.copy2(file_path, dest_path)
        
    weight_size_mb = round(os.path.getsize(dest_path) / (1024 * 1024), 2)
    
    return {
        "dir_path": dest_dir.replace("\\", "/"),
        "weights_path": dest_path.replace("\\", "/"),
        "weights_size_mb": weight_size_mb,
        "epochs": "N/A",
        "optimizer": "N/A",
        "model_cfg": "N/A",
        "metrics_summary": {},
        "results_png": None,
        "confusion_matrix": None
    }
