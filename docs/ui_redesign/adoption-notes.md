# Nocturne 採用決策記錄

這份文件記錄「要把 Nocturne 套到本專案」時必須先定下來的決定，以及已經定案的部分。
設計方向本身見 `redesign-proposal.dc.html`，現況樣板見 `current-state.dc.html`。

**目前狀態：B1–B4 全部定案；基礎建設層、全域 shell 與「模型與裝置」分頁已完成遷移。**
其餘五個分頁的內容區仍是舊樣式。

---

## B1. 語意色與類別色（已定案）

### 問題

Nocturne 是單一 accent 的低彩度系統：token 只有 neutral 100–900、一組 accent ramp
（`--color-accent-2-*` 依 readme 自述是同色相的機器產生替身，視為同一個角色）、
以及一個 deck 用的 section indigo。**沒有任何 success / warning / danger token，
也沒有類別色。**

但本專案的顏色是**帶語意的資料**，不是裝飾：

- `live-demo/classMap.js` — 每個病蟲害類別一個色相
- `dataset-analyzer/chartTheme.js` — `CHART_SERIES` 12 色循環、`SPLIT_COLORS`
- `evaluation/evalTheme.js` — `STATE_STYLES` 的 queued / running / done / failed

少了這兩組，偵測結果、圖表序列與評估狀態就沒辦法表達。

### 撞色不是判準

一度考慮把 accent 從 Nocturne 的 blurple 換成專案既有的 orange 以避開語意色。
實際算過色相距離後發現這條路不成立：

| 候選 accent | 最近的語意色 | 距離 |
| --- | --- | --- |
| Nocturne blurple `#9184d9` (h=289.6°) | violet / indigo / running | 9–10° |
| 現行 orange `#f97316` (h≈25°) | `CHART_SERIES[0]` 自己 | 0° |

`CHART_SERIES` 有 12 個色相、已鋪滿整個色環，**任何 accent 都會落在某個序列色的
30° 內**。換色相解決不了。

真正的分離方式是 Nocturne 自己的主張：accent「carries its chroma in lines and marks,
never as a flood」——外框、線條、發光、focus ring，幾乎不做實心填色；而類別色與
語意色全部是實心填色。**靠使用形式分離，不靠色相分離。** 這也說明為什麼現在
orange 同時當 accent 與 `CHART_SERIES[0]` 沒出過問題。

### 定案

- **accent 用 Nocturne 的 blurple**（完整採用，不換色相）。
- **類別色在 OKLCH 上重新生一組**，與 Nocturne 的 ramp 同一條感知亮度尺度。
- 產物：[`nocturne-extension.css`](nocturne-extension.css)，在 `styles.css` 之後載入。

生成參數與驗證結果：

| 項目 | 值 |
| --- | --- |
| 類別色相 | 12 個，30° 等距，相位 4.6° —— 讓 accent 的 289.6° 落在相鄰兩色正中間（各 15°） |
| 索引順序 | stride 5（與 12 互質）→ `cat-N` 與 `cat-N+1` 色相差 150° |
| 彩度 | 全色環安全值：step 400 C=0.112、step 500 C=0.116（12 色彩度相同，沒有哪個特別跳） |
| 對比 | 全部 5.8–6.5:1 vs `--color-bg`，遠高於非文字 UI 需要的 3:1，且彼此差距 < 0.7 |
| 語意色 | success h=145°、warning h=75°、danger h=29°，各給 300/500/700/900 四階 |
| info／進行中 | **不另設**，直接用 `--color-accent` —— 正在發生的事本來就該是畫面上唯一的 accent |

這是 Nocturne「Keep chroma low outside the accent」的**第三個明確例外**（前兩個是
deck 分隔頁與 landing 的 stat band）。理由：8–12 個類別要能一眼區分就必須有彩度，
這是資料的需求。語意色則只用在小面積（chip、進度條、圖示），與 Nocturne 的原則不衝突。

