# 系統架構文件

本文件記錄柑橘病蟲害雙軌診斷平台（YOLO / SSDLite）目前的系統架構，供後續開發與維護參考。內容對應 2026-08 完成的重構（測試安全網 → 後端強化 → API 型別化 → 前端拆分）之後的狀態。

## 1. 部署拓樸

應用本身是單一 Docker image：多階段建置 (`Dockerfile`) 先用 `node:20-alpine` 建置 React SPA (`npm run build` → `frontend/dist`)，再複製進 `python:3.12-slim`，FastAPI 用 `StaticFiles(html=True)` 掛載 `frontend/dist` 到 `/`。前後端同源、單一 port（8000）對外，不需額外反向代理。`docker-compose.yml` 把 `Datasets/`（唯讀）與 `ShowResultsWeb/backend/extracted_runs/`（讀寫）掛成 volume 做持久化。

`docker-compose.yml` 另起一個 `postgres:16-alpine` 服務給權重登錄簿（§10），資料放 named volume。`docker compose up --build` 仍然是唯一需要的指令：`healthcheck` + `depends_on: service_healthy` 保證啟動順序，應用端另有一層連線重試吸收殘餘的競速窗口。資料庫是**可選相依**——連不上時只有 `/api/registry/*` 降級回 503，其餘功能完全不受影響。

`db` 服務刻意**不指定 `platform`**：`postgres:16-alpine` 有 arm64 映像，讓它在 ARM 主機跑原生比跟著應用一起被逼進 amd64 模擬快得多（應用釘 amd64 是 TFLite 的限制，與資料庫無關）。

## 2. 後端（`ShowResultsWeb/backend/`）

```
main.py                        FastAPI 入口：CORS、路由註冊、靜態掛載、startup 清理
app/schemas.py                 各路由共用的 payload / request 模型（供 /docs 顯示完整 schema）
app/core/config.py             唯一路徑/設定真相來源（env override + 預設值），ensure_dirs()
app/core/envelope.py           統一回應信封 ApiResponse[T]、ApiException 與四個全域 handler
app/db/
  engine.py                    連線與 session 工廠；資料庫是可選相依，連不上只降級不中斷
  models.py                    weights / training_runs / evaluations 三張表（僅用通用型別）
app/routers/
  sessions.py                  session CRUD + 模型上傳（ZIP / 單一權重檔）
  datasets.py                  資料集上傳分析 / 列表 / 刪除
  exports.py                   模型格式轉換：能力查詢 / 送出 job / 輪詢 / 下載 / 刪除
  local_library.py             本機資料夾：路徑查詢 / 掃描（唯讀）/ 載入勾選項目
  evaluations.py               驗證評估：可用目標查詢 / 送出 / 輪詢 / 圖表 / 刪除
  registry.py                  權重登錄簿：清單 / 明細 / 指標帳本 / 統計 / 刪除
  reports.py                   成果報告：產生 / 列表 / 檢視 / 下載 / 刪除
  devices.py                   裝置列舉 / 切換
  inference.py                 執行推論（sync def，靠 FastAPI 執行緒池跑 PyTorch）
  metrics.py                   results.png 裁切、獨立圖表（confusion matrix 等）
  chart_generator.py           用 Pillow 手繪 SSD 訓練曲線（train_loss/mAP）
app/services/
  session_manager.py           全域字典 ACTIVE_SESSIONS（記憶體，RLock 保護）+ sessions.json 持久化
  dataset_detector.py          資料集格式偵測（YOLO / COCO / Pascal VOC）
  dataset_analyzer.py          資料集統計分析（不解壓縮，只讀標註文字檔）
  dataset_manager.py           ACTIVE_DATASETS + datasets.json 持久化（僅存統計，不存資料集內容）
  export_capabilities.py       匯出能力探測：OS 閘 + 相依探測（find_spec，不 import）
  export_service.py            匯出 job 表、daemon worker、產物與 manifest 生命週期
  library_scanner.py           LocalLibrary 的探索（唯讀列出候選項）與註冊（只處理勾選項）
  evaluation_service.py        評估 job 表、daemon worker、model.val() 與指標正規化
  dataset_resolver.py          把資料集記錄解析成磁碟上真實的 split 目錄
  report_service.py            Jinja2 渲染、圖片 base64 內嵌、寫入 REPORTS_DIR
  registry_service.py          權重雜湊、登錄簿讀寫；所有寫入都吞例外且在鎖之外
  model_service.py             ModelManager 單例：同時只保留一個模型在記憶體
  device_service.py            裝置探測結果快取（30s TTL）
app/utils/
  zip_handler.py                ZIP 安全解壓（路徑穿越防禦）+ YOLO run 索引
  dataset_zip.py               資料集 ZIP 唯讀層：虛擬目錄樹、大小上限、帶 cap 的成員讀取
  dataset_dir.py               資料集「真實目錄」唯讀層（dataset_zip 的目錄對應版本）
  dir_handler.py               目錄的 YOLO run 索引與就地權重索引（zip_handler 的目錄對應版本）
  image_cropper.py             results.png 網格像素裁切（2x5 grid）
  device_probe.py              torch/psutil 偵測 CPU/CUDA/MPS
tests/apitest.py               路由測試共用的信封 helper（每次呼叫順帶驗一次契約）
tests/                         pytest 單元測試（zip_handler / image_cropper / session_manager /
                               dataset_analyzer / dataset_manager / dataset_dir /
                               dir_handler / export_service / export_routes /
                               local_library_router / evaluation_service /
                               evaluation_routes / dataset_resolver /
                               session_container_dirs / envelope / micro_accuracy /
                               registry_service / registry_routes，共 349 項）
```

### 關鍵設計決策（有意保留，非缺陷）

- **`ModelManager` 單例、同時只駐留一個模型**：切換模型時主動 `del` + `gc.collect()` + `torch.cuda.empty_cache()`，避免多個大型模型疊加造成 OOM。這代表併發測試不同模型時會互相搶佔、觸發重新載入，是刻意的記憶體安全取捨，不會修改。
- **執行期狀態不進資料庫**：Session 狀態 = 記憶體 dict（`ACTIVE_SESSIONS`）+ JSON 快照（`sessions.json`）+ 檔案系統路徑，啟動時以「權重檔是否存在」過濾幽靈 session。2026-08 新增的權重登錄簿（§10）是**附加**的長期帳本，不取代這一層——session 回答「現在載入了什麼」，登錄簿回答「這台機器看過哪些權重」，兩者生命週期本來就不同。
- **無身分驗證**：工具定位為本地離線展示，非對外服務。
- **`ACTIVE_SESSIONS` 併發保護**：所有跨執行緒池的讀-改-寫操作都透過 `session_manager.SESSIONS_LOCK`（`threading.RLock`）保護，對齊 `ModelManager` 既有的鎖定模式。
- **API 回應契約**：所有路由回同一個 `ApiResponse` 信封，錯誤走真正的 HTTP 狀態碼，由 `tests/test_envelope.py` 強制。完整說明見 §9。

## 3. 前端（`ShowResultsWeb/frontend/src/`）

