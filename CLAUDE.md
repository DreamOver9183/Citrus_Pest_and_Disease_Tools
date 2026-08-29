# CLAUDE.md

給接手本專案的 AI 代理（Claude Code 或其他）的交接手冊。目的是讓你在不重新踩雷的前提下快速上手，不是重複 README/architecture.md 已經寫好的內容。

## 先讀哪份文件

三份文件分工不同，不要互相重複內容：

- **[README.md](README.md)** — 給人類使用者看的：功能特色、安裝、啟動方式。
- **[docs/architecture.md](docs/architecture.md)** — 每個子系統「為什麼這樣設計」的完整脈絡，含實測數據、被否決的替代方案、關鍵地雷的詳細說明。**修改任何子系統前務必先讀對應章節**，很多看似奇怪的寫法背後有已驗證過的理由。
- **本檔案** — 開發流程、跨子系統的硬規則、以及不值得寫進 architecture.md 但會讓你浪費半小時的細節。

## 專案速覽

柑橘病蟲害偵測工具包。FastAPI + PyTorch 後端（YOLO / SSDLite 雙軌），React + Vite 前端，應用本身仍是單一 Docker image 同時服務兩者（8000 port，無反向代理），另加一個 PostgreSQL 容器給權重登錄簿。無身分驗證——這是刻意的設計決策（單機本地展示工具），不是待補的缺口。

**資料庫只存「長期帳本」，不存執行期狀態。** session/dataset 仍然是記憶體 dict + JSON 快照，`LocalLibrary` 掃描結果仍然刻意不落地。登錄簿記的是「這台機器看過哪些權重、各自的超參數與歷次實測指標」，身分是權重檔內容的 SHA-256。見 architecture.md §10。

## 開發指令

```bash
# 後端測試（Windows venv 在 ShowResultsWeb/backend/.venv）
cd ShowResultsWeb/backend
./.venv/Scripts/python.exe -m pytest -q      # 或先 activate 再用裸 pytest -v

# 前端建置檢查（沒有測試框架，build 本身就是唯一的編譯檢查）
cd ShowResultsWeb/frontend
npm run build

# 本機開發伺服器
cd ShowResultsWeb/backend && uvicorn main:app --reload --host 127.0.0.1 --port 8000
cd ShowResultsWeb/frontend && npm run dev     # 代理 /api、/static、/samples 到 8000

# Docker（唯一能跑 TFLite 匯出的環境；Windows 開發模式下 TFLite 會顯示不可用）
# 會一併起 postgres:16-alpine 給權重登錄簿；單指令仍然成立
docker compose up --build

# 確認容器內的登錄簿真的連上 PostgreSQL（而不是靜默降級）
# 一定要走 HTTP 問正在跑的那個行程。`docker compose exec python -c ...` 會開一個**全新**
# 的 Python 行程，它沒跑過 lifespan、沒呼叫 init_db()，因此 is_available() 永遠是 False——
# 那是行程隔離，不是資料庫掛了。
curl -s localhost:8000/api/registry/stats     # 應含 "backend":"postgresql","available":true

# 本機開發不需要 Docker：DATABASE_URL 未設定時自動落回
# extracted_runs/registry.db（SQLite），pytest 亦同，零設定。

# E2E（需要後端已在執行；兩支都會在缺少素材時優雅跳過）
python e2e_tests/e2e_local_library.py       # 主力：用 LocalLibrary/ 內的真實檔案跑完整流程
E2E_ASSETS_DIR=<path> python e2e_tests/e2e_test.py   # 早期的上傳流程煙霧測試
```

沒有 lint/format 工具鏈（無 ruff/eslint 設定檔），改動風格比照鄰近程式碼即可。CI（`.github/workflows/ci.yml`）跑 `pytest`（SQLite 與 PostgreSQL 各一輪）與 `npm run build`，本機至少要過 SQLite 那一輪與前端 build 再提交。

