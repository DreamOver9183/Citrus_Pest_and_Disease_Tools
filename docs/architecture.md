# 系統架構文件

本文件記錄柑橘病蟲害雙軌診斷平台（YOLO / SSDLite）目前的系統架構，供後續開發與維護參考。內容對應 2026-08 完成的重構（測試安全網 → 後端強化 → API 型別化 → 前端拆分）之後的狀態。

## 1. 部署拓樸

單一 Docker image：多階段建置 (`Dockerfile`) 先用 `node:20-alpine` 建置 React SPA (`npm run build` → `frontend/dist`)，再複製進 `python:3.12-slim`，FastAPI 用 `StaticFiles(html=True)` 掛載 `frontend/dist` 到 `/`。前後端同源、單一 port（8000）對外，不需額外反向代理。`docker-compose.yml` 把 `Datasets/`（唯讀）與 `ShowResultsWeb/backend/extracted_runs/`（讀寫）掛成 volume 做持久化。

## 2. 後端（`ShowResultsWeb/backend/`）

```
main.py                        FastAPI 入口：CORS、路由註冊、靜態掛載、startup 清理
app/schemas.py                 各路由共用的 Pydantic 回應模型（供 /docs 顯示完整 schema）
app/core/config.py             唯一路徑/設定真相來源（env override + 預設值），ensure_dirs()
app/routers/
  sessions.py                  session CRUD + 模型上傳（ZIP / 單一權重檔）
  datasets.py                  資料集上傳分析 / 列表 / 刪除
  exports.py                   模型格式轉換：能力查詢 / 送出 job / 輪詢 / 下載 / 刪除
  local_library.py             本機資料夾：路徑查詢 / 掃描（唯讀）/ 載入勾選項目
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
  model_service.py             ModelManager 單例：同時只保留一個模型在記憶體
  device_service.py            裝置探測結果快取（30s TTL）
app/utils/
  zip_handler.py                ZIP 安全解壓（路徑穿越防禦）+ YOLO run 索引
  dataset_zip.py               資料集 ZIP 唯讀層：虛擬目錄樹、大小上限、帶 cap 的成員讀取
  dataset_dir.py               資料集「真實目錄」唯讀層（dataset_zip 的目錄對應版本）
  dir_handler.py               目錄的 YOLO run 索引與就地權重索引（zip_handler 的目錄對應版本）
  image_cropper.py             results.png 網格像素裁切（2x5 grid）
  device_probe.py              torch/psutil 偵測 CPU/CUDA/MPS
tests/                         pytest 單元測試（zip_handler / image_cropper / session_manager /
                               dataset_analyzer / dataset_manager / dataset_dir /
                               dir_handler / export_service / export_routes /
                               local_library_router / session_container_dirs，共 160 項）
```

### 關鍵設計決策（有意保留，非缺陷）

- **`ModelManager` 單例、同時只駐留一個模型**：切換模型時主動 `del` + `gc.collect()` + `torch.cuda.empty_cache()`，避免多個大型模型疊加造成 OOM。這代表併發測試不同模型時會互相搶佔、觸發重新載入，是刻意的記憶體安全取捨，不會修改。
- **無資料庫**：Session 狀態 = 記憶體 dict（`ACTIVE_SESSIONS`）+ JSON 快照（`sessions.json`）+ 檔案系統路徑，啟動時以「權重檔是否存在」過濾幽靈 session。對單機、單使用者的本地展示工具而言是合理設計。
- **無身分驗證**：工具定位為本地離線展示，非對外服務。
- **`ACTIVE_SESSIONS` 併發保護**：所有跨執行緒池的讀-改-寫操作都透過 `session_manager.SESSIONS_LOCK`（`threading.RLock`）保護，對齊 `ModelManager` 既有的鎖定模式。
- **API 回應契約**：所有路由都定義了 `response_model`（`app/schemas.py`），搭配 `response_model_exclude_unset=True` 讓錯誤回應（僅 `status`/`message`）與成功回應維持原本的最小化 JSON 形狀，不因型別化而改變前端可見的回應內容。

## 3. 前端（`ShowResultsWeb/frontend/src/`）

```
main.jsx → App.jsx                     四分頁 SPA：模型與裝置 / 消融分析 / 即時診斷 / 資料集
                                       （模型匯出是 session 卡片上的動作，不另開分頁）
context/
  ExperimentContext.jsx                組合層 Provider：組合六個獨立 hook，對外仍暴露單一 useExperiment()
  hooks/
    useSessions.js                     Session 清單、CRUD、載入狀態
    useDeviceControl.js                裝置清單與目前選用裝置
    useLiveDemoState.js                LiveDemo 分頁的推論結果/已上傳檔案狀態（跨分頁切換不遺失）
    useDatasetState.js                 資料集分析結果與進行中的請求（跨分頁切換不遺失）
    useModelExport.js                  匯出 job 狀態與輪詢迴圈（跨分頁切換不遺失）
    useLocalLibrary.js                 本機資料夾路徑、候選清單與勾選狀態（跨分頁切換不遺失）
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
  Lightbox.jsx                         自訂 Modal：滾動鎖定、拖曳邊界、Esc 關閉
```