### 採用對應表

**`chartTheme.js` 的 `CHART_SERIES`** —— 索引對索引直接替換（它是 `index % 12` 取色，
沒有語意綁定，所以外觀會全變但邏輯不受影響）：

| idx | 現行 | 新 token |
| --- | --- | --- |
| 0 | `#f97316` | `--color-cat-1-500` `#d3798f` |
| 1 | `#6366f1` | `--color-cat-2-500` `#57ad78` |
| 2 | `#10b981` | `--color-cat-3-500` `#a885d2` |
| 3 | `#f43f5e` | `--color-cat-4-500` `#af9739` |
| 4 | `#38bdf8` | `--color-cat-5-500` `#549fda` |
| 5 | `#a855f7` | `--color-cat-6-500` `#d57d67` |
| 6 | `#eab308` | `--color-cat-7-500` `#1cafa1` |
| 7 | `#14b8a6` | `--color-cat-8-500` `#c47cb5` |
| 8 | `#ec4899` | `--color-cat-9-500` `#89a451` |
| 9 | `#84cc16` | `--color-cat-10-500` `#8392df` |
| 10 | `#f59e0b` | `--color-cat-11-500` `#c98845` |
| 11 | `#8b5cf6` | `--color-cat-12-500` `#1aaac4` |

**`evalTheme.js` 的 `STATE_STYLES`**：

| 狀態 | 新 token |
| --- | --- |
| queued | `--color-neutral-500` / `-700` |
| running | `--color-accent`（見上，不另設 info） |
| done | `--color-success-*` |
| failed | `--color-danger-*` |

**`classMap.js` 的類別徽章** —— **不能用「就近色相」對應**。實際算過會撞：
red(潰瘍病) 與 orange(蚜蟲) 都最接近 `cat-6`、rose(介殼蟲) 與 pink 都最接近 `cat-1`、
violet(薊馬) 與 purple 都最接近 `cat-3`。而 `chartTheme.js` 的註解正是在警告這件事
（「避免像 classMap.js 那樣同色重複出現」）。改用刻意指派：

| 類別 | 中文 | type | 新 token |
| --- | --- | --- | --- |
| `Oily_Spot` | 油斑病 | damage | `--color-cat-1-500` |
| `Canker` | 潰瘍病 | damage | `--color-cat-2-500` |
| `Black_Spot` | 黑點病 | damage | `--color-cat-3-500` |
| `Scale_Insect` | 介殼蟲 | pest | `--color-cat-4-500` |
| `Citrus_Leaf_Miner` | 潛葉蛾 | pest | `--color-cat-5-500` |
| `Thrips` | 薊馬 | pest | `--color-cat-6-500` |
| `Aphid` | 蚜蟲 | pest | `--color-cat-7-500` |
| `Sooty_Mold` | 煤煙病 | damage | `--color-neutral-500` ← 例外 |

這 7 個帶色類別的兩兩色相最小距離是 30°，即 12 色環的理論上限。

`Sooty_Mold` 留在中性灰是**刻意的例外**：煤煙病本身就是黑灰色，原本的 slate 是助記
而不是隨機配色，而灰色沒有色相、類別色環表達不了。

`ResultCard` 用 `type === 'pest'` 決定紅點／琥珀點，與類別色無關，這條邏輯不受影響。

### 一個要注意的副作用

`SPLIT_COLORS` 現在的註解說 train/valid/test 的顏色「與三個既有分頁的主色語彙一致」。
Nocturne 只有一個 accent，分頁不再各有主色，**這個耦合關係會失效**——遷移時要把該註解
一併更新，否則會留下一句對不上的說明。

---

## B2. 模型頁與權重登錄簿的分工（已定案）

**放棄 `2a` 的表格工作台。模型頁用卡片，權重登錄簿維持獨立分頁。**

