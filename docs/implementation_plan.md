# YOLO 跨模型實驗追蹤與即時推論展示平台 (FastAPI + React SPA)

本專案採用前後端分離架構，旨在為評審展現極致流暢、防護嚴密的本地離線 YOLO 實驗追蹤與即時推論 Demo 系統。本計畫已針對性能優化、事件循環併發、影像快取失效、記憶體安全、Lightbox 滾動穿透與現場互動性進行深度重構。

---

## User Review Required

> [!IMPORTANT]
> **主要技術更新與規避方案**
> 1. **Lightbox 滾動穿透與拖曳出界防禦 (Scroll Leak & Boundary Defense)**：
>    - **防止滾動穿透 (Scroll Lock)**：在 `Lightbox.jsx` 中，當 Modal 開啟時，透過 React `useEffect` 動態設定 `document.body.style.overflow = "hidden"`，關閉時還原 `unset`。這能徹底防止評審使用滾輪縮放圖片時，背景的主網頁同步捲動的劣質體驗。
>    - **視窗鎖定關閉按鈕 (Fixed Close Button)**：將關閉按鈕 (X) 設置為 `fixed top-6 right-6 z-[60]`，直接以視窗 (Viewport) 為基準固定，不隨圖片縮放與拖曳移動，確保評審隨時能看得到並點擊關閉。
>    - **拖曳邊界限制 (Boundary Constraints)**：限制圖片拖動範圍，防止圖片被完全拖出視窗外找不到；並支援點擊暗色遮罩背景或按下 `Esc` 鍵一鍵關閉，提供頂級的互動防呆機制。
> 2. **檔名衝突與快取失效防禦 (Collision & Cache Busting Defense)**：
>    - **後端防衝突**：將推論結果儲存為 `pred_{uuid.uuid4().hex}_{filename}`，徹底避免多次點擊或多人同時上傳同名檔案時的檔案覆寫衝突。
>    - **前端快取失效 (Cache Busting)**：前端載入圖片 URL 時，自動加上時間戳記（例如 `?t=17166123456`），強迫瀏覽器繞過快取、重新解碼，保證點擊 Sample 卡片或重複上傳同張圖時能 100% 更新渲染。
>    - **垃圾清理機制**：後端在啟動時會自動清空 `extracted_runs/temp_output/`，防範磁碟空間暴增。
> 3. **事件循環阻塞防禦 (Event Loop Blocking Defense)**：
>    - **普通同步 `def` 路由**：將 `/api/inference` 與 `/api/metrics` 宣告為 `def` 路由而非 `async def`，使 FastAPI 自動在執行緒池 (Thread Pool) 中處理 PyTorch 推論與圖片裁剪，防止主事件循環被阻塞。
> 4. **效能優化 (靜態檔案掛載)**：捨棄 Base64 編碼，後端透過 FastAPI `StaticFiles` 掛載本地暫存目錄 `extracted_runs/temp_output/`。前端直接透過 URL 請求，善用瀏覽器的影像解碼與快取優化。
> 5. **全域守衛與 Loading 骨架屏**：建立 React `ExperimentContext` 全域狀態管理器。在 ZIP 檔解壓完成前，強制鎖定指標看板與 Live Demo 介面，並以骨架屏 (Skeleton) 視覺引導，避免非法路徑請求。
> 6. **單例模型置換代理**：為防範 YOLO 模型（特別是 Large 版本）快取過多導致 OOM 崩潰，改用 `ModelManager` 單例代理器。切換模型時自動銷毀舊模型實例並主動觸發 `gc.collect()` 垃圾回收。
> 7. **專家精選樣本庫 (Quick Samples)**：預載 3~4 張柑橘典型病徵相片，一鍵即時推論，解決現場尋找測試圖的不便。
> 8. **圖片放大鏡與全螢幕按鈕改版 (Image Magnifier & Fullscreen Button)**:
>    - **預設圖片放大鏡濾鏡 (Magnifying Glass Lens)**：滑鼠移入標註結果圖片時，會在游標處生成一個帶有橘色邊框的圓形放大鏡。透過 React 監聽滑鼠座標，動態調整背景圖片位移與背景縮放尺寸，實現極致平滑的局部放大。這能顯著提升對柑橘微小病徵（如薊馬、蚜蟲活體）的檢視體驗。
>    - **全螢幕放大按鈕 (Fullscreen Lightbox Button)**：取消點擊圖片本身直接放大彈窗的設計。改在卡片頂部狀態列中，在「對照原始圖」旁並排新增一個「全螢幕放大」按鈕。點擊後才呼叫原有的 Lightbox 大圖彈窗。
> 9. **數據圖表頁面底部新增「回到上方」按鈕 (Back to Top Button)**:
>    - 在「數據圖表」分頁最底部（並排圖表下方），新增一個置中的磨砂玻璃「回到最上方」按鈕，並引入 `ArrowUp` 箭頭圖示。
>    - 點擊按鈕時觸發 `window.scrollTo({ top: 0, behavior: 'smooth' })` 平滑滾動回到頁首，提升在多個大圖表滑動時的導覽流暢度。
> 10. **可收折指標側邊欄 (Collapsible Indicators Sidebar)**:
>    - 在「數據圖表」分頁中，將指標勾選側邊欄改為**可折疊式 (Collapsible)**，由 React 狀態 `isSidebarOpen` 控制。
>    - 展開時側邊欄佔用 `lg:col-span-1` (25% 寬度)，圖表區佔用 `lg:col-span-3` (75% 寬度)。
>    - 折疊收納時，側邊欄完全隱藏，圖表展示區自動寬度過渡至 `lg:col-span-4` (100% 滿版)，提供更為宏觀、清晰的消融圖像對照體驗。
>    - 折疊後在視窗左側邊緣懸浮展示一個醒目的橙色漸層「指標選單」滑動抽屜按鈕，隨時可一鍵點擊復原展開。
> 11. **遺留資料夾自動清理 (Legacy Folders Cleanup)**：
>    - **問題來源**：在先前的開發過程中，上傳 ZIP 檔案採用隨機的 `run_xxxx` 作為解壓目錄名。由於 `./ShowResultsWeb/backend/extracted_runs` 目錄被掛載為 Docker Volume 進行資料持久化，導致這些過往測試的遺留資料夾依然留在主機磁碟上，並呈現在資源總管檔案樹中。
>    - **清理策略**：除手動清理主機上遺留的舊 `run_*` 目錄外，我們在後端 `main.py` 的啟動事件 `startup_init()` 中新增自動清理機制。該機制會自動掃描並刪除 `extracted_runs/` 目錄下所有名稱符合 `run_` 加上 8 碼十六進位字元（符合正則表達式 `^run_[a-f0-9]{8}$`）的遺留暫存資料夾，保持資源總管的整潔。