**改完 UI 一定要用瀏覽器實際操作過（含分頁切換），不要只憑 build 成功就回報完成**——這個專案有多個 bug 是「型別檢查/測試全過但功能實際壞掉」，見下方地雷清單。

## 修改前必查的硬規則

以下是跨越多次功能開發後歸納出的模式，新增功能時請比照辦理，不要另創新模式：

1. **新增路徑設定一定改 `app/core/config.py` 的 4 個接點**：`_resolve_paths()` 字典項 → 模組層解包 → `ensure_dirs()`（若需要自動建立資料夾）→ `__all__`。少一個接點會在 import 時炸掉或悄悄拿到 `None`。

2. **前端跨分頁必須存活的狀態放 `context/hooks/`，不要放元件本地 state**。`App.jsx` 用純 `&&` 條件渲染分頁，切走分頁＝該元件樹整個 unmount，本地 state（含進行中的 request/AbortController）會直接消失。判斷標準：這個狀態切走分頁再切回來還需要在嗎？需要就放耐久 hook，不需要就放元件本地。`ExperimentContext.jsx` 是純組合層（見 architecture.md §3「Context 組合模式」），新 hook 要在這裡 compose 進去、對外仍經由單一 `useExperiment()` 暴露。

3. **Tailwind class 字串必須完整靜態出現在原始碼中**，不能用字串拼接（`` `bg-${color}-500` `` 這種在 JIT 模式下會被裁掉，因為 Tailwind 是靜態掃描原始碼字串，不是執行期解析）。需要依變數選色時用完整字串的查表物件（參考 `exportFormats.js`/`classMap.js` 的 `ACCENT_STYLES` 寫法）。

4. **模型/資料集的 `source_type`／`source` 欄位是前端精確比對、沒有 fallback 的字串**，不是自由文字。改動或新增來源前，先搜尋消費端（例如 `ModelMetricCard.jsx` 對 `source_type === 'single_weight'` 的精確比對）確認沒有既有邏輯依賴特定字面值。

5. **recharts 圖表若可能在隱藏分頁時載入資料，一定要加 `isAnimationActive={false}`**（`Pie` 尤其容易中招）。recharts 動畫走 `requestAnimationFrame`，瀏覽器把隱藏分頁的 rAF 節流到 0 fps，動畫永遠跑不完、圖表停在 0 個扇形——這是真實會發生的使用者體驗 bug，不是測試假象。

6. **後端背景工作用 `threading.Thread(daemon=True)` + `queue.Queue`，不要用 `ThreadPoolExecutor`**。後者的 atexit hook 會 join 非 daemon 執行緒，長任務進行中按 Ctrl-C 會卡住整個 uvicorn 行程直到任務結束。

7. **計算經過時間一律用 `time.monotonic()`，絕不與 `time.time()` 混用**。混用曾直接產出「29785752 分 60 秒」這種畫面（見 architecture.md §5）。

8. **任何會讓模型跑推論的新功能，都不得 import `model_service`**。`ModelManager._lock` 是非重入鎖且 `predict()` 全程持有，走它會讓所有推論請求排在你的長任務後面，而在持鎖狀態下呼叫 `load_model()` 直接死鎖。自建用完即丟的 `YOLO()` 實例（約 5MB），`export_service` 與 `evaluation_service` 都是這樣做的。

9. **`ultralytics` 的環境變數（`YOLO_AUTOINSTALL`/`YOLO_OFFLINE`）只能設在 [app/__init__.py](ShowResultsWeb/backend/app/__init__.py)，不能設在 `config.py`**。`AUTOINSTALL` 是 ultralytics 的模組級常數，在 `import ultralytics` 當下就凍結；`model_service.py` 第 6 行 import ultralytics、第 10 行才 import config，config.py 已經太晚。package `__init__` 保證先於任何 submodule 執行才是唯一可靠位置。

