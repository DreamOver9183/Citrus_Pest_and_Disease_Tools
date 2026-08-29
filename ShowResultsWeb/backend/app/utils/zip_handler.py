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

def peek_yolo_runs_in_zip(zip_path: str) -> list:
    """
    列出 ZIP 內的 YOLO 訓練 run，**完全不解壓縮**。

    只讀中央目錄的檔名清單，加上每個 run 的 args.yaml / results.csv 兩個小文字檔。
    用於 LocalLibrary 掃描的「探索」階段：使用者需要在決定要不要載入之前，先看到
    ZIP 裡到底有哪些 run 以及各自的 epochs/指標。

    判定條件與目錄版本一致（weights/best.pt + args.yaml 同層），因此同一個訓練成果
    無論以資料夾或 ZIP 的形式放進 LocalLibrary，看到的清單都相同。

    回傳的 dict 帶 inner_dir（run 在 ZIP 內的相對路徑），供之後解壓後定位同一個 run。
    """
    runs = []
    try:
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            names = set(zip_ref.namelist())

            for name in sorted(names):
                if not name.endswith("weights/best.pt"):
                    continue
                # "<run>/weights/best.pt" -> "<run>"；根層的 "weights/best.pt" -> ""
                run_dir = name[: -len("weights/best.pt")].rstrip("/")
                args_name = f"{run_dir}/args.yaml" if run_dir else "args.yaml"
                if args_name not in names:
                    continue

                hyperparams = {}
                try:
                    # 上限保護：args.yaml 正常只有數 KB，惡意壓縮檔不該能撐爆記憶體
                    with zip_ref.open(args_name) as f:
                        hyperparams = yaml.safe_load(f.read(1024 * 1024)) or {}
                except Exception as e:
                    print(f"[zip_handler] Error reading {args_name} in {zip_path}: {e}")

                metrics = {}
                results_name = f"{run_dir}/results.csv" if run_dir else "results.csv"
                if results_name in names:
                    try:
                        with zip_ref.open(results_name) as f:
                            text = f.read(4 * 1024 * 1024).decode("utf-8", errors="replace")
                        lines = [line.strip() for line in text.splitlines() if line.strip()]
                        if len(lines) > 1:
                            headers = [h.strip() for h in lines[0].split(",")]
                            last_values = [v.strip() for v in lines[-1].split(",")]
                            for h, v in zip(headers, last_values):
                                metrics[h.replace("metrics/", "").replace("(B)", "").strip()] = v
                    except Exception as e:
                        print(f"[zip_handler] Error parsing {results_name} in {zip_path}: {e}")

                runs.append({
                    "inner_dir": run_dir,
                    "name": os.path.basename(run_dir) or os.path.splitext(os.path.basename(zip_path))[0],
                    "weights_size_mb": round(zip_ref.getinfo(name).file_size / (1024 * 1024), 2),
                    "epochs": hyperparams.get("epochs", "N/A"),
                    "optimizer": hyperparams.get("optimizer", "N/A"),
                    "model_cfg": hyperparams.get("model", ""),
                    "metrics_summary": metrics,
                    # 完整 args.yaml，供權重登錄簿記錄（見 dir_handler 的同名欄位）
                    "hyperparameters": hyperparams,
                })
    except zipfile.BadZipFile:
        return []
    except OSError as e:
        print(f"[zip_handler] Error opening {zip_path}: {e}")
        return []

    return runs


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
        "hyperparameters": {},
        "results_png": None,
        "confusion_matrix": None
    }