```
main.jsx → App.jsx                     六分頁 SPA：模型與裝置 / 消融分析 / 即時診斷 / 資料集 /
                                       驗證評估 / 權重登錄簿
                                       （模型匯出是 session 卡片上的動作，不另開分頁）
api/client.js                          統一 API 客戶端：拆信封、把錯誤正規化成丟出的 ApiError
context/
  ExperimentContext.jsx                組合層 Provider：組合七個獨立 hook，對外仍暴露單一 useExperiment()
  hooks/
    useSessions.js                     Session 清單、CRUD、載入狀態
    useDeviceControl.js                裝置清單與目前選用裝置
    useLiveDemoState.js                LiveDemo 分頁的推論結果/已上傳檔案狀態（跨分頁切換不遺失）
    useDatasetState.js                 資料集分析結果與進行中的請求（跨分頁切換不遺失）
    useModelExport.js                  匯出 job 狀態與輪詢迴圈（跨分頁切換不遺失）
    useLocalLibrary.js                 本機資料夾路徑、候選清單與勾選狀態（跨分頁切換不遺失）
    useEvaluation.js                   評估 job 輪詢、報告清單（跨分頁切換不遺失）
    useRegistry.js                     登錄簿清單、排序與展開狀態（跨分頁切換不遺失）
components/
  SystemSpecs.jsx                      上傳、裝置選擇、session 管理
  MetricDashboard.jsx                  消融看板協調器（狀態 + 資料抓取 + 版面）
  metric-dashboard/
    metricsOptions.js                  指標選項清單常數
    IndicatorSidebar.jsx               左側指標勾選側邊欄（含收折按鈕）
    ModelMetricCard.jsx                單一模型指標圖卡片（混淆矩陣區塊與曲線區塊共用）
    ChartGrid.jsx                      混淆矩陣 + 各指標曲線的主圖區
  LiveDemo.jsx                         即時推論協調器（guard + 版面）
  live-demo/
    useLiveDemoInference.js            推論資料流 hook：上傳/重抽樣/信心閾值調整/AbortController
    classMap.js                        病蟲害類別中英對照表
    traverseFileTree.js                拖放資料夾遞迴解析工具
    ImageZoom.jsx                      局部放大鏡元件
    ResultCard.jsx                     單張推論結果卡片
    ControlPanel.jsx                   右側上傳/設定控制欄
  system-specs/
    ExportPanel.jsx                    session 卡片上的模型格式轉換區塊
    LocalLibraryPanel.jsx              本機資料夾路徑、候選勾選清單與載入按鈕
    exportFormats.js                   格式標籤與靜態 Tailwind class 對照表
  DatasetAnalyzer.jsx                  資料集分析協調器
  dataset-analyzer/
    useDatasetAnalysis.js              暫態 UI 狀態（dropzone、排序、展開）
    chartTheme.js / datasetFormat.js   圖表色票與格式化工具（純 JS）
    DatasetUploadPanel.jsx             上傳區 + 分析紀錄清單
    DatasetOverviewHeader.jsx          格式徽章、規模摘要、交叉檢查結果
    DatasetSummaryCards.jsx            四個 KPI 磚
    ClassDistributionChart.jsx         recharts 水平長條（可依 split 堆疊）
    SplitCompositionChart.jsx          recharts 甜甜圈
    SplitDensityChart.jsx              recharts 長條 + 折線雙軸
    ClassStatsTable.jsx                類別明細表（可排序）
    ValidationIssueList.jsx            健檢結果（error/warning/info 分級）
    DefinitionViewer.jsx               原始 data.yaml / COCO json 檢視
    GlassTooltip.jsx                   深色玻璃質感 tooltip
  Registry.jsx                         權重登錄簿協調器（總覽磚 + 清單／帳本切換）
  registry/
    WeightTable.jsx                    可排序的權重清單
    WeightDetailPanel.jsx              完整訓練超參數 + 該權重的歷次實測
    MetricLedgerTable.jsx              跨權重的指標帳本
    registryFormat.js                  格式化與靜態 Tailwind class 查表
  Lightbox.jsx                         自訂 Modal：滾動鎖定、拖曳邊界、Esc 關閉
```

無路由庫（純 tab 切換）、狀態管理以 axios + hooks/Context 為主，沒有導入 React Query/SWR 這類快取層。
唯一的第三方視覺化依賴是 **recharts（釘在 `~2.12.7`）**——釘 2.x 是因為 recharts 3.x 目標為 React 19，而本專案是 React 18.3.1，且 `package-lock.json` 未進版控、CI 跑裸 `npm install`，`^` 範圍會在某天無關的 PR 上靜默升 major。

### Context 組合模式

`ExperimentContext.jsx` 本身不持有業務狀態，而是組合 `useSessions`、`useDeviceControl`、`useLiveDemoState`、`useDatasetState`、`useModelExport`、`useLocalLibrary`、`useEvaluation`、`useRegistry` 八個獨立 hook 的回傳值，攤平後透過同一個 `useExperiment()` 對外暴露。這是刻意的 adapter 設計：既有元件（`SystemSpecs.jsx`、`LiveDemo.jsx`、`MetricDashboard.jsx`、`App.jsx`）呼叫 `useExperiment()` 的方式完全不需變動，同時八個 hook 各自獨立、可單獨測試或重用。`deleteSession` 是唯一的例外——組合層額外包了一層，在刪除後若已無任何 session，會呼叫 `setActiveTab('init')`（此邏輯原本就存在，只是搬到組合層，因為 `activeTab` 屬於頁面導覽狀態、不屬於任一個子 hook）。

## 4. 資料集分析（第 4 分頁）

上傳資料集 ZIP → 自動辨識格式 → 統計影像數／標註數／類別分佈，並用 recharts 呈現互動圖表。

### 核心決策：完全不解壓縮

分析所需的資訊只有兩種來源：**檔名清單**（`ZipFile.infolist()`，即中央目錄）與**少量文字檔**（`data.yaml`、`labels/*.txt`、COCO json、VOC xml）。影像像素一個 byte 都不需要讀。

實測資料集有 8,021 張影像但標註文字合計不到 2 MB，因此：峰值磁碟 = 使用者上傳的 ZIP（Starlette 本來就已 spool 到磁碟）、峰值記憶體 = 單一標註檔、`datasets.json` 只有數 KB。相對地，若採「解壓後分析再刪除」，數 GB 的資料集會需要等量的暫存空間。

連帶好處：`delete_dataset()` 沒有任何目錄要刪，因此完全避開了 `session_manager.delete_session()` 的路徑字串手術（該函式對 `extracted_runs/datasets/<id>` 這種路徑會算出 `extracted_runs/datasets` 並 rmtree 整個根目錄）。`tests/test_dataset_manager.py::test_delete_dataset_touches_no_filesystem` 就是在釘住這件事。

**路由也刻意不把上傳內容複製到 `UPLOAD_TEMP_DIR`**：Starlette 已將 request body 寫入 `SpooledTemporaryFile`，再 `copyfileobj` 一次會讓數 GB 的 ZIP 佔用雙倍磁碟。`SpooledTemporaryFile` 可 seek，直接交給 `ZipFile` 即可。

### 目錄探索是計數的唯一真相來源

`data.yaml` **只用於交叉驗證，永遠不決定計數**。這不是理論上的謹慎——實測資料集的 `data.yaml` 帶有：

```yaml
path: "f:\\115柑橘病蟲害專題\\Datasets_YOLO26_v5\\Citrus_YOLO26_Detect"
val: valid/images
```

`path:` 指向訓練當時他機的絕對路徑，且其中的 `Citrus_YOLO26_Detect` 子目錄在資料集內根本不存在。若拿它解析 split 位置，結果會是「0 張影像」而且極難追查。`val:` 與磁碟上的 `valid/` 目錄名不同也是常見狀況。兩者現在都只產生 `I_YAML_KEY_DIR_MAPPING` 資訊，不影響任何數字。

同理，ZIP 內常有一層包裝目錄（`Datasets_YOLO26_v5/train/...`），偵測器對虛擬樹的**每一個目錄**評分而非只看根層，因此任意深度的巢狀都自動處理。

### 空標註檔是負樣本，不是損壞

