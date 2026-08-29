# 柑橘病蟲害工具包 Citrus Pest and Disease Tools

[![CI](https://github.com/DreamOver9183/Citrus_Pest_and_Disease_Tools/actions/workflows/ci.yml/badge.svg)](https://github.com/DreamOver9183/Citrus_Pest_and_Disease_Tools/actions/workflows/ci.yml)

柑橘病蟲害偵測的模型管理、資料集分析與格式轉換工具包。後端為 FastAPI + PyTorch（YOLO / SSDLite 雙軌架構），前端為 React + Vite 單頁應用，前後端打包成單一 Docker 映像檔，搭配一個 PostgreSQL 容器保存權重登錄簿，`docker compose up --build` 一個指令即可啟動。

## 功能特色

- **模型與裝置管理**：上傳 YOLO（`.pt` / ZIP 訓練成果）或 SSDLite（`.pth`）權重，自動解析訓練參數與指標摘要；支援 CPU / CUDA / MPS 裝置切換。
- **消融指標與精度分析**：自動裁切、繪製訓練曲線與正規化混淆矩陣，多模型並排比較。
- **即時影像診斷**：拖放圖片或整個資料夾即可批次推論，支援信心閾值即時調整與標註前後對照。
- **資料集分析**：上傳 YOLO / COCO / Pascal VOC 格式的資料集 ZIP，自動辨識格式並統計影像數、標註數、類別分佈與健檢結果——**全程不解壓縮**，數 GB 的資料集也能在一秒內完成分析。
- **模型格式匯出**：一鍵將 `best.pt` 轉換為 ONNX，或於 Docker 環境轉換為 TFLite（LiteRT），背景 job 執行並提供下載。
- **本機資料夾掃描**：把訓練成果或資料集（**資料夾或 ZIP 皆可**）放進專案根目錄的 `LocalLibrary/`，按一下「掃描」即可列出找到的所有權重與資料集，勾選要載入的項目直接使用——**不需上傳**，系統對該資料夾只讀不寫。
- **驗證評估**：讓載入的模型**實際跑過**資料集的 test / valid split，重新計算 mAP、逐類別 AP 與召回率、混淆矩陣與 PR 曲線——不是沿用訓練時記錄的舊數值。多個模型跑同一份測試集即可做公平的消融比較，並附「AP × 標註框尺寸」散點圖用於分析小物件表現。
- **成果報告**：把一或多份評估打包成單一自足的 HTML（圖表全部內嵌，離線可讀），瀏覽器列印即可另存 PDF。
- **權重登錄簿**：以權重檔內容的 SHA-256 為身分的長期帳本，自動記錄每顆權重的**完整訓練超參數**（整份 `args.yaml`，實測 116 項）與歷次實測指標（mAP@50、mAP@50-95、Precision、Recall、F1、**Micro-Accuracy / Jaccard index**）。與已載入的 Session 生命週期脫鉤——刪掉模型、重啟系統，紀錄都還在，可跨權重排序比較。

## 技術棧

| 層級 | 技術 |
|---|---|
| 後端 | FastAPI、Python 3.12、Ultralytics YOLO、PyTorch / TorchVision（SSDLite）、ONNX Runtime、LiteRT（僅 Docker） |
| 資料庫 | SQLAlchemy 2.x；Docker 用 PostgreSQL 16，本機開發與 CI 自動落回 SQLite 檔案（零設定） |
| 前端 | React 18、Vite 5、Tailwind CSS、Axios、Recharts、react-dropzone |
| 部署 | Docker 多階段建置（應用單一容器同時服務前後端 + 一個資料庫容器）、GitHub Actions CI |

## 快速開始

### 方式一：Docker（建議）

需求：Docker Desktop / Docker Engine。

```bash
docker compose up --build
```

啟動後開啟 `http://localhost:8000` 即可使用完整功能（含 TFLite 匯出）。此指令會一併啟動權重登錄簿的 PostgreSQL 容器，資料存在 named volume `citrus-db-data`，重建容器不會遺失。

> 資料庫是**可選**相依：即使它起不來，模型載入、推論、資料集分析與驗證評估都照常運作，只有「權重登錄簿」分頁會顯示離線。

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
>
> 本機開發**不需要**安裝 PostgreSQL：未設定 `DATABASE_URL` 時，權重登錄簿會自動使用 `ShowResultsWeb/backend/extracted_runs/registry.db`（SQLite）。

## 專案結構

```
ShowResultsWeb/backend/          FastAPI 後端
  app/routers/                   API 路由（sessions / datasets / exports / local_library / evaluations / reports / registry / devices / inference / metrics）
  app/core/envelope.py           統一的 API 回應信封與錯誤契約
  app/db/                        權重登錄簿的資料表與連線層（SQLAlchemy）
  app/services/                  業務邏輯（模型管理、資料集分析、匯出/評估 job、報告產生、登錄簿、裝置探測）
  app/utils/                     ZIP 與目錄的唯讀讀取層、YOLO run 索引、圖片裁切
  tests/                         pytest 單元測試
ShowResultsWeb/frontend/         Vite + React 前端
  src/api/client.js              統一 API 客戶端（拆信封、錯誤正規化）
  src/components/                各分頁元件（依 dataset-analyzer / live-demo / metric-dashboard / system-specs / registry 拆分子模組）
  src/context/                   全域狀態（Context + 拆分後的獨立 hook）
LocalLibrary/                    本機資料夾掃描的目標（使用者自行放入，不進版控）
reports/                         驗證評估產生的成果報告（HTML，不進版控）
docs/architecture.md             系統架構文件（模組職責、關鍵設計決策、已知限制）
e2e_tests/                       端到端測試（以 LocalLibrary/ 的真實檔案驅動）
.github/workflows/ci.yml         CI（後端 pytest：SQLite 與 PostgreSQL 各一輪；前端建置）
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

端到端測試需要後端已在執行，並以 `LocalLibrary/` 內的真實檔案驅動，共 16 個階段（API 信封契約、掃描、勾選載入、指標、推論、資料集分析、ONNX/TFLite 匯出、驗證評估、成果報告、登錄簿入帳與雜湊對照、指標交叉驗算、帳本存活性、刪除安全性）：

```bash
python e2e_tests/e2e_local_library.py
```

`LocalLibrary/` 是空的時會優雅跳過。設 `E2E_SKIP_TFLITE=1` 可略過耗時約 110 秒的 TFLite 匯出。

## 已知限制

- **TFLite（LiteRT）匯出僅支援 Docker / Linux 環境**：本機 Windows 開發模式下會顯示為不可用並說明原因。
- **COCO / Pascal VOC 資料集解析未經真實素材驗證**：本專案實際使用的資料集皆為 YOLO 格式，這兩種格式僅依規格實作。
- **SSDLite（`.pth`）模型不支援格式匯出**：僅 YOLO 架構可轉換為 ONNX / TFLite。
- **本機資料夾掃描的結果不會持久化**：LocalLibrary 來源的模型與資料集只存在於記憶體，後端重啟後需重新掃描（一般上傳的內容仍照常保留）。
- **驗證評估僅支援 YOLO 架構**：`model.val()` 是 Ultralytics 專屬，SSDLite 需要另一套評估流程，UI 上會顯示但停用並說明原因。
- **Micro-Accuracy 是門檻相依的指標**：它取自 Ultralytics 的混淆矩陣，配對門檻為該套件的預設值 conf = 0.25 / IoU = 0.45（指標定義文件寫的是 IoU ≥ 0.5，這個落差已隨每筆紀錄存下並在介面標明）。與對所有門檻積分的 mAP 不可直接並列解讀。
- **權重登錄簿不會自動清理**：刪除模型或評估紀錄都不會連帶刪除帳本內容（那正是它的價值），需要時請從「權重登錄簿」分頁自行移除。
- **上傳的資料集 ZIP 無法用於評估**：分析階段完全不解壓縮，影像位元組在請求結束後即釋放。請改用本機資料夾。
- **評估未提供 COCO 式分桶 AP**：以「每類別 AP × 中位框面積」呈現尺度與表現的關係作為替代。

更完整的已知限制清單與各項限制的技術背景，請參考 [docs/architecture.md](docs/architecture.md#9-已知限制)。