無路由庫（純 tab 切換）、狀態管理以 axios + hooks/Context 為主，沒有導入 React Query/SWR 這類快取層。
唯一的第三方視覺化依賴是 **recharts（釘在 `~2.12.7`）**——釘 2.x 是因為 recharts 3.x 目標為 React 19，而本專案是 React 18.3.1，且 `package-lock.json` 未進版控、CI 跑裸 `npm install`，`^` 範圍會在某天無關的 PR 上靜默升 major。

### Context 組合模式

`ExperimentContext.jsx` 本身不持有業務狀態，而是組合 `useSessions`、`useDeviceControl`、`useLiveDemoState`、`useDatasetState`、`useModelExport`、`useLocalLibrary` 六個獨立 hook 的回傳值，攤平後透過同一個 `useExperiment()` 對外暴露。這是刻意的 adapter 設計：既有元件（`SystemSpecs.jsx`、`LiveDemo.jsx`、`MetricDashboard.jsx`、`App.jsx`）呼叫 `useExperiment()` 的方式完全不需變動，同時六個 hook 各自獨立、可單獨測試或重用。`deleteSession` 是唯一的例外——組合層額外包了一層，在刪除後若已無任何 session，會呼叫 `setActiveTab('init')`（此邏輯原本就存在，只是搬到組合層，因為 `activeTab` 屬於頁面導覽狀態、不屬於任一個子 hook）。

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

## 7. Docker 環境的路徑對齊（重要）

映像檔把專案結構**攤平**成 `/app/backend` 與 `/app/frontend`，並沒有主機端的 `ShowResultsWeb/` 這一層。而 `config.py` 的 `PROJECT_ROOT` 預設值是 `BACKEND_DIR.parent.parent`：

- 主機開發：`<root>/ShowResultsWeb/backend` → `.parent` = `ShowResultsWeb` → `.parent` = `<root>` ✅
- 容器內：`/app/backend` → `.parent` = `/app` → `.parent` = `/` ❌（多往上算一層）

若不修正，`SAMPLES_DIR` 會算成 `/Datasets/samples`，而 `docker-compose.yml` 實際把資料集掛在 `/app/Datasets`。更麻煩的是 `ensure_dirs()` 會把錯誤的 `/Datasets/samples` **建成一個空目錄**，於是 `/samples` 靜態路由看起來「掛載成功」但永遠回 404，不會有明顯錯誤訊息。

因此 `docker-compose.yml` 明確設定了 `PROJECT_ROOT=/app`。**日後若調整 Dockerfile 的目錄結構或 compose 的掛載點，務必同步檢查這個變數**，並用以下方式驗證：

```bash
docker compose exec citrus-detection-app python -c "from app.core.config import SAMPLES_DIR; print(SAMPLES_DIR)"
```

輸出應為 `/app/Datasets/samples`，且 `curl localhost:8000/samples/<某張實際存在的圖>` 應回 200。

## 8. 已知限制

- E2E 測試（`e2e_tests/e2e_test.py`）需要真實模型/資料集檔案（`.gitignore` 排除、機器相依），未設定 `E2E_ASSETS_DIR` 時會優雅跳過；CI 僅涵蓋單元測試與前端編譯檢查，不含端到端流程。
- 匯出功能只支援 YOLO；SSDLite（`.pth`）的卡片會停用並說明原因（依 `model_arch` 判斷，不能依副檔名——上傳時 `.pth` 會被改名成 `.pt`）。
- 匯出目前只出 FP32。`quantize` 參數已從 API 打通並用伺服器端白名單驗證，但白名單暫時只含 `32`/`None`：
  ONNX 的 FP16 轉換失敗在 ultralytics 內是**被捕捉並警告**的，等於會靜默交出一個標著 FP16 的 FP32 檔。
- COCO 與 Pascal VOC 的資料集解析未經真實素材驗證（本專案只有 YOLO 資料集），僅依規格實作；UI 已明確標示。
- 前端沒有測試框架（`package.json` 無 `test` script，CI 只做 build），前端的驗證僅有 `npm run build` 與人工走查。
- 資料集分析是單一同步請求（實測 16,043 個成員約 1.1 秒）。日後若在前面加反向代理，預設約 60 秒的逾時可能截斷超大資料集；回應中的 `analysis_ms` 可用來觀測這個天花板。
- LocalLibrary 掃描在 Docker 下完全依賴 `docker-compose.yml` 的 `./LocalLibrary:/app/LocalLibrary:ro` 掛載。若忘記這條掛載，容器內的目錄是空的，掃描會回報「找不到可辨識內容」而**不是錯誤**——無法從容器內部可靠判斷一個目錄是不是真的 bind mount。
- LocalLibrary 目錄走訪用 `follow_symlinks=False` 避免遞迴逃出根目錄，但樹內的**檔案**符號連結仍會被 `open()` 跟隨讀取。這在「單一本機操作者放自己的檔案」的前提下是可接受的；若部署模型改成多使用者或對外服務，需重新評估。
- YOLO 推論已用真實權重驗證過（實測 `POST /api/inference` 回 `status: success`，CPU）；**SSDLite 推論路徑仍未用真實 `.pth` 驗證**。完整端到端請跑 `e2e_tests/e2e_test.py`（設好 `E2E_ASSETS_DIR`）。
