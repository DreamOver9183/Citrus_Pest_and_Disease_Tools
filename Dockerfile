# Stage 1: Build Frontend SPA
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY ShowResultsWeb/frontend/package*.json ./
RUN npm install --include=dev
COPY ShowResultsWeb/frontend ./
RUN npm run build

# Stage 2: Build Python Backend & Bundle All
FROM python:3.12-slim
WORKDIR /app/backend

# Install system dependencies for OpenCV (libgl1, libglib) and compiler (gcc)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# ultralytics 的 AUTOINSTALL 預設為 True，缺套件時會在請求執行緒中直接 pip install。
# app/__init__.py 已用 setdefault 關掉（那行才是真正生效的），這裡再宣告一次讓
# 部署設定可見。YOLO_CONFIG_DIR 則避免 ultralytics 往唯讀的 HOME 寫 settings.json。
ENV YOLO_AUTOINSTALL=0 \
    YOLO_OFFLINE=1 \
    YOLO_CONFIG_DIR=/app/backend/.ultralytics

# 1. Install backend python dependencies first (to cache pip downloads)
# torch 先從 PyTorch 的 CPU index 裝：預設 PyPI 給的是 CUDA 版，會連帶拉進
# nvidia-cudnn/cublas 等 16 個套件約 2GB，但 docker-compose.yml 沒有任何 GPU
# runtime 設定，那些相依永遠用不到。
#
# 版本必須釘在 2.12.1：litert-torch 0.9.x 要求 torch<2.13.0。若這裡裝 2.13，
# 稍後 requirements-docker.txt 會觸發降級，而降級版本是從預設索引拉的 CUDA 版，
# 前面的 CPU 安裝就白做了（實測會多出 16 個 nvidia-* 套件）。釘住相容版本後，
# 第二道指令看到已滿足就不會動它（實測 CUDA 套件數 16 → 0）。
# Added PyPI mirror for significantly faster download in the user's region
COPY ShowResultsWeb/backend/requirements.txt ShowResultsWeb/backend/requirements-docker.txt ./
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu 'torch==2.12.1' torchvision \
 && pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements-docker.txt

# 2. Copy built frontend assets from Stage 1 (changes in frontend code won't invalidate the pip install cache anymore)
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

# 3. Copy backend files
COPY ShowResultsWeb/backend ./

# Expose FastAPI application port
EXPOSE 8000

# Run FastAPI using uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