實測資料集 8,021 個標註檔中有 450 個是空的。這是刻意保留的負樣本（背景影像），用於降低模型假陽性。因此「空標註檔」與「宣告了但零實例的類別」一律是 `info` 級，**絕不可標成 error**——否則使用者會誤以為資料集壞了。

### 檔名類別提示交叉檢查

實測資料集的增強樣本命名為 `synth_aug_cls3_00042.jpg`，其中 `cls<N>` 即類別索引。分析器用通用正則 `cls(\d+)` 取出提示並與標註內容比對（實測 4,098 個檔案 100% 命中）。

兩個必須做對的細節：比對用「**包含**」而非「等於」（一張影像可含多個類別），以及**空標註檔要跳過**不計入分母。

刻意**不**硬編任何專案特有的語意前綴對照表：`docs/柑橘病蟲害資料集_完整版.md` 描述的是 12 類別、`H_MC_`/`P_AP_LD_` 前綴的**舊版**資料集，而實際使用的 v5 已改為 8 類別、不同類別名、不同命名慣例。硬編那張表會在資料集改版後變成主動錯誤的資訊。

### 防護上限

`app/utils/dataset_zip.py` 依序檢查：ZIP 檔大小 → 成員數 → 宣告的解壓總大小 → 每個成員的路徑穿越 → `read_member_capped()`。最後這項量的是**實際解壓出的位元組**（讀 `cap+1` 判斷超限），因此偽造中央目錄 `file_size` 的壓縮炸彈也擋得下來。上限值皆可用環境變數覆寫（見 `config.py` 的 `MAX_DATASET_*`）。

Pascal VOC 的 XML 在交給 `xml.etree.ElementTree` 前會先檢查前 4 KB 是否含 `<!DOCTYPE`／`<!ENTITY` 並直接拒絕——expat 對 entity expansion（billion laughs）沒有防護，環境也沒有 `defusedxml`，而合法的 VOC 標註不需要 DOCTYPE。

### 格式支援深度

**YOLO 為深度分析且經真實資料驗證**（分析器輸出與直接掃描檔案系統的結果逐項吻合：8,021 影像／25,566 標註／450 空標註／8 類別逐一相符）。

**COCO 與 Pascal VOC 只做基本解析**（影像數、標註數、類別列表），且本專案沒有任何 COCO/VOC 素材可供驗證，因此回應帶 `verified: false` 與 `unverified_note`，UI 也會顯示明顯的琥珀色「基本分析」徽章與說明。

## 5. 模型格式匯出（ONNX / TFLite）

session 卡片上可把 `best.pt` 轉成 ONNX 或 TFLite 並下載。不另開分頁——匯出是逐 session 的動作，結構上與刪除按鈕同類。

### TFLite 走 PyTorch 直轉，不經過 ONNX

直覺做法是 PyTorch→ONNX→TFLite（ultralytics 的 `saved_model` 路徑），但那條路在本專案有**無解的相依衝突**：

- `ultralytics[export-tensorflow]` 要求 `numpy<2.0.0`（python<3.13）
- ultralytics 傳遞相依的 `opencv-python 5.x` 要求 `numpy>=2`

映像檔基底是 `python:3.12-slim`，兩者無法同時滿足，pip 只能降級 opencv 或 numpy，等於在執行中的推論堆疊底下抽換套件。

改走 `format="litert"`：`litert_torch.convert()` 從 PyTorch 直接轉，只需 `litert-torch` + `ai-edge-litert`（無 TensorFlow、無 numpy 限制），且產出**單一 `.tflite` 檔**而非一個含多種變體的目錄。交付物完全相同，路徑更短更便宜。

代價是 `export_litert` 內有 `assert MACOS or (LINUX and not ARM64)`，Windows 直接失敗——這就是「TFLite 僅 Docker」的技術根據，也是能力探測要分成兩道閘的原因。

### 能力探測分兩道閘

`export_capabilities.py` 分別回報 **平台不支援**（`reason_kind: "platform"`）與 **缺少套件**（`reason_kind: "dependency"`），因為使用者的下一步動作完全不同：前者要改用 Docker，後者要裝套件。相依探測一律用 `importlib.util.find_spec()` **不 import**——import litert/TF 要數秒與數百 MB RSS，而這個探測每次 SystemSpecs 掛載都會跑。

UI 上不可用的格式**顯示但停用**並附原因，而不是隱藏：使用者因此知道 TFLite 存在、且 Docker 能解鎖它。

### 匯出用自己的 YOLO 實例，絕不碰 ModelManager

`ModelManager._lock` 是非重入 `threading.Lock` 且 `predict` 全程持有；`load_model` 又會 `del` 掉常駐模型。若匯出走 ModelManager，每個推論請求都會排在 30-300 秒的匯出後面，還會把使用者在「即時診斷」載入的模型踢掉。

因此 worker 自建 `YOLO(staged_path)`，代價只有約 5MB 常駐。**硬規則：`export_service` 不得 import `model_service`。**

實測驗證：匯出進行中送出推論請求，1.95 秒回應 `status: success`，且伺服器 log 顯示 ModelManager 獨立載入了自己的模型。

### 產物暫存複製，不就地匯出

exporter 會把產物寫在**來源檔旁邊**，所以先把 `weights_path` 複製到 `EXPORTS_DIR/<job_id>/`，用複製來改寫落點。這樣不會往使用者的 run 目錄（卡片上顯示的「實體工作區目錄」）丟檔案，一次 `rmtree` 就能清乾淨，而且產物可依 `custom_name` 命名——三個 session 都下載出 `best.onnx` 是真實的 UX 失敗。

**`session_manager.delete_session()` 的白名單已加入 `exports` 與 `datasets`**：該函式用字串切割反推刪除目標，若某個 session 的 `dir_path` 落在 `extracted_runs/exports/` 底下，會算出 `extracted_runs/exports` 並 rmtree 整個匯出根目錄。`tests/test_session_container_dirs.py` 對五個容器目錄逐一釘住這件事。

### Job 模型

- 一個 `daemon=True` 執行緒 + 有界 `queue.Queue`，**不用 `ThreadPoolExecutor`**——後者的 atexit hook 會 join 非 daemon 執行緒，Ctrl-C 會卡住 uvicorn 長達整個匯出時間。
- 狀態 `queued`/`running`/`done`/`failed`，**不做 cancel**：執行中的 `model.export()` 無法從 Python 中止，給一個按了沒用的取消鍵比不給更糟。
- `exporting` 階段佔約九成時間且無中間進度（ultralytics 只有 start/end 兩個 callback），因此 UI 顯示不定量動畫 + 經過秒數 + log 尾巴，**不偽造百分比**。
- log 尾巴掛 handler 到 `"ultralytics"` logger。ultralytics 用 `colorstr()` 嵌 ANSI 色碼，收進緩衝前會用 `_ANSI_RE` 剝掉，否則前端會顯示逃逸字元亂碼。
- **進行中 job 的 `elapsed_seconds` 必須用 `time.monotonic()` 相減**（`_started_monotonic` 來自該時鐘）。曾誤用 `time.time()`，UI 顯示成「29785752 分 60 秒」；已完成的 job 走另一條路徑所以看不出來。`test_running_job_elapsed_uses_monotonic_clock` 釘住此事。
- job 本身不跨重啟，但**完成的產物會**：完成時寫 `manifest.json`，啟動時只重建「state 為 done + 產物檔存在 + session 仍在」的紀錄。

### 下載用 FileResponse

