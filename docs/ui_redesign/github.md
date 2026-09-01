repo: DreamOver9183/Citrus_Pest_and_Disease_Tools
branch: feature/ui-redesign-proposal
path: ShowResultsWeb/frontend

## Last sync
date: 2026-08-31T07:25:00Z

### Updated in this project
- 依前端原始碼像素級重建現況 UI（六個分頁的 shell、面板與資料呈現）
- 以 Nocturne 設計系統提出三個重新設計方向（**只涵蓋「模型與裝置」一頁**，其餘五頁尚未設計）

## 怎麼開啟這兩份文件
`.dc.html` 要用 Claude Design 的畫布開啟才會渲染；`support.js` 在執行期會從 unpkg 取
React 18.3.1 / ReactDOM / @babel/standalone（附 SRI），因此**看這兩份文件需要網路**，
與本專案「本地離線」的執行定位不同。`support.js` 是設計工具產生的 runtime（檔頭標明
do-not-edit），不要手改。

## Screen map
| 專案畫面 | 來源檔案 |
| --- | --- |
| 現況重建 · 全域 shell / 分頁列 / footer | src/App.jsx, src/index.css, index.html, tailwind.config.js |
| 現況重建 · 模型與裝置 | src/components/SystemSpecs.jsx, components/system-specs/LocalLibraryPanel.jsx, components/system-specs/ExportPanel.jsx |
| 現況重建 · 消融分析 | src/components/MetricDashboard.jsx, components/metric-dashboard/IndicatorSidebar.jsx, ChartGrid.jsx, metricsOptions.js |
| 現況重建 · 即時診斷 | src/components/LiveDemo.jsx, components/live-demo/ControlPanel.jsx, ResultCard.jsx |
| 現況重建 · 資料集 | src/components/DatasetAnalyzer.jsx, components/dataset-analyzer/DatasetOverviewHeader.jsx, DatasetSummaryCards.jsx |
| 現況重建 · 驗證評估 | src/components/Evaluation.jsx, components/evaluation/EvalLauncher.jsx, EvalJobList.jsx |
| 現況重建 · 權重登錄簿 | src/components/Registry.jsx, components/registry/WeightTable.jsx |
| 新UI風格提案 1a/1b/1c、合併版 2a | 只重新設計「模型與裝置」一頁作為樣板；其餘五頁未涵蓋 |
