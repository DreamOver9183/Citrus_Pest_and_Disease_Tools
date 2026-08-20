import os
import json
import shutil
import re
import threading
from app.core.config import EXTRACTED_RUNS_DIR, TEMP_DIR, SAMPLES_DIR, LOCAL_LIBRARY_EXTRACT_DIR, ensure_dirs
from app.services.model_service import model_manager

# 全域 Session 追蹤字典。跨執行緒池讀寫（upload/delete/inference 皆可能併發執行），
# 所有「讀-改-寫」的複合操作都應持有 SESSIONS_LOCK，對齊 ModelManager 既有的鎖定模式。
ACTIVE_SESSIONS = {}
SESSIONS_LOCK = threading.RLock()

SESSIONS_FILE = os.path.join(EXTRACTED_RUNS_DIR, "sessions.json")

def save_sessions_to_disk():
    """將 ACTIVE_SESSIONS 持久化至 sessions.json"""
    try:
        os.makedirs(os.path.dirname(SESSIONS_FILE), exist_ok=True)
        with SESSIONS_LOCK:
            # LocalLibrary 掃描而來的 session 刻意不落地：它們引用的是使用者本機
            # 資料夾內的檔案，語意上只在「本次執行期間」有效。重啟後使用者重新
            # 按一次掃描即可，而不是留下一堆指向可能已被搬動/刪除的路徑的紀錄。
            snapshot = {
                sid: sdata for sid, sdata in ACTIVE_SESSIONS.items()
                if sdata.get("source") != "local_library"
            }
        with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[SessionManager] Error saving sessions to disk: {e}")

def load_sessions_from_disk():
    """從 sessions.json 還原 ACTIVE_SESSIONS，過濾掉實體檔案已遺失的幽靈記錄"""
    if not os.path.exists(SESSIONS_FILE):
        return
    try:
        with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
        with SESSIONS_LOCK:
            for sid, sdata in saved.items():
                weights_path = sdata.get("weights_path", "")
                if os.path.exists(weights_path):
                    ACTIVE_SESSIONS[sid] = sdata
                else:
                    print(f"[SessionManager] Skipping ghost session {sid}: weights not found at {weights_path}")
    except Exception as e:
        print(f"[SessionManager] Error loading sessions from disk: {e}")

def cleanup_temp_files():
    """清理暫存輸出目錄中的所有檔案"""
    print("[SessionManager] Cleaning up temporary output files...")
    if not os.path.exists(TEMP_DIR):
        return
    for f in os.listdir(TEMP_DIR):
        try:
            path = os.path.join(TEMP_DIR, f)
            if os.path.isfile(path) or os.path.islink(path):
                os.remove(path)
            elif os.path.isdir(path):
                shutil.rmtree(path)
        except Exception as e:
            print(f"[SessionManager] Error deleting {f}: {e}")

def cleanup_legacy_runs():
    """清理 extracted_runs/ 目錄下的舊暫存資料（僅清理 temp_output，保留 weight/reports/images）"""
    print("[SessionManager] Cleaning up temporary output files for a clean start...")
    if not os.path.exists(EXTRACTED_RUNS_DIR):
        return
    legacy_pattern = re.compile(r"^run_[a-f0-9]{8}$")
    for f in os.listdir(EXTRACTED_RUNS_DIR):
        if legacy_pattern.match(f):
            path = os.path.join(EXTRACTED_RUNS_DIR, f)
            if os.path.isdir(path):
                try:
                    shutil.rmtree(path)
                except Exception:
                    pass
    # LocalLibrary 的 ZIP 解壓內容與其 session 同生命週期——session 本來就不落地，
    # 留著解壓內容只會佔磁碟且成為沒有任何 session 指向的孤兒。
    if os.path.exists(LOCAL_LIBRARY_EXTRACT_DIR):
        try:
            shutil.rmtree(LOCAL_LIBRARY_EXTRACT_DIR)
            print(f"[SessionManager] Cleared local library extracts: {LOCAL_LIBRARY_EXTRACT_DIR}")
        except Exception as e:
            print(f"[SessionManager] Error clearing {LOCAL_LIBRARY_EXTRACT_DIR}: {e}")
    os.makedirs(LOCAL_LIBRARY_EXTRACT_DIR, exist_ok=True)

    # 僅清理 temp_output，保留 weight/reports/images 以防止使用者進度遺失
    if os.path.exists(TEMP_DIR):
        try:
            shutil.rmtree(TEMP_DIR)
            print(f"[SessionManager] Cleared temp directory: {TEMP_DIR}")
        except Exception as e:
            print(f"[SessionManager] Error clearing temp directory {TEMP_DIR}: {e}")
    os.makedirs(TEMP_DIR, exist_ok=True)

def delete_session(session_id: str):
    """刪除指定 Session 並清理本地解壓硬碟目錄"""
    with SESSIONS_LOCK:
        if session_id not in ACTIVE_SESSIONS:
            raise KeyError("Session not found")

        session_data = ACTIVE_SESSIONS[session_id]
        dir_path = session_data["dir_path"]

        # 嘗試釋放該模型在快取中的實例
        model_manager.load_model("")

        # 遞迴刪除本地實體解壓資料夾 (防範 extracted_runs 內硬碟爆滿)
        if "extracted_runs" in dir_path:
            parts = dir_path.split("/")
            try:
                er_idx = parts.index("extracted_runs")
                if er_idx + 1 < len(parts):
                    first_sub = parts[er_idx + 1]
                    if first_sub == "weight" and er_idx + 2 < len(parts):
                        folder_to_delete = parts[er_idx + 2]
                        target_to_del = "/".join(parts[:er_idx + 3])
                    else:
                        folder_to_delete = first_sub
                        target_to_del = "/".join(parts[:er_idx + 2])

                    # 這份白名單是「容器目錄」清單——底下的內容屬於個別 session，但目錄本身絕不能被刪。
                    # exports 是後加的：匯出產物放在 extracted_runs/exports/<job_id>/，若有任何
                    # session 的 dir_path 落在其下，上面的字串切割會算出 extracted_runs/exports
                    # 並 rmtree 整個匯出根目錄。datasets 與 local_library 也是同一個坑：
                    # LocalLibrary 的 ZIP 解壓在 extracted_runs/local_library/<zip>/，刪掉其中
                    # 一個 session 會連帶清空所有其他 ZIP 來源的模型。
                    if folder_to_delete and folder_to_delete not in [
                        "temp_output", "temp", "reports", "images", "weight", "exports", "datasets",
                        "local_library", "evaluations",
                    ]:
                        # 檢查是否有其他 active sessions 也在使用 target_to_del 下的任何路徑
                        other_sessions_using = False
                        for other_sid, other_sdata in ACTIVE_SESSIONS.items():
                            if other_sid != session_id:
                                other_dir = other_sdata.get("dir_path", "")
                                if other_dir.startswith(target_to_del):
                                    other_sessions_using = True
                                    break

                        if not other_sessions_using:
                            if os.path.exists(target_to_del):
                                try:
                                    shutil.rmtree(target_to_del)
                                except Exception as e:
                                    print(f"[SessionManager] Error deleting directory {target_to_del}: {e}")
                        else:
                            print(f"[SessionManager] Not deleting {target_to_del} because other active sessions are using it.")
            except ValueError:
                pass

        del ACTIVE_SESSIONS[session_id]
    save_sessions_to_disk()
