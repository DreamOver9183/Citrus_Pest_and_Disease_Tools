import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import ensure_dirs, TEMP_DIR, SAMPLES_DIR, IMAGES_DIR, CORS_ALLOWED_ORIGINS
from app.services.session_manager import (
    ACTIVE_SESSIONS,
    load_sessions_from_disk,
    cleanup_temp_files,
    cleanup_legacy_runs,
)
from app.routers import sessions, devices, inference, metrics, chart_generator, datasets, exports
from app.services.dataset_manager import load_datasets_from_disk
from app.services.export_service import load_export_jobs_from_disk

# 初始化目錄
try:
    ensure_dirs()
except Exception as e:
    print(f"[FastAPI] Error during directory initialization: {e}")

app = FastAPI()

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

@app.on_event("startup")
def startup_init():
    """啟動時自動清理暫存並載入本地/已存模型 Session"""
    cleanup_temp_files()
    cleanup_legacy_runs()
    load_sessions_from_disk()
    load_datasets_from_disk()
    # 必須在 load_sessions_from_disk() 之後：要用還原後的 session 清單過濾孤兒匯出
    load_export_jobs_from_disk(known_session_ids=set(ACTIVE_SESSIONS.keys()))

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