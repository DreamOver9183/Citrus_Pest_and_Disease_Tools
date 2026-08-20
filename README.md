# 柑橘病蟲害工具包 Citrus Pest and Disease Tools

[![CI](https://github.com/DreamOver9183/Citrus_Pest_and_Disease_Tools/actions/workflows/ci.yml/badge.svg)](https://github.com/DreamOver9183/Citrus_Pest_and_Disease_Tools/actions/workflows/ci.yml)

柑橘病蟲害偵測的模型管理、資料集分析與格式轉換工具包。後端為 FastAPI + PyTorch（YOLO / SSDLite 雙軌架構），前端為 React + Vite 單頁應用，前後端打包成單一 Docker 映像檔部署。

## 功能特色

- **模型與裝置管理**：上傳 YOLO（`.pt` / ZIP 訓練成果）或 SSDLite（`.pth`）權重，自動解析訓練參數與指標摘要；支援 CPU / CUDA / MPS 裝置切換。
- **消融指標與精度分析**：自動裁切、繪製訓練曲線與正規化混淆矩陣，多模型並排比較。
- **即時影像診斷**：拖放圖片或整個資料夾即可批次推論，支援信心閾值即時調整與標註前後對照。
- **資料集分析**：上傳 YOLO / COCO / Pascal VOC 格式的資料集 ZIP，自動辨識格式並統計影像數、標註數、類別分佈與健檢結果——**全程不解壓縮**，數 GB 的資料集也能在一秒內完成分析。
- **模型格式匯出**：一鍵將 `best.pt` 轉換為 ONNX，或於 Docker 環境轉換為 TFLite（LiteRT），背景 job 執行並提供下載。
- **本機資料夾掃描**：把訓練成果或資料集（**資料夾或 ZIP 皆可**）放進專案根目錄的 `LocalLibrary/`，按一下「掃描」即可列出找到的所有權重與資料集，勾選要載入的項目直接使用——**不需上傳**，系統對該資料夾只讀不寫。

## 技術棧

| 層級 | 技術 |
|---|---|
| 後端 | FastAPI、Python 3.12、Ultralytics YOLO、PyTorch / TorchVision（SSDLite）、ONNX Runtime、LiteRT（僅 Docker） |
| 前端 | React 18、Vite 5、Tailwind CSS、Axios、Recharts、react-dropzone |
| 部署 | Docker 多階段建置（單一容器同時服務前後端）、GitHub Actions CI |

## 快速開始

### 方式一：Docker（建議）

需求：Docker Desktop / Docker Engine。

```bash
docker compose up --build
```

啟動後開啟 `http://localhost:8000` 即可使用完整功能（含 TFLite 匯出）。

### 方式二：本機開發

需求：Node.js 20+、Python 3.12+。

後端：

```powershell
cd ShowResultsWeb/backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

前端（另開一個終端機）：

```bash
cd ShowResultsWeb/frontend
npm install
npm run dev
```

前端開發伺服器（`http://localhost:5173`）會將 `/api`、`/static`、`/samples` 代理至後端的 8000 埠。

> 本機開發模式下 TFLite 匯出會顯示為不可用（LiteRT 僅支援 Linux x86 / macOS），僅 ONNX 匯出可用；完整功能請使用 Docker。

## 專案結構

```
ShowResultsWeb/backend/          FastAPI 後端
  app/routers/                   API 路由（sessions / datasets / exports / local_library / devices / inference / metrics）
  app/services/                  業務邏輯（模型管理、資料集分析、匯出 job、裝置探測）
  app/utils/                     ZIP 與目錄的唯讀讀取層、YOLO run 索引、圖片裁切
  tests/                         pytest 單元測試
ShowResultsWeb/frontend/         Vite + React 前端
  src/components/                各分頁元件（依 dataset-analyzer / live-demo / metric-dashboard / system-specs 拆分子模組）
  src/context/                   全域狀態（Context + 拆分後的獨立 hook）
LocalLibrary/                    本機資料夾掃描的目標（使用者自行放入，不進版控）
docs/architecture.md             系統架構文件（模組職責、關鍵設計決策、已知限制）
e2e_tests/                       端到端煙霧測試（需設定 E2E_ASSETS_DIR 指向本機資料才會執行）
.github/workflows/ci.yml         CI（後端 pytest + 前端建置）
```

完整的模組職責、設計決策與各項功能的技術細節，請參考 [docs/architecture.md](docs/architecture.md)；若使用 AI 代理（如 Claude Code）協作開發，請先閱讀 [CLAUDE.md](CLAUDE.md)。

## 測試

後端擁有涵蓋 ZIP 安全性、資料集解析、匯出流程等情境的 pytest 測試套件：

```powershell
cd ShowResultsWeb/backend
pip install -r requirements-dev.txt
pytest -v
```

前端目前以 `npm run build` 作為編譯檢查（尚無自動化測試框架），CI 已涵蓋兩者。

## 已知限制

- **TFLite（LiteRT）匯出僅支援 Docker / Linux 環境**：本機 Windows 開發模式下會顯示為不可用並說明原因。
- **COCO / Pascal VOC 資料集解析未經真實素材驗證**：本專案實際使用的資料集皆為 YOLO 格式，這兩種格式僅依規格實作。
- **SSDLite（`.pth`）模型不支援格式匯出**：僅 YOLO 架構可轉換為 ONNX / TFLite。
- **本機資料夾掃描的結果不會持久化**：LocalLibrary 來源的模型與資料集只存在於記憶體，後端重啟後需重新掃描（一般上傳的內容仍照常保留）。

更完整的已知限制清單與各項限制的技術背景，請參考 [docs/architecture.md](docs/architecture.md#8-已知限制)。