`TEMP_DIR` 每次啟動都被清空且是公開掛載，不適合放使用者最有價值的權重產物。改用 `/api/export/{job_id}/download` 回 `FileResponse`，由 Starlette 產生 RFC 5987 的 `Content-Disposition`（實測 `attachment; filename*=utf-8''best_%28PyTorch%29.onnx`），中文檔名也能正確處理。前端用 `<a download>` 而非 `responseType:'blob'`——blob 會把整個產物緩衝進 JS 記憶體。

### 相依實測結果（2026-08 於 Docker linux/amd64）

`litert-torch` 的傳遞閉包實測**不含 TensorFlow / onnx2tf / tf-keras**，numpy 維持 2.5.2、opencv 維持 5.x——當初排除 `saved_model` 路線的 numpy 衝突在此路線完全不存在。

但它有一個當初沒預期到的約束：`litert-torch 0.9.3` 要求 `torch<2.13.0`。若 Dockerfile 先從 CPU index 裝了 torch 2.13，稍後安裝 litert 時 pip 會**降級 torch，而降級版本來自預設索引（CUDA 版）**，等於把前面的 CPU 安裝整個作廢。實測差異：

| 安裝順序 | 套件數 | CUDA 套件 |
|---|---|---|
| CPU torch 2.13.0 → litert | 76 | **16** |
| CPU torch **2.12.1** → litert | 56 | **0** |

因此 Dockerfile 明確釘 `torch==2.12.1`。這造成本機 venv（2.13.0）與映像檔（2.12.1）的版本落差，是刻意的——約束來自 litert，只在有裝 litert 的地方成立。

**實測映像檔體積：3.18 GB → 0.96 GB**（加了匯出功能還縮小約 70%）。

實測匯出時間（YOLO26n，CPU）：ONNX 約 15 秒、TFLite (LiteRT) 約 90-107 秒，產出皆為單一檔案並可分別用 `onnx.checker` 與 `ai_edge_litert.Interpreter` 載入驗證。

### `YOLO_AUTOINSTALL` 必須在 `app/__init__.py` 關閉

`AUTOINSTALL` 是 ultralytics 的模組級常數，在 `import ultralytics` 當下凍結。而 `model_service.py` 第 6 行就 import 了 ultralytics、第 10 行才 import config——**放 config.py 已經太晚**。package `__init__` 保證先於任何 submodule 執行，是唯一可靠的位置。

不關掉的後果：`model.export()` 缺套件時會在請求執行緒中直接跑 `pip install`，離線會卡住、唯讀容器會失敗。驗證方式：

```bash
python -c "import app; from ultralytics.utils import AUTOINSTALL, ONLINE; print(AUTOINSTALL, ONLINE)"
```

應輸出 `False False`。

## 6. 本機資料夾掃描（LocalLibrary）

使用者把訓練成果／資料集放進專案根目錄的 `LocalLibrary/`，按下「掃描本機資料夾」看到找到的內容，勾選要載入的項目即可就地使用，**不需上傳**。

### 掃描與載入是兩個階段

`POST /local-library/scan` 純唯讀，只回報找到什麼；`POST /local-library/register` 才依 `candidate_id` 註冊使用者實際勾選的項目。

第一版是「掃描即註冊」，有兩個實務上的硬傷：`MAX_SESSIONS` 只有 3，資料夾裡若有 6 個模型，使用者拿到的是**掃描順序的前 3 個**而不是想要的那 3 個；而資料集只對整棵樹跑一次分析、取分數最高的根目錄，並存的第二個資料集會被無聲吞掉。分成兩階段之後，「找得到」與「要不要用」是兩件獨立的事，數量上限只在載入時才生效。

`tests/test_local_library_router.py::test_scan_lists_candidates_without_registering_anything` 釘住掃描的唯讀性——這是整組測試裡最該守住的一條。

### 四種來源形態

| 形態 | 探索方式 | 載入方式 |
|---|---|---|
| YOLO run 資料夾 | `index_yolo_runs_in_dir()` 遞迴走訪 | 就地引用，不複製 |
| 散落權重檔（僅頂層） | 副檔名比對 | 就地引用，不複製 |
| 訓練成果 ZIP | `peek_yolo_runs_in_zip()` 只讀中央目錄 | 解壓到 `LOCAL_LIBRARY_EXTRACT_DIR` |
| 資料集（資料夾或 ZIP） | `analyze_dataset()` 零解壓分析 | 直接沿用探索階段算好的統計 |

**ZIP 支援是後補的缺陷修正**：`.zip` 不在權重副檔名清單裡，而 `os.walk` 不會走進壓縮檔，因此第一版把訓練成果 ZIP 放進資料夾後**整包內容完全不可見、也不報錯**。實測使用者放了 `v5.zip` 與 `v8.zip`，看到的卻是先前遺留的解壓資料夾，兩者恰好同名，讓這個缺陷更難察覺。

ZIP 是唯一需要寫入磁碟的形態——權重無法從壓縮檔內直接餵給 Ultralytics。落點在受管的 `extracted_runs/local_library/`（由 ZIP 絕對路徑推導，因此同一個 ZIP 只會解壓一份），啟動時整個清空，所以「絕不寫入 `LOCAL_LIBRARY_DIR`」的保證仍然成立。

### `local_library` 必須列入 `delete_session` 的容器白名單

這是 §5 記錄過的同一個坑的第三次現形。ZIP 來源 session 的 `dir_path` 形如 `extracted_runs/local_library/<zip>/detect/<run>`，`delete_session()` 的字串切割會算出 `extracted_runs/local_library` 並 `rmtree` 整個根目錄——刪掉一個 ZIP 來源的模型，會連帶清空**其他所有 ZIP 來源模型**的權重。`test_delete_session_never_removes_container_dir[local_library]` 已加入既有的參數化清單；移除白名單項目後該測試確實會紅。


### 為什麼是固定目錄，不是「選擇資料夾」按鈕

瀏覽器基於安全機制，永遠不會把使用者選取的資料夾轉成後端可用的絕對路徑字串（`showDirectoryPicker()` 只給檔案控制代碼與資料夾名稱）。固定目錄讓**路徑完全不需要經過瀏覽器**——掃描端點不接受任何請求參數，目標永遠是伺服器端設定好的 `LOCAL_LIBRARY_DIR`。附帶好處是 Docker 支援退化成一條與 `Datasets/` 對稱的 bind mount，不需要任何雙模式或能力分級邏輯。

### reader 抽象層：ZIP 與目錄共用同一套解析邏輯

原本的偵測（`dataset_detector`）與分析（`dataset_analyzer`）直接吃 `zipfile.ZipFile`，但稽核後發現它們對 ZIP **沒有任何結構性依賴**——所有 `zip_ref` 的使用都只是「讀取某路徑的位元組」的傳遞。因此把這個能力收斂成 reader 介面：

| | ZIP 來源 | 目錄來源 |
|---|---|---|
| 建樹 | `ZipArchiveReader.build_tree()` | `DirArchiveReader.build_tree()` |
| 讀取 | `.read(path, cap)` | `.read(path, cap)` |

`_parse_data_yaml`、`_analyze_yolo`、`_analyze_coco`、`_analyze_voc` 內部所有 YOLO/COCO/VOC 解析、交叉驗證與 issue 邏輯**一行都沒改**，因為它們從頭到尾只操作 `bytes`/`str`/`VirtualTree`。`tests/test_dataset_dir.py` 有對等性測試釘住「同一份內容經兩種 reader 產出相同分析結果」。

同理，`zip_handler.extract_and_index()` 原本內嵌的 `os.walk` 索引迴圈抽成 `dir_handler.index_yolo_runs_in_dir()`，兩條路徑現在共用同一份「什麼算是有效 YOLO run」的定義。

### `_DirEntryStat` 必須有 `.file_size`（易踩的地雷）

`dataset_analyzer` 的截斷保護是：