理由：`MAX_SESSIONS = 3`（`app/core/config.py`），模型頁最多三列，而每一張卡片要
承載 arch、訓練超參數、最佳 mAP、匯出選項與工作區路徑——這些內容是卡片形的，
塞進表格會被截斷，三列也不需要排序。而 `registry/WeightTable.jsx` 已經是一張真正
多列、可排序、有 SHA／架構／來源／mAP 的表格，該有的表格已經有了。

一併排除的選項：把模型頁做成登錄簿的投影、兩頁合一。CLAUDE.md 明寫登錄簿與 session
的生命週期是刻意脫鉤的（「模型刪掉了、系統重啟了，我測過它、當時多少分仍然查得到」），
合併會模糊這個區別；而且 LocalLibrary 掃描結果不落地，兩個資料源的生命週期本來就不同。

## B3. 「摘要」分頁（已定案）

**不新增分頁。** `1c` 的四個結論數字（最佳 mAP@50 / mAP@50-95 / Micro-Accuracy
及其來源權重）本來就是登錄簿的跨權重彙總，放回**權重登錄簿分頁的頂部**。

連帶好處：

- nav 維持 6 個分頁，不用再擠 `flex-wrap`。
- `isUnzipped` 閘門的問題自動消失——登錄簿本來就刻意不吃閘門（見 `App.jsx` 的註解），
  所以「一個模型都沒載入時仍然看得到歷史數字」這件事自然成立，不需要為摘要頁
  另外想一套規則。

## B4. Nocturne 怎麼接 Tailwind（已定案）

**token 映射進 `tailwind.config.js` 的 `theme.extend`，元件繼續用 utility 寫。**
只維持一套樣式系統，可以一個分頁一個分頁漸進遷移。

### 關鍵技術限制：透明度修飾詞

前端有 **376 處、125 種**不同的透明度修飾詞寫法（`bg-orange-500/10`、
`border-red-500/30` …）。Tailwind 的 `/10` **沒辦法作用在存著完整色值的 CSS 變數上**，
必須是空格分隔的通道值配 `<alpha-value>` 佔位符。

因此 `nocturne-extension.css` 的每個 token 都有兩種形式：

```css
--color-cat-1-500: #d3798f;        /* 直接當顏色用：.dc.html 設計文件、純 CSS */
--color-cat-1-500-rgb: 211 121 143; /* 給 Tailwind 的 <alpha-value> 用 */
```

Nocturne 自身的 35 個 hex token 也在同一個檔案補了通道版本（不改動 vendored 的
`styles.css`）。**改動 `styles.css` 時要一併重生那一段**，否則兩者會不同步。

### 實測過的 config 寫法

```js
// tailwind.config.js
const ch = (v) => `rgb(var(${v}) / <alpha-value>)`;

const CAT = Object.fromEntries(
  Array.from({ length: 12 }, (_, i) => [String(i + 1), {
    400: ch(`--color-cat-${i + 1}-400-rgb`),
    500: ch(`--color-cat-${i + 1}-500-rgb`),
  }])
);

export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: { extend: {
    colors: { cat: CAT, accent: ch('--color-accent-rgb'), /* neutral / success / warning / danger 同理 */ },
    borderRadius: { sm: 'var(--radius-sm)', DEFAULT: 'var(--radius-md)', lg: 'var(--radius-lg)' },
    boxShadow:    { sm: 'var(--shadow-sm)', DEFAULT: 'var(--shadow-md)', lg: 'var(--shadow-lg)' },
  } },
};
```

已用專案自己的 tailwindcss 實跑驗證，輸出正確：

```css
.bg-cat-1-500\/10   { background-color: rgb(var(--color-cat-1-500-rgb) / 0.1) }
.border-danger-700\/60 { border-color: rgb(var(--color-danger-700-rgb) / 0.6) }
.text-cat-1-400      { color: rgb(var(--color-cat-1-400-rgb) / var(--tw-text-opacity, 1)) }
```