---

## Proposed Changes

---

### [Backend: FastAPI High-Performance Engine]

#### [MODIFY] [main.py](file:///d:/Download/Citrus%20Pest%20and%20Disease%20Detection/ShowResultsWeb/backend/main.py)
FastAPI 服務中樞：
- **啟動自動清理**：
  - 在 `startup` 事件中自動清理 `extracted_runs/temp_output/`。
  - 新增對 `extracted_runs/` 下名稱符合 `run_[a-f0-9]{8}` 格式之遺留資料夾的掃描與自動清理，確保主機與容器內資源總管之整潔。
- **執行緒池併發設計**：
  - `POST /api/upload-zip`：使用 `async def`。
  - `GET /api/metrics`：使用 **`def`**，使 FastAPI 在執行緒池中處理 Pillow 圖片裁剪。
  - `POST /api/inference`：使用 **`def`**，在執行緒池中執行 PyTorch 的 `model.predict()` 推論運算。
- **靜態資源掛載**：
  - `app.mount("/static", StaticFiles(directory="extracted_runs/temp_output"), name="static")`
  - `app.mount("/samples", StaticFiles(directory="Datasets/samples"), name="samples")`

#### [NEW] [model_manager.py](file:///d:/Download/專題/utils/model_manager.py)
單例模型載入與記憶體回收代理：
- 設計 `ModelManager` 類別：
  - 維持單一成員變數 `self.current_model = None`。
  - 提供 `load_model(model_path)` 方法：若新載入路徑與當前不同，主動 `del self.current_model` 釋放資源，調用 `gc.collect()` 與 `torch.cuda.empty_cache()`（若可用），最後載入新 YOLO 模型。

#### [NEW] [zip_handler.py](file:///d:/Download/專題/utils/zip_handler.py)
解包與自動目錄結構對齊：
- 提供 `extract_and_index(zip_path, extract_to)`。
- 尋找 `args.yaml` 與 `best.pt` 權重。
- 自動將子目錄對齊到：`YOLO26l`、`YOLO26n`、`YOLO26n+P2`。

#### [NEW] [image_cropper.py](file:///d:/Download/專題/utils/image_cropper.py)
`results.png` 像素級裁剪落盤模組：
- 解析 2400x1200 解析度之 YOLO 繪圖網格。
- 裁剪後儲存至 `extracted_runs/temp_output/[model_name]_[metric_name].png`，回傳檔名以利前端 URL 請求。