```python
info = tree.member_by_path.get(member_path)
if info is not None and not budget.try_spend(info.file_size):
    result["truncated"] = True
```

目錄來源若把 `member_by_path` 的值塞成 `None`，那個 `is not None` 前置條件會讓整個 `TextBudget` 保護**悄悄失效**——不報錯，只是永遠不截斷。因此目錄版本存的是 `_DirEntryStat(file_size=...)`（`zipfile.ZipInfo` 剛好也有同名屬性，兩種來源共用消費端）。`test_dir_source_still_enforces_text_budget` 專門釘住這件事。

### 不落地：「直到系統關閉」的實作機制

LocalLibrary 來源的 session/dataset 只存在於記憶體的 `ACTIVE_SESSIONS`/`ACTIVE_DATASETS`，**寫檔時被過濾掉**：

- `save_sessions_to_disk()` 排除 `source == "local_library"`
- `save_datasets_to_disk()` 排除有 `source_path` 的項目（ZIP 分析出的資料集永遠沒有這個欄位，因此不需要額外標記）

重啟後自然不會被還原（從未寫入），使用者重新按一次掃描即可。過濾是**選擇性**的——一般上傳的 session/dataset 照常持久化，`test_local_library_sessions_are_not_persisted` 同時斷言這兩件事。

所有讀取端（inference、metrics、export、chart_generator）完全不用修改，因為用的是同一個 dict。

### 檔案安全

系統對 `LocalLibrary/` **只讀不寫**：

- `index_single_weight_in_place()` 不複製、不做 `.pth`→`.pt` 改名（那是使用者的檔案）
- `delete_session()` 的目錄清理被 `if "extracted_runs" in dir_path` 擋住，LocalLibrary 路徑不會命中，只移除記憶體項目
- 匯出功能安全：`export_service` 會先 `shutil.copy2` 到 `EXPORTS_DIR` 才轉檔，從不寫在原始檔旁邊
- Docker 掛載為 `:ro`

`test_delete_session_never_touches_paths_outside_extracted_runs` 涵蓋了「路徑完全不在 `extracted_runs` 之內」這個既有測試從未涵蓋的形狀。

### 已知行為

- **去重以絕對路徑為鍵**：同路徑重新訓練後，重新載入不會更新既有註冊；需手動刪除後重載或重啟。
- **散落權重檔只掃頂層**：避免把 run 資料夾內的 `weights/last.pt` 誤判成獨立權重檔。
- **資料集逐個頂層項目探測**，而非對整棵樹跑一次分析——後者只會回報分數最高的那一個，多個並存的資料集會被吞掉。根目錄本身最後才探測一次，涵蓋「data.yaml 與 train/ 直接放在頂層」的情形，並以偵測到的根路徑去重。
- **`source_type` 用字面值 `"single_weight"`**（散落權重檔）：`ModelMetricCard.jsx` 用精確比對決定「Weight Only」徽章，沒有 fallback。

## 7. 驗證評估與成果報告

讓載入的模型實際跑過資料集，算出**當下的**指標；再把結果打包成可交付的 HTML 報告。

### 這個功能填補的是一個結構性缺口

在此之前，`ACTIVE_SESSIONS` 與 `ACTIVE_DATASETS` 是兩個**永不交集**的登錄表——沒有任何端點同時接受 `session_id` 與 `dataset_id`。而消融分析頁顯示的每一個數字，都是 `/api/metrics` 從訓練當時的 `results.png` 切出來的圖片切片（見 `image_cropper.py`），不是計算結果。

後果是：兩個模型的 mAP 可能來自**不同的資料集與不同的 split**，並列比較在方法學上無效。消融研究的前提就是共同的評估協定，本功能提供那個協定。

實測差異可觀：v5 的 150-epoch 模型，`results.csv` 記錄的 mAP50 是 **0.803**（訓練時在 valid 上），本工具在 test split 實測為 **0.862**。兩者都對，但它們回答的不是同一個問題。

### 為什麼用 `model.val()` 而不自己算 mAP

自行實作 IoU 配對與 PR 積分很容易在細節上算錯（插值方式、NMS 前後順序、重複配對），而一個「自己算的、和 ultralytics 對不上的 mAP」在學術場合是負分。`val()` 另外還免費產出 confusion matrix 與 PR/F1 曲線，正好是既有 `/api/metrics` 已在展示的圖種。

代價是只支援 YOLO——SSDLite 需要另一套評估迴圈。比照匯出功能的先例，UI 上**顯示但停用並說明原因**。

### 類別詞彙比對是最重要的正確性前提

模型 checkpoint 的 `names` 與資料集 `data.yaml` 的 `names`/`nc` 若不一致，算出來的每一個數字都是垃圾，而且**不會有任何錯誤訊息**——ultralytics 只會照索引配對。

```
nc 不同      → 硬性拒絕，訊息說明雙方類別數
nc 同、名稱異 → 允許執行，但結果與報告標紅警告並列出差異
```

這不是假想風險：`model_service.py` 的 SSD 類別表寫死 12 類、`num_classes=13`，而實際的 v5 資料集是 8 類。

比對刻意排在 **validating 之前**——讓使用者等 4 分鐘才得知類別對不上是最糟的順序。

### 資料集來源決定可不可以評估

| 來源 | 可否評估 | 機制 |
|---|---|---|
| LocalLibrary 資料夾 | ✅ | 就地引用，**零複製** |
| LocalLibrary ZIP | ✅ | 只解出被評估的那**一個** split |
| 上傳的 ZIP | ❌ | 位元組已不存在 |

上傳 ZIP 走的是 Starlette 的 `SpooledTemporaryFile`，請求結束即消失（見 §4「完全不解壓縮」）。這是核心設計決策的必然代價，不是可補救的疏漏，因此 UI 給的是說明而非失敗。

ZIP 只解單一 split 是可用性關鍵：整包 4.3 GB，而 test split 只有約 240 MB。解壓內容在標記 `done` **之前**就清掉——若留到 `finally`，「狀態是 done」與「暫存已清空」之間會有時間差，觀察者看到的 done 就不誠實。

**順帶修正的資料模型缺陷**：`stats["source_path"]` 是「容器路徑 + 內層前綴」黏合後再 `normcase` 的**去重鍵**，對 ZIP 來源根本不是可開啟的路徑。因此新增 `source_container`（真實可開啟的 .zip 或資料夾）與 `source_inner_prefix` 兩個欄位，讓要讀檔的功能不必反解字串。

### 逐尺度分析：範圍的誠實界定

**有做**：每類別的框尺寸剖面（中位面積、極小框佔比），直接讀標註文字檔算出，不需推論。與每類別 AP 並排即為「AP × 中位框面積」散點圖（X 軸取對數——實測中位面積從 0.19% 到 52%，跨三個數量級，線性軸會把小物件類別擠成一團）。

**沒做**：COCO 式 small/medium/large 分桶 AP。那需要自行實作配對迴圈，與上面「不自己算 mAP」同樣的理由。此限制在結果頁與報告中都明列。

實測結果值得記錄，因為它**推翻了直覺的假設**：

| 類別 | AP@50 | 中位框面積 |
|---|---|---|
| Sooty_Mold | 0.990 | 52.2% |
| Black_Spot | 0.956 | 43.4% |
| Scale_Insect | 0.877 | 0.216% |
| Canker | 0.803 | 0.187% |
| Aphid | 0.798 | 4.76% |
| Thrips | 0.697 | 3.22% |

最小的兩個類別（Canker、Scale_Insect）表現**優於**比它們大 15–25 倍的 Thrips 與 Aphid。所以「越小越差」並不成立，弱勢類別的瓶頸另有原因。這正是這個功能的價值：它給的是真實結構，而不是預期的結論。