10. **改動需要「讀取某個位元組來源」的邏輯（ZIP 解析、資料夾解析）時，優先看能不能用既有的 reader 抽象**（`ZipArchiveReader`/`DirArchiveReader`，見 architecture.md §6）。這兩者只包一層 `build_tree()`/`read(path, cap)`，上層的 YOLO/COCO/VOC 解析邏輯完全不用關心來源是 ZIP 還是真實目錄。目錄端的 `_DirEntryStat` **必須有真實的 `.file_size` 屬性，絕不能用 `None` 佔位**——`dataset_analyzer` 的截斷保護是 `if info is not None and not budget.try_spend(info.file_size)`，塞 `None` 會讓保護悄悄失效而不報錯。

11. **新增任何會把 session 的 `dir_path` 指到 `extracted_runs/<新容器>/` 底下的功能時，那個容器名一定要加進 `delete_session()` 的白名單**（[session_manager.py](ShowResultsWeb/backend/app/services/session_manager.py) 內的 `["temp_output", "temp", "reports", …]`）。該函式用字串切割反推刪除目標，容器名不在白名單就會 `rmtree` 整個容器根目錄，刪一個 session 連帶清空其他所有同類資料。`datasets`/`exports`/`local_library`/`evaluations` 都各自踩過一次，`tests/test_session_container_dirs.py` 有參數化測試，新容器記得補一行。

12. **所有 API 回應一律走 `ApiResponse` 信封，錯誤一律 `raise ApiException`。** 不要回裸 dict，不要用 HTTP 200 夾帶 `{"status": "error"}`，不要重新引入 `response_model_exclude_unset=True`（它會靜默裁掉沒賦值的欄位，前端拿到 `undefined`——那是舊版的地雷，已由固定信封消除）。`tests/test_envelope.py` 會走訪所有路由強制這件事，新端點沒照做會直接紅。錯誤碼與 HTTP 狀態的對照表在 [app/core/envelope.py](ShowResultsWeb/backend/app/core/envelope.py) 的 `ERROR_STATUS`，分界線是「400 = 請求本身壞掉，422 = 請求沒問題但這件事現在不能做」。

13. **權重登錄簿的寫入絕不能讓主流程失敗，也絕不能在持鎖時發生。** 資料庫是**可選**相依：`registry_service` 的每個寫入函式都自己吞例外並只印日誌，呼叫端不必判斷成敗。而且 DB I/O 一律在 `SESSIONS_LOCK` / `EVAL_JOBS_LOCK` **之外**——資料庫可能在網路彼端，在鎖內等待往返會讓所有推論請求排隊。目前有三個寫入接點（`sessions.py` 兩條上傳路徑、`library_scanner.register()`、`evaluation_service._process_job()`），**新增載入模型的路徑時記得補上第四個**——漏掉 `library_scanner` 那次，單元測試全過而 E2E 才抓到。

14. **權重的身分是檔案內容的 SHA-256，不是 `session_id`。** 後者每次掃描都重新產生，拿它當 key 會讓同一顆 best.pt 每重掃一次就多一列。另外**絕不在 `library_scanner.discover()` 裡算雜湊**：掃描是唯讀探索、要維持秒級，對每個 `.pt` 做雜湊會讓它變成分鐘級。

15. **資料庫模型只能用 SQLAlchemy 通用型別**（`JSON`/`Float`/`String`）。`JSONB`、`ARRAY` 只有 PostgreSQL 有，用了就毀掉「Docker 走 Postgres、本機與 CI 走 SQLite」的雙軌，而那條雙軌是本機開發與 CI 零設定的前提。

## 依賴版本鎖定，改動前三思

- `recharts` 釘 `~2.12.7`：3.x 目標 React 19，本專案是 React 18.3.1；`package-lock.json` 未進版控、CI 跑裸 `npm install`，`^` 範圍會在無關 PR 上靜默升 major。
- Docker 內 `torch` 釘 `==2.12.1`：`litert-torch 0.9.3` 要求 `torch<2.13.0`，若讓 pip 自動解析會**降級成 CUDA 版**（覆蓋掉先前明確安裝的 CPU 版），實測差 16 個 CUDA 套件、映像檔暴增數 GB。
- 兩者都是「動了會在很久之後才炸、而且炸得很隱晦」的類型，改動前請重新做一次乾淨安裝並實測套件清單/bundle 大小。