---

### [Frontend: React SPA Application]

#### [NEW] [ExperimentContext.jsx](file:///d:/Download/專題/frontend/src/context/ExperimentContext.jsx)
React 全域狀態管理器：
- 維持全域狀態：`isUnzipped`（解包狀態）、`modelMapping`（模型路徑與超參數對應）、`activeTab`。

#### [NEW] [App.jsx](file:///d:/Download/專題/frontend/src/App.jsx)
前端頁面框架：
- 提供導覽列、離線安全指引以及 `ExperimentContext.Provider` 包裹。
- 注入精美磨砂玻璃暗色系樣式，在未解包完成前，對「指標看板」與「Live Demo」切換標籤實施視覺鎖定，或載入 Loading Skeleton 佔位。

#### [MODIFY] [MetricDashboard.jsx](file:///d:/Download/Citrus%20Pest%20and%20Disease%20Detection/ShowResultsWeb/frontend/src/components/MetricDashboard.jsx)
指標與圖表對比消融看板：
- **新增 5 種獨立指標圖表對比**：支援一鍵全選/全部取消勾選。
- **實體路徑明確展示**：在每張模型圖表與混淆矩陣下方標註伺服器絕對原始路徑。
- **「回到上方」按鈕**：在數據圖表分頁的最底部新增一個置中設計的磨砂玻璃按鈕，點擊觸發 `window.scrollTo` 平滑回到頁面頂部。

#### [MODIFY] [LiveDemo.jsx](file:///d:/Download/Citrus%20Pest%20and%20Disease%20Detection/ShowResultsWeb/frontend/src/components/LiveDemo.jsx)
AI 隨機推論與互動優化：
- **新增內置 `ImageZoom` 元件**：透過監聽 mousemove 座標事件實現原生放大鏡鏡片，提供懸停局部 2.5 倍高清放大。
- **全螢幕放大按鈕**：將原本點擊圖片呼叫 Lightbox 動作改為獨立按鈕，擺放於圖片上方狀態列與「對照原始圖」並排，點擊按鈕方可展開 Lightbox 全螢幕對比。

#### [NEW] [Lightbox.jsx](file:///d:/Download/專題/frontend/src/components/Lightbox.jsx)
自訂 Modal 放大與互動阻斷組件：
- **滾動穿透鎖定**：使用 `useEffect` 阻斷 body 滾動（設定 `document.body.style.overflow = 'hidden'` / `unset`）。
- **固定控制鈕**：關閉鈕設為 `fixed top-6 right-6 z-[60]`。
- **拖曳限制與縮放**：使用 React `useState` 記錄 Scale 與 Offset，並在 drag 時計算邊界，防止大圖超出範圍丟失。
- **鍵盤監聽**：支援 `Esc` 按鍵事件關閉。

---

## Verification Plan

### Automated Tests
- **滾動穿透測試**：
  打開 Lightbox 彈窗並放大圖片，嘗試在圖片內部及遮罩外部滑動滾輪，驗證背景主網頁的 scroll bar 是否紋絲不動。
- **邊界限制與防丟失測試**：
  在 Lightbox 中將圖片放大並往視窗邊緣狂拖，驗證圖片是否有最大位移限制（不可被拖出視窗外）。
- **執行緒池併發與阻塞測試**：
  在推論進行時，同時對 `/api/metrics` 發起指標請求，驗證 Event Loop 未被阻塞。
- **快取失效與覆寫測試**：
  使用相同的柑橘葉片檔名快速上傳 5 次，檢查 `extracted_runs/temp_output/` 資料夾內是否生成 5 個帶有不同 UUID 的影像檔案，並檢查前端是否成功渲染出 5 次最新的預測結果，無任何影像殘留卡頓。
- **記憶體監控測試**：
  在推論過程中，瘋狂切換 Large $\rightarrow$ Nano $\rightarrow$ Nano+P2，並藉由後端程式日誌（顯示記憶體釋放前後的系統 RAM 佔用）驗證 `ModelManager` 是否成功將 RAM 限制在單個模型運作的安全邊界。

### Manual Verification
1. **Quick Samples 卡片測試**：點擊精選卡片，確認 0.5 秒內即時在 Live Demo 生成結果圖，且下方出現病蟲害計數徽章。
2. **Lightbox 互動測試**：點擊 Live Demo 內生成的結果圖，確認大圖以 Modal 呈現，滾輪可放大到微觀斑點與蚜蟲，按住可任意拖動，按下 ESC 或背景能完美關閉。