### 評估結果跨重啟存活，且刻意不做孤兒清除

與 `export_service` 明確不同：匯出產物只有搭配該 session 的下載連結才有意義，但評估結果是一次**測量**——指標、逐類別拆解與圖表本身就是完整資訊。

而且在本專案裡「來源 session 還在嗎」這個過濾等於**永遠刪光**：絕大多數 session 來自 LocalLibrary 掃描，依設計不落地持久化，重啟後 session id 必然不存在。一次評估要跑 4 分鐘，因為模型沒被重新載入就丟掉測量結果是不能接受的。

### 報告：一個檔案就是全部

所有圖表以 base64 data URI 內嵌，因此報告可離線開啟、可直接寄出、可放進附錄。用 `<img src="/api/...">` 的報告一離開這台機器就壞了。實測產出約 1.1 MB、零外部資源引用。

**PDF 走瀏覽器列印**（模板含 `@media print`）。不引入 `reportlab`：它沒被安裝，為一份報告增加相依不划算，而瀏覽器的列印引擎對中文與網頁版面的支援更好。這件事必須在 UI 上講清楚，否則使用者會一直找一顆不存在的「匯出 PDF」按鈕。

Jinja2 隨 torch 傳遞安裝，**沒有新增任何套件**。

報告產生時會檢查所有評估是否用同一個資料集與 split：不同就在報告開頭標紅「指標不可直接比較」。默默並列不同測試集的數字，比不做這個功能更糟。

這也是 `REPORTS_DIR` 的第一個使用者——它在 `config.py` 定義了六處但零 importer，唯一作用是開機時建立一個空資料夾。

### 效能實測（CPU）

445 張影像、2,300 個標註框：**單張推論 435 ms，全程約 4 分鐘**。原先估的 45–60 秒過度樂觀，UI 文案已依實測修正。本機 venv 與 Docker 都是 CPU-only torch（機器有 RTX 3050，但 torch 是 CPU build）。

### 新容器目錄的白名單

`extracted_runs/evaluations/` 已加入 `delete_session()` 的容器白名單。這是 §5 記錄過的同一個坑第四次現形（`datasets`／`exports`／`local_library` 各踩過一次），`tests/test_session_container_dirs.py` 的參數化清單同步補上。

## 8. Docker 環境的路徑對齊（重要）

映像檔把專案結構**攤平**成 `/app/backend` 與 `/app/frontend`，並沒有主機端的 `ShowResultsWeb/` 這一層。而 `config.py` 的 `PROJECT_ROOT` 預設值是 `BACKEND_DIR.parent.parent`：

- 主機開發：`<root>/ShowResultsWeb/backend` → `.parent` = `ShowResultsWeb` → `.parent` = `<root>` ✅
- 容器內：`/app/backend` → `.parent` = `/app` → `.parent` = `/` ❌（多往上算一層）

若不修正，`SAMPLES_DIR` 會算成 `/Datasets/samples`，而 `docker-compose.yml` 實際把資料集掛在 `/app/Datasets`。更麻煩的是 `ensure_dirs()` 會把錯誤的 `/Datasets/samples` **建成一個空目錄**，於是 `/samples` 靜態路由看起來「掛載成功」但永遠回 404，不會有明顯錯誤訊息。

因此 `docker-compose.yml` 明確設定了 `PROJECT_ROOT=/app`。**日後若調整 Dockerfile 的目錄結構或 compose 的掛載點，務必同步檢查這個變數**，並用以下方式驗證：

```bash
docker compose exec citrus-detection-app python -c "from app.core.config import SAMPLES_DIR; print(SAMPLES_DIR)"
```

輸出應為 `/app/Datasets/samples`，且 `curl localhost:8000/samples/<某張實際存在的圖>` 應回 200。

## 9. API 契約：統一信封（2026-08 正規化）

在此之前，同一個後端有四種回應形狀並存：成功時 `{"status": "success", ...payload}`；失敗時可能是 HTTP 200 帶 `{"status": "error", "message": ...}`、`HTTPException` 的 `{"detail": "..."}`、或 FastAPI 驗證失敗的 `{"detail": [{...}]}`。請求端同樣混亂：`Form(...)`、JSON body、query param 三種並用，刪除全部走 `POST /xxx/delete`。

前端的代價很具體：每個 hook 都要寫 `if (res.data.status === 'success')`，再補一段 `err.response?.data?.detail || err.message || '連線失敗'` 的三段 fallback。而「HTTP 200 但其實失敗」讓 axios 的錯誤路徑形同虛設——真正的網路錯誤與業務錯誤走完全不同的分支。

### 回應：一種形狀

```json
{"status": "success", "data": {...}, "error": null,                          "meta": {...}|null}
{"status": "error",   "data": null,  "error": {"code": ..., "message": ...}, "meta": null}
```

四個欄位**永遠存在**。這也是移除 `response_model_exclude_unset=True` 的理由：那個選項會把未賦值的 key 從 JSON 靜默裁掉，前端拿到 `undefined` 而不是可偵測的錯誤（原 CLAUDE.md 硬規則 12 的地雷，現已從根本消除）。

實作在 [app/core/envelope.py](../ShowResultsWeb/backend/app/core/envelope.py)：`ApiResponse[T]` 泛型模型 + `ok()` helper + `ApiException` + 四個全域 exception handler（`ApiException` / `RequestValidationError` / `StarletteHTTPException` / `Exception`）。

### 錯誤碼與 HTTP 狀態（唯一真相）

| code | HTTP | 用於 |
|---|---|---|
| `validation_error` | 400 | 請求格式或欄位不合法（含 FastAPI 原本回 422 的驗證失敗） |
| `not_found` | 404 | session / dataset / job / report / weight 不存在 |
| `conflict` | 409 | 掃描或分析正在進行中 |
| `capacity_reached` | 409 | 已達 `MAX_SESSIONS` |
| `unsupported_format` | 415 | 副檔名不支援 |
| `precondition_failed` | 422 | 格式正確但語意上不能執行（類別數不符、資料集無影像位元組、非 YOLO 架構） |
| `queue_full` | 429 | 匯出／評估佇列已滿 |
| `internal_error` | 500 | 未預期例外 |
| `dependency_unavailable` | 503 | 資料庫等可選相依不可用 |

分界線：**400 = 請求本身壞掉，422 = 請求沒問題但這件事現在不能做。** FastAPI 預設把請求驗證失敗回成 422，這裡刻意改回 400，好讓 422 專門承載「使用者需要原封不動看到的那句說明」。

### 請求：JSON body + 正確的動詞

除三個**真正的檔案上傳**（`/api/upload-model`、`/api/upload-dataset`、`/api/inference`，維持 multipart）之外，所有寫入端點吃 JSON body，GET 用型別化 query param，刪除用 `DELETE` + path id。

| 舊 | 新 |
|---|---|
| `POST /delete-session`（Form） | `DELETE /sessions/{session_id}` |
| `POST /delete-dataset`（Form） | `DELETE /datasets/{dataset_id}` |
| `POST /export/{id}/delete` | `DELETE /export/{id}` |
| `POST /evaluations/{id}/delete` | `DELETE /evaluations/{id}` |
| `POST /reports/{id}/delete` | `DELETE /reports/{id}` |
| `POST /set-device`、`/export`、`/evaluations`、`/update-session-name`（Form） | 同路徑，改吃 JSON body |
| `POST /inference?session_id=&conf=` | 兩個參數改成 multipart 表單欄位 |

`/api/upload-zip` 這個向後相容別名一併移除。

