import React from 'react';
import { ExperimentProvider, useExperiment } from './context/ExperimentContext';
import SystemSpecs from './components/SystemSpecs';
import MetricDashboard from './components/MetricDashboard';
import LiveDemo from './components/LiveDemo';
import DatasetAnalyzer from './components/DatasetAnalyzer';
import { Layers, Activity, BarChart2, Zap, Cpu, Database, Sparkles, Server, CheckCircle2, FolderTree } from 'lucide-react';

const AppContent = () => {
  const { activeTab, setActiveTab, isUnzipped, loading, sessionCount, currentDeviceLabel } = useExperiment();

  if (loading) {
    return (
      <div className="min-h-screen bg-[#030612] text-gray-100 flex flex-col items-center justify-center gap-4 select-none">
        <div className="relative flex items-center justify-center">
          <div className="w-16 h-16 border-2 border-orange-500/10 border-t-orange-500 rounded-full animate-spin"></div>
          <Zap className="absolute w-6 h-6 text-orange-500 animate-pulse" />
        </div>
        <div className="text-center space-y-1">
          <span className="text-xs font-semibold text-gray-300 font-sans tracking-wide">初始化柑橘病蟲害工具包...</span>
          <p className="text-[10px] text-gray-500 font-mono tracking-widest uppercase">Initializing NVIDIA CUDA & GEMINI LLM Fallbacks</p>
        </div>
      </div>
    );
  }

  return (
    <div className="relative min-h-screen bg-[#020510] text-gray-100 flex flex-col justify-between overflow-hidden font-sans selection:bg-orange-500/30 selection:text-white">
      {/* 磨砂多色彩背景裝飾圓 (Dynamic Multi-Colored Ambient Glows for Professional Vibe) */}
      <div className="absolute top-[-10%] left-[-10%] w-[50vw] h-[50vw] rounded-full bg-orange-600/10 blur-[130px] pointer-events-none"></div>
      <div className="absolute top-[20%] right-[-10%] w-[45vw] h-[45vw] rounded-full bg-teal-600/8 blur-[120px] pointer-events-none"></div>
      <div className="absolute bottom-[20%] left-[-15%] w-[40vw] h-[40vw] rounded-full bg-pink-600/6 blur-[110px] pointer-events-none"></div>
      <div className="absolute bottom-[-10%] right-[-5%] w-[50vw] h-[50vw] rounded-full bg-indigo-600/10 blur-[150px] pointer-events-none"></div>
      
      {/* 科技感點陣背景疊加 (Grid matrix overlay) */}
      <div className="absolute inset-0 bg-[linear-gradient(to_right,#ffffff02_1px,transparent_1px),linear-gradient(to_bottom,#ffffff02_1px,transparent_1px)] bg-[size:24px_24px] [mask-image:radial-gradient(ellipse_60%_50%_at_50%_0%,#000_70%,transparent_100%)] pointer-events-none"></div>

      <div className="z-10 w-full">
        {/* 精美玻璃導覽列 (Navbar) */}
        <header className="sticky top-0 z-40 bg-[#040817]/85 backdrop-blur-md border-b border-white/[0.06] shadow-2xl transition-all">
          <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between flex-wrap gap-4">
            
            {/* 標題與標籤 */}
            <div className="flex items-center gap-3">
              <div className="p-2.5 bg-gradient-to-br from-orange-500 to-amber-600 rounded-xl shadow-[0_0_15px_rgba(249,115,22,0.25)] flex items-center justify-center">
                <Zap className="w-5 h-5 text-white animate-pulse" />
              </div>
              <div className="text-left">
                <div className="flex items-center gap-2">
                  <h1 className="font-extrabold text-white tracking-tight text-lg font-sans">
                    柑橘病蟲害工具包
                  </h1>
                  <span className="text-[9px] font-mono font-bold bg-orange-500/15 text-orange-400 border border-orange-500/30 px-2 py-0.5 rounded-md uppercase tracking-wider">
                    v3.5 Live
                  </span>
                </div>
                <p className="text-[10px] text-gray-400 font-mono tracking-wide mt-0.5">
                  Detection · Dataset Analysis · Model Export Toolkit
                </p>
              </div>
            </div>

            {/* 實時遙測統計 Telemetry Widget */}
            <div className="hidden xl:flex items-center gap-6 px-5 py-2.5 bg-slate-950/40 border border-white/[0.05] rounded-2xl">
              {/* 統計 1: 模型數量 */}
              <div className="flex items-center gap-2.5 border-r border-white/5 pr-5">
                <Database className="w-4 h-4 text-orange-400" />
                <div className="text-left font-mono">
                  <div className="text-[9px] text-gray-500 uppercase">模型庫容量</div>
                  <div className="text-xs text-white font-bold">{sessionCount} / 3 Sessions</div>
                </div>
              </div>

              {/* 統計 2: 當前硬體 */}
              <div className="flex items-center gap-2.5 border-r border-white/5 pr-5">
                <Cpu className="w-4 h-4 text-indigo-400" />
                <div className="text-left font-mono">
                  <div className="text-[9px] text-gray-500 uppercase">當前推論設備</div>
                  <div className="text-xs text-white font-bold truncate max-w-[140px]">{currentDeviceLabel || 'Auto'}</div>
                </div>
              </div>

              {/* 統計 3: 安全狀態 */}
              <div className="flex items-center gap-2">
                <span className="relative flex h-2 w-2">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
                </span>
                <span className="text-[11px] font-bold text-emerald-400 font-sans tracking-wide">
                  後端服務同步中
                </span>
              </div>
            </div>

            {/* 功能切換 Tabs (Multi-Colored, Clean Interactive Styling) */}
            <nav className="flex items-center bg-slate-950/70 p-1 rounded-xl border border-white/[0.08] shadow-inner font-sans">
              <button
                onClick={() => setActiveTab('init')}
                className={`flex items-center gap-2 px-4 py-2.5 text-xs font-bold rounded-lg transition-all cursor-pointer ${
                  activeTab === 'init'
                    ? 'bg-gradient-to-r from-teal-500 to-emerald-600 text-white shadow-lg shadow-teal-500/15 animate-glow-emerald'
                    : 'text-gray-400 hover:text-white hover:bg-white/5'
                }`}
              >
                <Activity className="w-3.5 h-3.5" />
                模型與裝置
              </button>

              <button
                onClick={() => isUnzipped && setActiveTab('metrics')}
                disabled={!isUnzipped}
                className={`flex items-center gap-2 px-4 py-2.5 text-xs font-bold rounded-lg transition-all ${
                  activeTab === 'metrics'
                    ? 'bg-gradient-to-r from-indigo-500 to-purple-600 text-white shadow-lg shadow-indigo-500/15 animate-glow-indigo'
                    : !isUnzipped
                    ? 'text-gray-600 cursor-not-allowed opacity-40'
                    : 'text-gray-400 hover:text-white hover:bg-white/5 cursor-pointer'
                }`}
                title={!isUnzipped ? "請先載入模型" : "消融指標與精度分析"}
              >
                <BarChart2 className="w-3.5 h-3.5" />
                消融分析
              </button>

              <button
                onClick={() => isUnzipped && setActiveTab('demo')}
                disabled={!isUnzipped}
                className={`flex items-center gap-2 px-4 py-2.5 text-xs font-bold rounded-lg transition-all ${
                  activeTab === 'demo'
                    ? 'bg-gradient-to-r from-orange-500 to-amber-500 text-white shadow-lg shadow-orange-500/15 animate-glow'
                    : !isUnzipped
                    ? 'text-gray-600 cursor-not-allowed opacity-40'
                    : 'text-gray-400 hover:text-white hover:bg-white/5 cursor-pointer'
                }`}
                title={!isUnzipped ? "請先載入模型" : "即時影像多標籤診斷"}
              >
                <Layers className="w-3.5 h-3.5" />
                即時診斷
              </button>

              <button
                onClick={() => setActiveTab('dataset')}
                className={`flex items-center gap-2 px-4 py-2.5 text-xs font-bold rounded-lg transition-all cursor-pointer ${
                  activeTab === 'dataset'
                    ? 'bg-gradient-to-r from-rose-500 to-pink-600 text-white shadow-lg shadow-rose-500/15 animate-glow-rose'
                    : 'text-gray-400 hover:text-white hover:bg-white/5'
                }`}
                title="資料集格式辨識與標註統計分析"
              >
                <FolderTree className="w-3.5 h-3.5" />
                資料集
              </button>
            </nav>

          </div>
        </header>

        {/* 內容渲染主區 */}
        <main className="min-h-[80vh]">
          {activeTab === 'init' && <SystemSpecs />}
          {activeTab === 'metrics' && <MetricDashboard />}
          {activeTab === 'demo' && <LiveDemo />}
          {activeTab === 'dataset' && <DatasetAnalyzer />}
        </main>
      </div>

      {/* 底部 Footer */}
      <footer className="z-10 py-6 border-t border-white/[0.05] text-center bg-slate-950/40 backdrop-blur-sm">
        <div className="max-w-7xl mx-auto px-6 flex flex-col sm:flex-row items-center justify-between gap-3">
          <p className="text-[10px] text-gray-500 font-mono tracking-wide">
            © 2026 Citrus Multi-Format (YOLO / SSD) Diagnosis Dashboard. Connected to FastAPI Core & PyTorch Engine.
          </p>
          <div className="flex items-center gap-4 text-[10px] text-gray-400 font-mono">
            <span className="flex items-center gap-1"><CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" /> WebRTC Secure</span>
            <span className="text-gray-600">|</span>
            <span className="flex items-center gap-1"><Sparkles className="w-3.5 h-3.5 text-orange-400" /> GPU HyperThreaded</span>
          </div>
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
