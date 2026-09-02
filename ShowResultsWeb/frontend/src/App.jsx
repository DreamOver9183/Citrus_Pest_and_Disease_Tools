import React from 'react';
import { ExperimentProvider, useExperiment } from './context/ExperimentContext';
import SystemSpecs from './components/SystemSpecs';
import MetricDashboard from './components/MetricDashboard';
import LiveDemo from './components/LiveDemo';
import DatasetAnalyzer from './components/DatasetAnalyzer';
import Evaluation from './components/Evaluation';
import Registry from './components/Registry';
import { Layers, Activity, BarChart2, Leaf, CheckCircle2, FolderTree, GaugeCircle, Library } from 'lucide-react';

// 分頁定義。
//
// `gated` 表示需要先載入模型才能進入。**權重登錄簿刻意不設閘門**：它記的是跨 session
// 的長期事實，一個模型都沒載入時仍然要能查得到歷史紀錄——那正是它存在的理由。
const TABS = [
  { id: 'init', label: '模型與裝置', Icon: Activity, gated: false, title: '載入模型與選擇推論裝置' },
  { id: 'metrics', label: '消融分析', Icon: BarChart2, gated: true, title: '消融指標與精度分析' },
  { id: 'demo', label: '即時診斷', Icon: Layers, gated: true, title: '即時影像多標籤診斷' },
  { id: 'dataset', label: '資料集', Icon: FolderTree, gated: false, title: '資料集格式辨識與標註統計分析' },
  { id: 'evaluate', label: '驗證評估', Icon: GaugeCircle, gated: true, title: '讓模型實跑資料集，計算當下的指標' },
  { id: 'registry', label: '權重登錄簿', Icon: Library, gated: false, title: '以權重雜湊為身分的長期帳本：訓練超參數與歷次實測指標' },
];

// 全域 shell：header、分頁列、內容區、footer。
//
// Nocturne 版本。與舊版的三個差異都是設計系統的直接後果：
//
// 1. **六個分頁不再各有主色**，一律走單一 accent 的底線。Nocturne 是單 accent 系統，
//    彩度留給真正帶語意的資料（偵測類別、圖表序列、job 狀態），見
//    docs/ui_redesign/adoption-notes.md 的 B1。
// 2. **拿掉四顆飽和色的背景光暈與網格疊層**。Nocturne 明講底色要保持去飽和、用柔和的
//    漸層深度而不是大面積填色，那四顆 blur 正好是它說不要做的事。
// 3. **主要動作一律外框、不填色**，包含 header 的品牌標記。
const AppContent = () => {
  const { activeTab, setActiveTab, isUnzipped, loading, sessionCount, currentDeviceLabel } = useExperiment();

  if (loading) {
    return (
      <div className="min-h-screen bg-ground text-ink flex flex-col items-center justify-center gap-4 select-none">
        <div className="w-10 h-10 border-2 border-ds-neutral-800 border-t-accent rounded-full animate-spin" />
        <div className="text-center space-y-1">
          <p className="text-sm text-ink">初始化柑橘病蟲害工具包…</p>
          <p className="text-xs text-ds-neutral-600">正在偵測推論裝置與既有的模型 session</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-ground text-ink flex flex-col">
      <header className="sticky top-0 z-40 bg-ground/95 backdrop-blur-sm border-b border-ds-neutral-800">
        <div className="max-w-7xl mx-auto px-6">
          {/* 品牌與遙測 */}
          <div className="flex items-center justify-between gap-4 flex-wrap py-3">
            <div className="flex items-center gap-2.5">
              <span className="w-6 h-6 rounded-ds-sm border border-accent text-accent flex items-center justify-center flex-shrink-0">
                <Leaf className="w-3.5 h-3.5" />
              </span>
              <span className="text-sm font-medium text-ink">柑橘病蟲害工具包</span>
              <span className="hidden sm:inline text-xs text-ds-neutral-600">
                偵測 · 資料集分析 · 模型匯出
              </span>
            </div>

            <div className="hidden md:flex items-center gap-5 text-xs text-ds-neutral-500">
              <span>
                插槽 <span className="text-ink tabular-nums">{sessionCount}/3</span>
              </span>
              <span className="truncate max-w-[180px]">
                裝置 <span className="text-ink">{currentDeviceLabel || 'Auto'}</span>
              </span>
            </div>
          </div>

          {/* 分頁列。Nocturne 用底線標示目前位置，不用填色的膠囊 */}
          <nav className="flex flex-wrap items-center gap-x-6 -mb-px">
            {TABS.map(({ id, label, Icon, gated, title }) => {
              const disabled = gated && !isUnzipped;
              const active = activeTab === id;
              return (
                <button
                  key={id}
                  onClick={() => !disabled && setActiveTab(id)}
                  disabled={disabled}
                  title={disabled ? '請先載入模型' : title}
                  aria-current={active ? 'page' : undefined}
                  className={`flex items-center gap-1.5 py-2.5 text-sm border-b-2 transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2 ${
                    active
                      ? 'border-accent text-ink'
                      : disabled
                        ? 'border-transparent text-ds-neutral-700 cursor-not-allowed'
                        : 'border-transparent text-ds-neutral-500 hover:text-ink cursor-pointer'
                  }`}
                >
                  <Icon className="w-3.5 h-3.5" />
                  {label}
                </button>
              );
            })}
          </nav>
        </div>
      </header>

      <main className="flex-1">
        {activeTab === 'init' && <SystemSpecs />}
        {activeTab === 'metrics' && <MetricDashboard />}
        {activeTab === 'demo' && <LiveDemo />}
        {activeTab === 'dataset' && <DatasetAnalyzer />}
        {activeTab === 'evaluate' && <Evaluation />}
        {activeTab === 'registry' && <Registry />}
      </main>

      <footer className="border-t border-ds-neutral-800">
        <div className="max-w-7xl mx-auto px-6 py-4 flex flex-col sm:flex-row items-center justify-between gap-2 text-xs text-ds-neutral-600">
          <p>© 2026 柑橘病蟲害偵測工具包 · FastAPI + PyTorch（YOLO / SSDLite）</p>
          <span className="flex items-center gap-1.5">
            <CheckCircle2 className="w-3.5 h-3.5 text-success-500" />
            後端服務已連線
          </span>
        </div>
      </footer>
    </div>
  );
};

const App = () => {
  return (
    <ExperimentProvider>
      <AppContent />
    </ExperimentProvider>
  );
};

export default App;
