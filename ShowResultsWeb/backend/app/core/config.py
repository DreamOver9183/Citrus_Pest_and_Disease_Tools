import os
from pathlib import Path


def _resolve_paths():
    """Resolve project and backend paths with sensible defaults.

    Environment variables can override any of these:
      - PROJECT_ROOT
      - EXTRACTED_RUNS_DIR
      - REPORTS_DIR
      - SAMPLES_DIR
    """
    # backend dir: ../../../ from this file => ShowResultsWeb/backend
    current = Path(__file__).resolve()
    BACKEND_DIR = current.parents[2]

    PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", BACKEND_DIR.parent.parent)).resolve()

    extracted_default = BACKEND_DIR / "extracted_runs"
    EXTRACTED_RUNS_DIR = Path(os.environ.get("EXTRACTED_RUNS_DIR", extracted_default)).resolve()

    TEMP_DIR = EXTRACTED_RUNS_DIR / "temp_output"
    REPORTS_DIR = Path(os.environ.get("REPORTS_DIR", PROJECT_ROOT / "reports")).resolve()
    SAMPLES_DIR = Path(os.environ.get("SAMPLES_DIR", PROJECT_ROOT / "Datasets" / "samples")).resolve()
    IMAGES_DIR = Path(os.environ.get("IMAGES_DIR", EXTRACTED_RUNS_DIR / "images")).resolve()
    EXPORTS_DIR = Path(os.environ.get("EXPORTS_DIR", EXTRACTED_RUNS_DIR / "exports")).resolve()
    # 使用者手動放置模型/資料集的固定目錄，供「本機資料庫掃描」功能就地讀取。
    # 與 Datasets/ 同層級。本系統只會建立這個目錄並讀取其內容，絕不寫入或刪除裡面的檔案。
    LOCAL_LIBRARY_DIR = Path(os.environ.get("LOCAL_LIBRARY_DIR", PROJECT_ROOT / "LocalLibrary")).resolve()

    return {
        "PROJECT_ROOT": PROJECT_ROOT,
        "BACKEND_DIR": BACKEND_DIR,
        "EXTRACTED_RUNS_DIR": EXTRACTED_RUNS_DIR,
        "TEMP_DIR": TEMP_DIR,
        "REPORTS_DIR": REPORTS_DIR,
        "SAMPLES_DIR": SAMPLES_DIR,
        "IMAGES_DIR": IMAGES_DIR,
        "EXPORTS_DIR": EXPORTS_DIR,
        "LOCAL_LIBRARY_DIR": LOCAL_LIBRARY_DIR,
    }


_PATHS = _resolve_paths()

PROJECT_ROOT = _PATHS["PROJECT_ROOT"]
BACKEND_DIR = _PATHS["BACKEND_DIR"]
EXTRACTED_RUNS_DIR = _PATHS["EXTRACTED_RUNS_DIR"]
TEMP_DIR = _PATHS["TEMP_DIR"]
REPORTS_DIR = _PATHS["REPORTS_DIR"]
SAMPLES_DIR = _PATHS["SAMPLES_DIR"]
IMAGES_DIR = _PATHS["IMAGES_DIR"]
EXPORTS_DIR = _PATHS["EXPORTS_DIR"]
LOCAL_LIBRARY_DIR = _PATHS["LOCAL_LIBRARY_DIR"]

# 上傳檔案暫存目錄（絕對路徑，不受啟動時 cwd 影響）
UPLOAD_TEMP_DIR = Path(os.environ.get("UPLOAD_TEMP_DIR", BACKEND_DIR / "temp")).resolve()

# 系統同時允許載入的模型 Session 數量上限
MAX_SESSIONS = int(os.environ.get("MAX_SESSIONS", "3"))

# --- 資料集分析 ---
# 資料集分析只讀取 ZIP 內的文字檔（data.yaml / labels/*.txt / COCO json / VOC xml），
# 不解壓縮任何影像，因此不需要額外的解壓目錄常數；以下純量僅用於防護與容量控制。
# 保留的分析結果數量上限（只存統計 JSON，不存資料集內容）
MAX_DATASETS = int(os.environ.get("MAX_DATASETS", "10"))
# 單一上傳 ZIP 的大小上限（MB）
MAX_DATASET_ZIP_MB = int(os.environ.get("MAX_DATASET_ZIP_MB", "8192"))
# ZIP 內成員數量上限
MAX_DATASET_MEMBERS = int(os.environ.get("MAX_DATASET_MEMBERS", "200000"))
# ZIP 宣告的解壓後總大小上限（GB），用於擋下壓縮炸彈
MAX_DATASET_UNCOMPRESSED_GB = int(os.environ.get("MAX_DATASET_UNCOMPRESSED_GB", "64"))
# 本次分析累計可讀取的文字量上限（MB），超過則截斷而非失敗
MAX_DATASET_TEXT_MB = int(os.environ.get("MAX_DATASET_TEXT_MB", "256"))
# 單次分析最多讀取的標註檔數量
MAX_DATASET_LABEL_FILES = int(os.environ.get("MAX_DATASET_LABEL_FILES", "100000"))
# 單次分析最多解析的 Pascal VOC XML 檔數量
MAX_DATASET_XML_FILES = int(os.environ.get("MAX_DATASET_XML_FILES", "20000"))

# --- 模型格式匯出 ---
# 保留的匯出 job 數量上限（超過時淘汰最舊的「已完成」job，永不淘汰執行中的）
MAX_EXPORT_JOBS = int(os.environ.get("MAX_EXPORT_JOBS", "10"))
# 等待佇列長度上限。刻意設小：卡死的匯出無法從 Python 中止，有界佇列能讓它
# 降級成誠實的「佇列已滿」而不是無限堆積。
MAX_QUEUED_EXPORTS = int(os.environ.get("MAX_QUEUED_EXPORTS", "3"))
# 匯出產物保留時數，啟動與每次提交時掃除逾期者
EXPORT_JOB_TTL_HOURS = int(os.environ.get("EXPORT_JOB_TTL_HOURS", "24"))

# CORS 允許的前端來源（逗號分隔）。Docker 單容器部署下前後端同源，此設定主要用於本機開發
# （Vite dev server 預設在 5173 port）。
CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
    if origin.strip()
]


def ensure_dirs():
    """Create standard directories if missing (idempotent)."""
    for p in [EXTRACTED_RUNS_DIR, TEMP_DIR, REPORTS_DIR, SAMPLES_DIR, IMAGES_DIR, UPLOAD_TEMP_DIR, EXPORTS_DIR, LOCAL_LIBRARY_DIR]:
        try:
            p.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass


__all__ = [
    "PROJECT_ROOT",
    "BACKEND_DIR",
    "EXTRACTED_RUNS_DIR",
    "TEMP_DIR",
    "REPORTS_DIR",
    "SAMPLES_DIR",
    "IMAGES_DIR",
    "EXPORTS_DIR",
    "LOCAL_LIBRARY_DIR",
    "UPLOAD_TEMP_DIR",
    "MAX_SESSIONS",
    "MAX_DATASETS",
    "MAX_DATASET_ZIP_MB",
    "MAX_DATASET_MEMBERS",
    "MAX_DATASET_UNCOMPRESSED_GB",
    "MAX_DATASET_TEXT_MB",
    "MAX_DATASET_LABEL_FILES",
    "MAX_DATASET_XML_FILES",
    "MAX_EXPORT_JOBS",
    "MAX_QUEUED_EXPORTS",
    "EXPORT_JOB_TTL_HOURS",
    "CORS_ALLOWED_ORIGINS",
    "ensure_dirs",
]