## 刻意不做的事（不要「順手修掉」）

- `ModelManager` 同時只駐留一個模型（切換時主動 `del`+GC）——併發測試不同模型會互相搶佔重新載入，是刻意的記憶體安全取捨。
- 無身分驗證——工具定位是本地離線展示。
- 資料庫**只當附加的長期帳本**，不接管 session/dataset 狀態，也不改變「LocalLibrary 掃描結果不落地」——兩者生命週期本來就不同。
- 登錄簿**不引入 Alembic**：schema 用 `create_all()` 建立，日後只做加欄位的相容變更。單機、單使用者、資料可重建（重新掃描＋重跑評估）的工具，migration 框架的維護成本高於它解決的問題。
- 刪除 session 或評估 job **不連帶刪除**登錄簿紀錄（反之亦然）——那正是帳本的價值：模型刪掉了、系統重啟了，「我測過它、當時多少分」仍然查得到。
- 匯出功能的 job **不支援取消**——`model.export()` 執行中無法從 Python 中止，給一個按了沒用的取消鍵比不給更糟。
- 匯出只出 FP32，`quantize` 白名單刻意只放行 `32`/`None`——ONNX 的 FP16 轉換失敗在 ultralytics 內是被捕捉並警告的，等於會靜默交出標著 FP16 的 FP32 檔，貿然開放 FP16 選項會是使用者看不見的錯誤。
- LocalLibrary 掃描結果不落地（重啟後消失）——這是設計目標本身（「直到系統關閉、刪除暫存」），不是忘記持久化。
- LocalLibrary 的掃描**不會自動載入**任何東西，一定要使用者勾選後按載入——`MAX_SESSIONS` 只有 3，自動載入等於由掃描順序替使用者決定拿到哪幾個模型。
- Micro-Accuracy（Jaccard）**不另外掃一次資料集**，直接取 `val()` 已累積好的混淆矩陣，代價為零；代價是它綁在 ultralytics 寫死的 conf=0.25 / IoU=0.45（規格文件寫 IoU≥0.5，這 0.05 的落差**寫進資料列與 UI 明說**，而不是靠 monkeypatch 套件內部去消除）。
- 評估**不自己實作 mAP**，一律走 `model.val()`——自行實作 IoU 配對與 PR 積分容易在細節上算錯，交出一個和 ultralytics 對不上的數字在學術場合是負分。同理刻意不做 COCO 式分桶 AP。
- 已完成的評估結果**跨重啟保留，且不做「來源 session 還在嗎」的孤兒清除**（與 `export_service` 明確不同）——本專案多數 session 來自不落地的 LocalLibrary，那個過濾等於每次重啟刪光，而一次評估要跑 4 分鐘。

完整清單見 [docs/architecture.md 已知限制](docs/architecture.md#9-已知限制)。

## 提交與推送慣例

- Commit message 用**繁體中文**，格式比照既有紀錄（`git log`）：一行祈使句摘要，可選加簡短說明本次改動的模組範圍。
- 遠端只有 `origin`（`https://github.com/DreamOver9183/Citrus_Pest_and_Disease_Tools`），單一 `main` 分支，直接 push，無 PR 流程。
- 提交前務必跑過上方「開發指令」的 pytest 與 npm build 兩項，兩者是 CI 的完整內容，本機沒過 CI 一定紅。
- `.gitignore` 已排除 `Datasets/`、`Model/`、`Test tools/`、`LocalLibrary/`——這些是使用者本機資料，改動時若看到這幾個資料夾被 git 追蹤到，先確認是不是誤放的內容而非調整 `.gitignore`。