**CLAUDE.md 硬規則 3 仍然完全適用**：config 可以用程式產生（Tailwind 在 build 期讀它），
但 JSX 裡的 class 字串必須完整靜態出現——`` `bg-cat-${n}-500` `` 一樣會被 JIT 裁掉。
依變數選色仍然要用 `ACCENT_STYLES` / `CLASS_MAP` 那種完整字串的查表物件。

### 順帶解決既有的字型問題

`docs/architecture.md` §12 記錄了一個既有問題：`index.css` 匯入的 Outfit 被
`App.jsx` 的 `font-sans` 蓋掉，整個 app 其實用系統字型在跑。採用 Nocturne 時這個問題
自動關掉——`theme.extend.fontFamily.sans` 設成 Inter / Noto Sans TC，`font-sans` 就
真的指向設計系統的字型，同時把 `index.css` 的 Google Fonts `@import` 與 `body` 的
`font-family` 一起移除。**遷移時記得把 architecture.md 那一條一併結案。**

### 圖示

提案文件用 unpkg CDN 載 Phosphor。實作時**必須改用 `@phosphor-icons/react` npm 套件**
（現在是 `lucide-react`，打包進 bundle）；照抄 CDN 會讓離線工具在無網路時整片圖示消失。

---

## 已完成：基礎建設層

只鋪管線、不改任何元件外觀。改動三個檔案：

| 檔案 | 做了什麼 |
| --- | --- |
| `src/styles/nocturne-tokens.css` | **新增。** 由 `_ds/…/styles.css` 與 `nocturne-extension.css` 的 `:root` 區塊合併產生，158 個 token。只取 token，不取 Nocturne 的元件層。改動來源後要重新產生。 |
| `tailwind.config.js` | 把 token 接成 utility。顏色一律 `rgb(var(--x-rgb) / <alpha-value>)`。 |
| `src/index.css` | 匯入 token 檔；Google Fonts 從 Outfit/Space Grotesk 換成 Inter/Noto Sans TC（JetBrains Mono 保留）；`body` 的 `font-family` 改讀 `theme('fontFamily.sans')`。 |

### 刻意沒有覆寫的東西

`borderRadius` / `boxShadow` / `spacing` 都用 **`ds-` 前綴另開一組**（`rounded-ds`、
`shadow-ds-lg`、`p-ds-4`），沒有覆寫 Tailwind 既有的尺度。原因：`rounded` 在原始碼
用了 247 處、`shadow` 97 處，覆寫會讓全站立刻變樣，而基礎建設層的前提就是不改外觀。
逐頁遷移時再把元件換成 `ds-` 這組。

`ds-neutral` 同理——不覆寫 Tailwind 內建的 `neutral`（目前雖然 0 處在用，覆寫仍是
看不見的地雷）。

`body` 的 `background-color` 也維持原本的 `#030712`，沒有換成 `var(--color-bg)`——
那是換皮，屬於逐頁遷移。

### 唯一改變畫面的一項：字型

這同時是在修 `docs/architecture.md` §12 記錄的既有問題。實測確認（Vite dev server +
瀏覽器）：

- `font-sans` → `Inter, "Noto Sans TC", system-ui, …`（原本被 Tailwind 預設的
  `ui-sans-serif` 蓋掉，實際是系統字型）
- `font-mono` → `"JetBrains Mono", ui-monospace, …`（原本是 Consolas）
- 三個字型都確認真的載入（用 canvas 量測寬度比對 fallback，不是只看 CSS 宣告）
- token 在執行期取得到：`--color-cat-1-500` = `#d3798f`、`--color-cat-1-500-rgb` = `211 121 143`
- 六個分頁切換正常，console 零錯誤

**architecture.md §12 的那一條可以結案了**，但留著到元件遷移完成再一起刪，
免得中途有人以為字型問題還在。

### 還開著的：字型要不要自架