`/inference` 的參數搬進 body 是刻意的：那個端點本來就必須是 multipart，把參數留在 query 等於同一個請求有兩套參數傳遞方式。統一後的規則沒有例外——**POST 的參數都在 body 裡**。

### 契約由測試強制，不靠自律

正規化最容易失敗的方式不是一開始做錯，而是慢慢退化。[tests/test_envelope.py](../ShowResultsWeb/backend/tests/test_envelope.py) 走訪 `app.routes` 本身，對每個 `/api` 路由斷言 `response_model` 是 `ApiResponse[...]`、且沒有任何路由還在用 `exclude_unset`；再加上執行期的形狀檢查（成功與失敗的 key 集合必須相同、404 必須真的是 404）。

另外 `tests/apitest.py` 的 `data()` / `error()` 兩個 helper 讓**每一支路由測試都順帶驗一次信封**，契約因此被整個測試套件反覆檢查，而不是靠單獨一支測試孤軍守著。

> 走訪路由有個容易踩空的地方：FastAPI 0.141 起 `include_router()` 掛上的是 `_IncludedRouter` 容器，不再把 `APIRoute` 攤平進 `app.routes`，而容器底下的 route 只帶未加前綴的路徑。直接過濾頂層會**靜默**得到空清單、測試變成空跑——所以 `test_there_are_api_routes_to_check` 專門擋這件事。

### 前端：單一客戶端

[frontend/src/api/client.js](../ShowResultsWeb/frontend/src/api/client.js) 用一個 axios interceptor 把信封拆掉：成功回 `data`，失敗**丟出** `ApiError { code, message, details, status }`。於是 hook 的錯誤處理從「三種形狀各判一次」收斂成一個 `try/catch`。

唯一的特例：`axios.isCancel` 的取消物件必須原樣穿透——`useLiveDemoInference` 依賴它靜默忽略被 `AbortController` 取消的請求，包成 `ApiError` 會讓使用者看到假的錯誤訊息。

## 10. 權重登錄簿（資料庫）

§2 原本明列「無資料庫」是刻意設計。那個決策對**執行期狀態**仍然成立——載入了哪些模型、選了哪個裝置，重啟後本來就該重來。資料庫解決的是另一件事。

### 這個功能填補的缺口

- `session_id` 是 `run_<uuid8>`，**每次掃描／上傳都重新產生**，且 LocalLibrary 來源的 session 依設計不落地（§6）。重啟後「這顆權重我測過、超參數是什麼、當時實測多少」全部消失。
- `args.yaml` 的完整超參數在 `dir_handler.py` 只取出 `epochs`/`optimizer`/`model` 三個鍵，其餘**當場丟棄**。實測本專案的 args.yaml 有 **116 個鍵**——被丟掉的 113 項（lr0、mosaic、patience、augment 各項…）正是消融研究要比較的東西。
- 一次評估要跑數分鐘，結果只以 job manifest 存在，無法跨權重查詢、排序或比較。

### 身分是內容雜湊，不是 session_id

```
weights            一顆權重檔一列，主鍵 = 檔案內容的 SHA-256
  ├── training_runs   訓練當時的紀錄（完整 args.yaml + results.csv 最後一列），1:1
  └── evaluations     本系統實測出來的每一次評估，1:N
```

用 `session_id` 當 key 會讓同一顆 best.pt 每重掃一次就多一列，帳本一週後就沒法看。內容雜湊還有個附帶好處：同一顆權重無論是從資料夾就地引用、還是從 ZIP 解壓出來，都收斂到同一列。

**SHA-256 只在註冊／上傳時算，絕不在 `discover()` 裡算**——掃描是唯讀探索、要維持秒級（實測 0.66 秒掃完 126 個檔案），對每個 `.pt` 做雜湊會讓它變成分鐘級，而使用者按下掃描時根本還沒決定要不要用。評估時的雜湊則放在背景 worker，不佔請求路徑。

### 雙軌：PostgreSQL 與 SQLite

`DATABASE_URL` 未設定時走 SQLite 檔案（`extracted_runs/registry.db`），`docker-compose.yml` 注入 PostgreSQL 連線字串。因此**模型定義只能用 SQLAlchemy 通用型別**（`JSON`/`Float`/`String`）；`JSONB`、`ARRAY` 只有 Postgres 有，用了就毀掉雙軌。

好處是本機開發、CI 與 pytest 全部零設定；代價是「CI 跑的不完全等於出貨的」，所以 CI 另有一輪把 `DATABASE_URL` 指向 Postgres service container 的執行，外加一個會因失敗而中斷的建表檢查。

### 資料庫是可選的（這是「附加層」的實作定義）

上傳一顆模型不該因為 PostgreSQL 還沒暖機完成而失敗。因此：

- `init_db()` 重試若干次後放棄，**應用程式照常啟動**，永不拋例外。
- 所有寫入路徑在不可用時靜默略過，且每個寫入函式都吞掉自己的例外。
- 讀取端點回 **503 + `dependency_unavailable`**，不是 500——那不是伺服器出錯，是可選相依不在。前端據此顯示「登錄簿離線」而不是紅色錯誤。
- `/api/registry/stats` 是唯一不做這個檢查的端點：它是前端判斷登錄簿在不在的依據，自己絕不能因資料庫掛掉而失敗（執行期失敗時回 200 + `available: false`）。

**「啟動時連不上」與「跑到一半才掛掉」是兩條不同的路徑**，第二條很容易被漏掉：`is_available()` 只反映啟動當下的狀態，資料庫之後才死掉時那個旗標仍是 True，查詢會一路打到 driver 才炸開，最後被通用 handler 收成 HTTP 500 `internal_error`。這是實測抓到的缺陷——`docker compose stop db` 之後 `/api/registry/weights` 回的是 500。

修法是把連線層級的失敗包成具名的 `RegistryUnavailable`（在 `session_scope` 內攔截 `SQLAlchemyError`），由 `main.py` 註冊的 handler 翻成 503；同時把 `_AVAILABLE` 拉下來，後續請求走快路徑而不必每次等 TCP 逾時。

**資料庫回來後會自動恢復**：`_require_db()` 在不可用時先試 `init_db(retries=1)`，成功就繼續。否則使用者得重啟整個應用才能再用登錄簿，而那與「資料庫是可選相依」的主張矛盾。實測 `docker compose stop db` → 503 → `docker compose start db` → 無需重啟應用即恢復 200，且資料完整。

`tests/test_registry_routes.py::test_runtime_failure_is_503_not_500` 釘住這條路徑。連帶地，測試用的 `disable_for_tests()` 必須設一個獨立的 `_FORCE_OFFLINE` 旗標而不是單純把 `_AVAILABLE` 設 False——否則自動重連會成功，降級路徑根本測不到。

三個寫入接點：`sessions.py` 的兩條上傳路徑、`library_scanner.register()`、`evaluation_service._process_job()` 完成時。**全部在鎖之外**——資料庫可能在網路彼端，在 `SESSIONS_LOCK` / `EVAL_JOBS_LOCK` 內等待往返會讓所有推論請求排隊。

> 開發時漏掉 `library_scanner` 那個接點，單元測試全過（它們直接測 service 層），是 E2E 抓出來的：「權重已入帳」直接失敗。這正是端到端測試要對照**外部可驗證事實**而非後端自己欄位的理由。

啟動還原時會補寫尚未入帳的評估（`record_evaluation` 以 `job_id` upsert），讓「評估完成當下資料庫剛好不可用」能自我修復。

### 刻意不引入 Alembic

schema 用 `create_all()` 建立，日後只做**加欄位**的相容變更。對單機、單使用者、資料可重建（重新掃描＋重跑評估）的工具，一套 migration 框架的維護成本高於它解決的問題。`schema_meta` 表記版號，未來若真的需要破壞性變更，至少能明確偵測並要求使用者重建，而不是靜默給出錯誤結果。

