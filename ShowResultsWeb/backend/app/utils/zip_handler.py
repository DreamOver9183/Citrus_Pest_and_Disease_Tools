import os
import zipfile
import yaml

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
        
    found_runs = []
    
    # 遞迴遍歷解壓目錄，尋找所有包含 weights/best.pt 與 args.yaml 的 YOLO 訓練子目錄
    for root, dirs, files in os.walk(extract_to):
        if "weights" in dirs and "args.yaml" in files:
            best_pt_path = os.path.join(root, "weights", "best.pt")
            if os.path.exists(best_pt_path):
                # 讀取 args.yaml 中的超參數
                args_path = os.path.join(root, "args.yaml")
                hyperparams = {}
                try:
                    with open(args_path, "r", encoding="utf-8") as f:
                        hyperparams = yaml.safe_load(f) or {}
                except Exception as e:
                    print(f"[zip_handler] Error reading args.yaml at {args_path}: {e}")
                
                # 計算權重檔案大小 (MB)
                weight_size_mb = round(os.path.getsize(best_pt_path) / (1024 * 1024), 2)
                
                # 取得相關超參數
                epochs = hyperparams.get("epochs", "N/A")
                optimizer = hyperparams.get("optimizer", "N/A")
                model_name_cfg = hyperparams.get("model", "")
                
                # 讀取 results.csv 的最後一行取得最終驗證指標數據
                results_csv = os.path.join(root, "results.csv")
                metrics = {}
                if os.path.exists(results_csv):
                    try:
                        with open(results_csv, "r", encoding="utf-8") as f:
                            lines = [line.strip() for line in f.readlines() if line.strip()]
                            if len(lines) > 1:
                                headers = [h.strip() for h in lines[0].split(",")]
                                last_values = [v.strip() for v in lines[-1].split(",")]
                                for h, v in zip(headers, last_values):
                                    cleaned_header = h.replace("metrics/", "").replace("(B)", "").strip()
                                    metrics[cleaned_header] = v
                    except Exception as e:
                        print(f"[zip_handler] Error parsing results.csv at {results_csv}: {e}")
                
                # 取得 results.png 與 confusion_matrix.png 的實體路徑
                results_png = os.path.join(root, "results.png").replace("\\", "/")
                confusion_matrix = os.path.join(root, "confusion_matrix.png").replace("\\", "/")
                
                # 蒐集此模型實體規格
                found_runs.append({
                    "dir_path": root.replace("\\", "/"),
                    "weights_path": best_pt_path.replace("\\", "/"),
                    "weights_size_mb": weight_size_mb,
                    "epochs": epochs,
                    "optimizer": optimizer,
                    "model_cfg": model_name_cfg,
                    "metrics_summary": metrics,
                    "results_png": results_png if os.path.exists(results_png) else None,
                    "confusion_matrix": confusion_matrix if os.path.exists(confusion_matrix) else None
                })
                
    return found_runs

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