現在仍然是一個 Google Fonts 請求（只是換了字族）。對「本地離線」的定位，正解是用
`@fontsource` 系列套件自架，但那會新增 npm 依賴——CLAUDE.md 對依賴變動有明確的謹慎
要求，所以留給人決定，沒有擅自加。

---

## 已完成：「模型與裝置」分頁（第一個遷移的分頁）

依 1a 的方向：**單欄主軸 ＋ 設定抽屜**。

| 檔案 | |
| --- | --- |
| `system-specs/SettingsDrawer.jsx` | **新增。** 右側滑出抽屜，Esc 與點背景關閉、開啟時移入焦點、`role="dialog"`。 |
| `system-specs/ModelRow.jsx` | **新增。** 可展開的模型列：收合看名稱／架構／來源／輪數／大小／兩個 mAP，展開看來源檔、優化器、模型設定、改名、匯出、工作區路徑與移除。 |
| `SystemSpecs.jsx` | 重組為單欄主軸；上傳、本機資料夾、推論裝置移進抽屜。 |
| `system-specs/LocalLibraryPanel.jsx` | 改用 Nocturne token，去掉自帶面板外框（外框由抽屜負責）。 |
| `system-specs/ExportPanel.jsx`、`exportFormats.js` | 改用 Nocturne token；`STATE_STYLES` 照 B1 對應到 accent／success／danger。 |

### 抽屜的開關狀態放哪裡

**元件本地 state，不放 `context/hooks/`。** CLAUDE.md 硬規則 2 的判準是「切走分頁再切
回來還需要在嗎」——抽屜是純呈現，真正需要存活的東西（掃描結果、勾選項目、進行中的
請求）本來就在 `useLocalLibrary` 這個耐久 hook 裡。

但這帶來一個真實風險：使用者按下掃描、關掉抽屜，就再也看不到結果了。因此「設定」按鈕
在 `isScanning || isRegistering || selectedIds.length > 0` 時會顯示一個小圓點。

### 遷移途中發現的四個既有 bug

都不是這次改動造成的，但都在動到那段程式碼時浮出來，一併修掉：

1. **模型卡的 mAP 一直顯示 N/A。** 舊程式讀 `metrics_summary.mAP` 與 `.mAP_50`，
   但實際鍵是 `mAP50` 與 `mAP50-95`（後端把 `results.csv` 的表頭原樣帶過來，只去掉
   `metrics/` 前綴與 `(B)` 後綴）。兩個鍵從來都不存在。改成比照
   `registry_service.py` 的別名表做不分大小寫的比對。
2. **權重登錄簿的來源徽章顯示原始字串 `local_library_run`。**
   `registryFormat.js` 的 `SOURCE_LABELS`／`SOURCE_STYLES` 只有 `local_library` 這個鍵，
   但 `library_scanner.py` 送的是 `local_library_run`，於是退回 unknown 樣式並把鍵名
   直接印在畫面上。這正是 CLAUDE.md 硬規則 4 在講的失敗模式。兩個鍵都補上。
3. **推論裝置有兩個項目同時打勾。** 舊邏輯把「auto 時第一個實體裝置也算 selected」
   寫進同一個判斷式。舊版面把 auto 拆成獨立按鈕所以不明顯，收進同一個清單後就變成
   兩個勾。改成 auto 與實體裝置互斥，實際落在哪個裝置改用「自動選用」提示表示。
4. **展開列的按鈕沒有可及性名稱**（內容是巢狀 div／dl，算不出有意義的字串）。
   補 `aria-label`。

### 驗證

`npm run build` 與 `pytest`（352 passed）之外，實際開瀏覽器完整走過一遍：
開抽屜 → 掃描（6 權重 / 2 資料集）→ 取消全選 → 勾選 → 載入 → Esc 關閉 → 展開列 →
確認 mAP、來源徽章、匯出面板 → 移除 → 分頁切換。console 零錯誤。