## 11. Micro-Accuracy（Jaccard index）

公式依《效能指標定義與評測方法》§2 的 TN=0 簡化定義（物件偵測的無效背景框數無限且不可統計）：

```
Precision = TP / (TP + FP)
Recall    = TP / (TP + FN)
F1        = 2·P·R / (P + R)
Accuracy  = TP / (TP + FP + FN) = 1 / (1/P + 1/R − 1)
```

最後一項就是 Micro-Accuracy / Jaccard index——TN=0 時，準確率的定義自然化簡成交集除以聯集，兩個名字指的是同一個量。

「Micro」是先把所有類別的 TP/FP/FN **加總**再相除，而不是各類別先算比率再平均（後者是 macro）。本資料集的 Scale_Insect 有 1,586 個框、Black_Spot 只有 25 個，macro 會讓後者擁有與前者相同的話語權；micro 反映的是整個測試集上的整體正確比例。

### 資料來源與**已知落差**

TP/FP/FN 取自 ultralytics `val()` 累積的混淆矩陣（`results.confusion_matrix.matrix`，於 `finalize_metrics()` 中無條件指派）。矩陣是 `(nc+1)×(nc+1)`，慣例 `matrix[預測類別, 真實類別]`，最後一列／行是 background。

**該矩陣的配對門檻是 ultralytics 的預設值 conf=0.25 / IoU=0.45，而指標定義文件寫的是 IoU ≥ 0.5。** 這 0.05 的落差無法在不改寫 ultralytics 內部呼叫的前提下消除——`process_batch` 的 `iou_thres` 在 `models/yolo/detect/val.py` 中是寫死的，而為了它去 monkeypatch 套件內部，違反本專案「不與 ultralytics 內部細節耦合」的既有原則。

因此選擇**把實際使用的門檻一起存進每一筆紀錄**（`conf_threshold` / `iou_threshold` 兩欄），並在 UI 與報告中明寫，而不是宣稱 0.5 卻用 0.45 去算。這是誠實界定範圍，不是疏漏。

同樣重要的是：**Micro-Accuracy 是門檻相依的單點量測，mAP 是對所有門檻積分的曲線下面積**，兩者不可直接並列解讀。UI 與報告都標註了這一點。

### 正確性如何被證明

- `tests/test_micro_accuracy.py` 餵手算過答案的合成矩陣（完美→1.0、全錯→0.0、含 background、全零→`None`、指定 nc…）。
- **恆等式交叉驗算**：對同一組 TP/FP/FN，`TP/(TP+FP+FN)` 與 `1/(1/P + 1/R − 1)` 必須給出同一個數字。兩條算式完全不同，任何一邊寫錯（例如 FP/FN 的行列取反）都會立刻失敗。實測兩邊都是 0.1934。
- **E2E 的硬不變量**：`TP + FN` 必須等於該 split 的標註框總數。每個 GT 框必定落在其真實類別那一欄的某一格（配對到就落 `M[預測,真實]`、沒配對到就落 `M[background,真實]`），所以真實類別各欄的總和就是 GT 總數。實測 777 + 1,523 = 2,300，與 E2E 自己數出的 2,300 相符。

> 這條不變量第一次跑是 2,300 vs 2,302，差 2。追下去發現 v5 資料集的 `test_0175.txt` 有 4 列但只有 2 列相異，而 ultralytics 在載入標註時會做 `np.unique(lb, axis=0)`。**不變量與實作都是對的，錯的是 E2E 的數法**——E2E 已改為去重後計數，並把這件事寫進註解。

分母為 0 時回 `None` 而不是 0.0：「沒有東西可算」與「算出來是零」是兩件不同的事，混為一談會在帳本裡留下假的 0 分紀錄。

## 12. 已知限制

- E2E 測試有兩支，都需要後端已在執行、且在缺素材時優雅跳過；CI 僅涵蓋單元測試與前端編譯檢查，不含端到端流程。
  `e2e_tests/e2e_local_library.py` 是主力，用 `LocalLibrary/` 內的真實檔案跑完 16 個階段（API 信封契約、掃描唯讀性、勾選載入、使用者檔案指紋、指標圖、推論對照真實標註、資料集分析對照 ZIP 實際成員數、ONNX/TFLite 匯出、驗證評估、成果報告、登錄簿入帳與雜湊對照、指標交叉驗算、帳本存活性、刪除安全性），實測 98 項全通過、耗時約 94 秒；`e2e_tests/e2e_test.py` 是早期的上傳流程煙霧測試，需要 `E2E_ASSETS_DIR` 指向特定佈局的素材夾。
- **Micro-Accuracy 的 IoU 門檻是 0.45 而非規格文件的 0.5**，因為它來自 ultralytics 寫死的混淆矩陣參數。實際使用的門檻已隨每筆紀錄存下並在 UI／報告標明，詳見 §11。
- 登錄簿的排序與「每顆權重的最佳指標」彙總在 **Python 端**做（過濾仍在 SQL）。單機使用者手上數十顆權重的規模下這是划算的取捨；若日後筆數成長到數千，需要改寫成跨方言都成立的 SQL 彙總。
- 登錄簿**沒有 migration 機制**（刻意，見 §10）。schema 破壞性變更時 `schema_meta` 只會印警告，需要手動刪除資料庫檔案／volume 重建。
- 刪除 session 或評估 job **不會**連帶刪除登錄簿紀錄，反之亦然——這是刻意的生命週期分離，但也代表登錄簿會單調成長，需要使用者自行從登錄簿分頁清理。
- 匯出功能只支援 YOLO；SSDLite（`.pth`）的卡片會停用並說明原因（依 `model_arch` 判斷，不能依副檔名——上傳時 `.pth` 會被改名成 `.pt`）。
- 匯出目前只出 FP32。`quantize` 參數已從 API 打通並用伺服器端白名單驗證，但白名單暫時只含 `32`/`None`：
  ONNX 的 FP16 轉換失敗在 ultralytics 內是**被捕捉並警告**的，等於會靜默交出一個標著 FP16 的 FP32 檔。
- COCO 與 Pascal VOC 的資料集解析未經真實素材驗證（本專案只有 YOLO 資料集），僅依規格實作；UI 已明確標示。
- 前端沒有測試框架（`package.json` 無 `test` script，CI 只做 build），前端的驗證僅有 `npm run build` 與人工走查。
- 資料集分析是單一同步請求（實測 16,043 個成員約 1.1 秒）。日後若在前面加反向代理，預設約 60 秒的逾時可能截斷超大資料集；回應中的 `analysis_ms` 可用來觀測這個天花板。
- LocalLibrary 掃描在 Docker 下完全依賴 `docker-compose.yml` 的 `./LocalLibrary:/app/LocalLibrary:ro` 掛載。若忘記這條掛載，容器內的目錄是空的，掃描會回報「找不到可辨識內容」而**不是錯誤**——無法從容器內部可靠判斷一個目錄是不是真的 bind mount。
- LocalLibrary 目錄走訪用 `follow_symlinks=False` 避免遞迴逃出根目錄，但樹內的**檔案**符號連結仍會被 `open()` 跟隨讀取。這在「單一本機操作者放自己的檔案」的前提下是可接受的；若部署模型改成多使用者或對外服務，需重新評估。
- YOLO 推論已用真實權重驗證過（實測 `POST /api/inference` 回 `status: success`，CPU）；**SSDLite 推論路徑仍未用真實 `.pth` 驗證**。完整端到端請跑 `e2e_tests/e2e_test.py`（設好 `E2E_ASSETS_DIR`）。
