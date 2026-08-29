import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import CORS_ALLOWED_ORIGINS, IMAGES_DIR, SAMPLES_DIR, TEMP_DIR, ensure_dirs
from app.core.envelope import register_exception_handlers
from app.db import engine as db_engine
from app.routers import (
    chart_generator,
    datasets,
    devices,
    evaluations,
    exports,
    inference,
    local_library,
    metrics,
    registry,
    reports,
    sessions,
)
from app.services.dataset_manager import load_datasets_from_disk
from app.services.evaluation_service import load_jobs_from_disk as load_eval_jobs_from_disk
from app.services.export_service import load_export_jobs_from_disk
from app.services.session_manager import (
    ACTIVE_SESSIONS,
    cleanup_legacy_runs,
    cleanup_temp_files,
    load_sessions_from_disk,
)

# 初始化目錄
try:
    ensure_dirs()
except Exception as e:
    print(f"[FastAPI] Error during directory initialization: {e}")

@asynccontextmanager
async def lifespan(_app: FastAPI):
    """啟動時清理暫存並載入本地/已存狀態；關閉時釋放資料庫連線池。

    用 lifespan 而非已棄用的 @app.on_event。
    """
    cleanup_temp_files()
    cleanup_legacy_runs()

    # 權重登錄簿。init_db() 永不拋例外——資料庫是可選相依，連不上時只是
    # /api/registry/* 回 503，其餘功能完全不受影響（見 app/db/engine.py）。
    db_engine.init_db()

    load_sessions_from_disk()
    load_datasets_from_disk()
    # 必須在 load_sessions_from_disk() 之後：要用還原後的 session 清單過濾孤兒匯出
    load_export_jobs_from_disk(known_session_ids=set(ACTIVE_SESSIONS.keys()))
    # 評估結果不做「來源 session 是否還在」的過濾——它是一次獨立的測量，
    # 而本專案多數 session 來自不落地的 LocalLibrary，過濾等於每次重啟刪光。
    # 必須排在 init_db() 之後：還原時會順便把尚未入帳的結果補寫進登錄簿。
    load_eval_jobs_from_disk()

    yield

    db_engine.dispose()


app = FastAPI(lifespan=lifespan)

# 統一的錯誤信封。必須在註冊路由之前掛上，讓所有路由（含驗證失敗）都走同一條錯誤路徑。
register_exception_handlers(app)

# 配置 CORS，支持本機開發時前端 Vite dev server 跨域存取
# （Docker 單容器部署下前後端同源，不受此設定影響）。專案未使用 cookie/session 驗證，
# 故不開放 allow_credentials，避免與萬用 origin 併用的無效且不安全組合。
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 註冊 API 路由分層
app.include_router(sessions.router, prefix="/api")
app.include_router(devices.router, prefix="/api")
app.include_router(inference.router, prefix="/api")
app.include_router(metrics.router, prefix="/api")
app.include_router(chart_generator.router, prefix="/api")
app.include_router(datasets.router, prefix="/api")
app.include_router(exports.router, prefix="/api")
app.include_router(local_library.router, prefix="/api")
app.include_router(evaluations.router, prefix="/api")
app.include_router(reports.router, prefix="/api")
app.include_router(registry.router, prefix="/api")

# 掛載靜態推論/指標圖片暫存目錄
app.mount("/static", StaticFiles(directory=str(TEMP_DIR)), name="static")

# 掛載原始持久化圖片目錄
if IMAGES_DIR.exists():
    try:
        app.mount("/images", StaticFiles(directory=str(IMAGES_DIR)), name="images")
    except Exception as e:
        print(f"[FastAPI] Could not mount images directory: {e}")

# 掛載專案精選展示圖片樣本目錄
if SAMPLES_DIR.exists():
    try:
        app.mount("/samples", StaticFiles(directory=str(SAMPLES_DIR)), name="samples")
        print(f"[FastAPI] Mounted samples from: {SAMPLES_DIR}")
    except Exception as e:
        print(f"[FastAPI] Could not mount samples directory: {e}")


# 掛載前端靜態頁面 (以利 Docker 一鍵啟動單容器託管)
backend_current_dir = os.path.dirname(os.path.abspath(__file__))
frontend_dist = os.path.abspath(os.path.join(backend_current_dir, "../frontend/dist"))
if not os.path.exists(frontend_dist):
    frontend_dist = os.path.abspath(os.path.join(backend_current_dir, "frontend/dist"))

if os.path.exists(frontend_dist):
    print(f"[FastAPI] Mounting frontend static files from: {frontend_dist}")
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
else:
    print(f"[FastAPI] Frontend dist directory not found at: {frontend_dist}. Running in API-only mode.")
