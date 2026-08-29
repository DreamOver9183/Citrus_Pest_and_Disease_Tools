"""
真實目錄的模型索引——zip_handler 的目錄對應版本。

zip_handler.extract_and_index() 的後半段（解壓縮之後、走訪 weights/args.yaml 的
那個迴圈）本來就只是純目錄操作，與 ZIP 無關。這裡把它抽成獨立函式，讓
「什麼樣的資料夾算是一個有效的 YOLO 訓練 run」只有一份定義——
extract_and_index() 現在也委派到這裡，兩條路徑不會各自漂移。

本模組**只讀不寫**：絕不複製、改名或刪除 root_path 底下的任何檔案。
這是它與 zip_handler.index_single_weight()（會 shutil.copy2 到受管目錄）
最根本的差異——LocalLibrary 的檔案屬於使用者，系統只做就地引用。
"""
import os

import yaml


def index_yolo_runs_in_dir(root_path: str) -> list:
    """
    遞迴走訪 root_path，找出所有有效的 YOLO 訓練 run 目錄。

    判定條件與 ZIP 上傳完全一致：某目錄同時有 weights/ 子目錄與 args.yaml，
    且 weights/best.pt 確實存在。

    回傳的 dict 形狀與 zip_handler.index_single_weight() 對齊，可直接餵給
    sessions 註冊邏輯。
    """
    found_runs = []

    for root, dirs, files in os.walk(root_path):
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
                    print(f"[dir_handler] Error reading args.yaml at {args_path}: {e}")

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
                        print(f"[dir_handler] Error parsing results.csv at {results_csv}: {e}")

                # 取得 results.png 與 confusion_matrix.png 的實體路徑
                results_png = os.path.join(root, "results.png").replace("\\", "/")
                confusion_matrix = os.path.join(root, "confusion_matrix.png").replace("\\", "/")

                # 蒐集此模型實體規格。
                # hyperparameters 帶的是**完整**的 args.yaml：上面那三個 get() 只挑了
                # 消融看板要顯示的欄位，其餘（lr0/mosaic/patience…）正是權重登錄簿要記的
                # 東西。這裡不重讀檔案，直接把已經 safe_load 出來的 dict 一併回傳。
                found_runs.append({
                    "dir_path": root.replace("\\", "/"),
                    "weights_path": best_pt_path.replace("\\", "/"),
                    "weights_size_mb": weight_size_mb,
                    "epochs": epochs,
                    "optimizer": optimizer,
                    "model_cfg": model_name_cfg,
                    "metrics_summary": metrics,
                    "hyperparameters": hyperparams,
                    "results_png": results_png if os.path.exists(results_png) else None,
                    "confusion_matrix": confusion_matrix if os.path.exists(confusion_matrix) else None
                })

    return found_runs


def index_single_weight_in_place(file_path: str) -> dict:
    """
    就地索引單一權重檔，不複製、不改名。

    與 zip_handler.index_single_weight() 的兩個關鍵差異：

    1. **不複製**：weights_path 直接指向使用者原本的檔案。系統對 LocalLibrary
       只有讀取權，複製既無必要也會憑空佔用磁碟。
    2. **不做 .pth -> .pt 改名**：那是為了讓 Ultralytics 接受上傳副本而做的，
       這裡不能改使用者的檔案。確認安全——SSD 架構是依原始檔名判斷（見
       sessions.py 的 model_arch 判定），且 torch.load() 對副檔名無感。

    回傳 dict 的鍵與 index_single_weight() 完全相同，方便共用註冊邏輯。
    """
    abs_path = os.path.abspath(file_path)
    return {
        "dir_path": os.path.dirname(abs_path).replace("\\", "/"),
        "weights_path": abs_path.replace("\\", "/"),
        "weights_size_mb": round(os.path.getsize(abs_path) / (1024 * 1024), 2),
        "epochs": "N/A",
        "optimizer": "N/A",
        "model_cfg": "N/A",
        "metrics_summary": {},
        "hyperparameters": {},
        "results_png": None,
        "confusion_matrix": None,
    }