### 已知的過渡狀態

全域 shell（header、分頁列、footer、背景光暈）仍是舊的橘色玻璃擬態，與 Nocturne 的
內容區有明顯接縫。這是逐頁遷移的預期代價，會在其餘分頁與 shell 遷移後消失。

---

## 已完成：全域 shell

`App.jsx`、`index.css`、`index.html`。三個改動都是設計系統的直接後果：

1. **六個分頁不再各有主色**，一律走單一 accent 的底線（B1 定案 Nocturne 是單 accent
   系統，彩度留給帶語意的資料）。連帶讓 `index.css` 的 `.animate-glow*` 五條規則失去
   使用者。
2. **拿掉四顆飽和色的背景光暈與網格疊層。** Nocturne 明講底色要保持去飽和、用柔和的
   漸層深度而不是大面積填色，那四顆 blur 正好是它說不要做的事。
3. **主要動作一律外框不填色**，包含 header 的品牌標記。

`body` 底色改為 `var(--color-bg)`，`index.html` 不再寫死 `bg-[#080d1a]`。

### 連帶清掉的死程式碼

全 src 掃描（`.jsx` 與 `.js`）確認 0 處引用後移除，`index.css` 從 211 行降到 76 行、
打包後的 CSS 從 55.6 kB 降到 49.6 kB：

`.glass-card` / `.glass-card-hover`、`.bg-radial-gradient-*`（4 條）、
`.border-gradient-*`（2 條）、`.animate-glow*`（5 條）、
以及 `.markdown-content` 及其 14 條子規則（約 90 行）。

**`.glass-panel` 保留**——其餘五個分頁還有 32 處在用，遷移完最後一頁時才能刪。

### 一併發現：`react-markdown` 是未使用的依賴

`.markdown-content` 那 90 行樣式沒有任何元件在用，因為 `react-markdown` **整個 src
都沒有 import**，但它仍列在 `package.json` 的 `dependencies`。**依賴本身沒有動**——
移除依賴是獨立的決定，CLAUDE.md 對依賴變動有明確的謹慎要求。

### 順帶更新的過期註解

`chartTheme.js` 的 `SPLIT_COLORS` 原本註明「與三個既有分頁的主色語彙一致」。分頁列
收成單一 accent 之後這個耦合失效了，註解已改寫（色值本身留待「資料集」分頁遷移時
換成 `--color-cat-*`）。

### 被改寫的裝飾性文案（需要你確認）

舊 shell 有幾處與事實不符的裝飾文字，遷移時一併改掉，但這是**內容決定不是設計決定**，
如果要保留原文請說：

| 位置 | 原文 | 現在 |
| --- | --- | --- |
| footer | `WebRTC Secure` | 移除（本專案沒有用到 WebRTC） |
| footer | `GPU HyperThreaded` | 移除（無實際意義） |
| 載入畫面 | `Initializing NVIDIA CUDA & GEMINI LLM Fallbacks` | 改為「正在偵測推論裝置與既有的模型 session」（本專案沒有用到 Gemini） |
| header | `v3.5 Live` 徽章 | 移除 |
| header | `Detection · Dataset Analysis · Model Export Toolkit` | 譯為「偵測 · 資料集分析 · 模型匯出」 |

### 驗證

`npm run build`、`pytest`（352 passed），並實際開瀏覽器逐一走過六個分頁：
三個閘門分頁確認為 `disabled`、`aria-current` 與 accent 底線只落在目前分頁
（用 DOM 查 `borderBottomColor` 確認是 `rgb(145,132,217)`，不是憑截圖判斷）、
未遷移的分頁在新底色上仍可讀。console 零錯誤。

---

## 還沒決定的

- 字型是否改用 `@fontsource` 自架（見上）。
- 遷移順序：一次全改，還是一個分頁一個分頁換。
- 其餘五個分頁的重新設計——目前只有「模型與裝置」有樣板。
