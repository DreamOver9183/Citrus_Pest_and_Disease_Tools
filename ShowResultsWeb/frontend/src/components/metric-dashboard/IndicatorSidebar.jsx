import React from 'react';
import { AreaChart, ChevronLeft, ChevronRight } from 'lucide-react';
import { METRICS_OPTIONS } from './metricsOptions';

// 展開抽屜按鈕 (側邊欄收折後懸浮顯示)
export const SidebarExpandButton = ({ onExpand }) => (
  <button
    onClick={onExpand}
    className="fixed left-0 top-36 z-30 flex items-center gap-1.5 px-4 py-3 bg-gradient-to-r from-orange-500 to-amber-500 text-white font-extrabold text-[11px] rounded-r-2xl shadow-xl hover:shadow-orange-500/20 active:scale-95 transition-all cursor-pointer animate-slideIn font-sans uppercase tracking-wider"
    title="展開指標篩選器"
  >
    <ChevronRight className="w-4 h-4" />
    指標篩選
  </button>
);

// 左側指標勾選側邊欄 (Sticky)
const IndicatorSidebar = ({
  selectedMetrics,
  onToggleMetric,
  onToggleAll,
  showConfusionMatrix,
  onToggleConfusionMatrix,
  onCollapse
}) => {
  return (
    <div className="lg:col-span-1 sticky top-24 self-start space-y-6 animate-fadeIn">
      <div className="glass-panel p-5 rounded-2xl border border-white/[0.06] space-y-6 shadow-2xl relative">
        {/* 收折按鈕 */}
        <button
          onClick={onCollapse}
          className="absolute -right-3 top-5 p-1 bg-[#060b1e] border border-white/10 text-gray-400 hover:text-white rounded-full shadow-lg hover:border-orange-500/40 transition-all cursor-pointer z-20"
          title="折疊指標選單"
        >
          <ChevronLeft className="w-3.5 h-3.5" />
        </button>

        <div className="flex items-center justify-between pb-4 border-b border-white/5">
          <div className="flex items-center gap-2">
            <AreaChart className="w-4 h-4 text-orange-400" />
            <h3 className="text-xs font-bold text-white tracking-wider uppercase font-sans flex items-center gap-2">
              對齊與消融指標
              <div className="relative group inline-block ml-1">
                <button className="cursor-help w-4 h-4 rounded-full bg-white/10 hover:bg-orange-500 hover:text-white text-[10px] text-gray-400 font-bold transition-all flex items-center justify-center border border-white/10 shadow-lg" aria-label="說明">
                  ?
                </button>
                <div className="absolute left-1/2 -translate-x-1/2 top-full mt-2 w-64 p-3 bg-slate-950/95 border border-white/10 rounded-xl text-xs text-gray-300 shadow-2xl opacity-0 group-hover:opacity-100 pointer-events-none transition-all duration-300 z-50 leading-relaxed font-sans font-normal backdrop-blur-md">
                  系統會自動對齊每個模型的關鍵指標。YOLO 展示截圖解析，SSD 則展示自動繪製之曲線。
                </div>
              </div>
            </h3>
          </div>
          <button
            onClick={onToggleAll}
            className="text-[9px] px-2 py-1 bg-white/5 hover:bg-orange-500 hover:text-white border border-white/10 rounded-md transition-all cursor-pointer font-bold font-sans"
          >
            {selectedMetrics.length === METRICS_OPTIONS.length ? '取消全部' : '全選指標'}
          </button>
        </div>

        {/* 指標核取區 */}
        <div className="space-y-2 max-h-[360px] overflow-y-auto pr-1">
          {METRICS_OPTIONS.map(opt => {
            const checked = selectedMetrics.includes(opt.key);
            return (
              <label
                key={opt.key}
                className={`flex items-start gap-3 p-2.5 rounded-xl border transition-all cursor-pointer select-none ${
                  checked
                    ? 'bg-orange-500/10 border-orange-500/30 text-white'
                    : 'border-white/5 text-gray-400 hover:bg-slate-900/40'
                }`}
              >
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => onToggleMetric(opt.key)}
                  className="mt-1 accent-orange-500 rounded cursor-pointer w-3.5 h-3.5"
                />
                <div className="text-left">
                  <p className="text-[11px] font-bold leading-tight">{opt.name}</p>
                  <p className="text-[9px] text-gray-500 mt-1 leading-normal">{opt.desc}</p>
                </div>
              </label>
            );
          })}
        </div>

        {/* 混淆矩陣獨立開關 */}
        <div className="pt-4 border-t border-white/5">
          <label
            className={`flex items-center gap-3 p-3 rounded-xl border transition-all cursor-pointer select-none ${
              showConfusionMatrix
                ? 'bg-indigo-500/10 border-indigo-500/30 text-white'
                : 'border-white/5 text-gray-400 hover:bg-slate-900/40'
            }`}
          >
            <input
              type="checkbox"
              checked={showConfusionMatrix}
              onChange={onToggleConfusionMatrix}
              className="accent-indigo-500 rounded cursor-pointer w-3.5 h-3.5"
            />
            <div className="text-left">
              <p className="text-[11px] font-bold leading-tight">正規化混淆矩陣對比</p>
              <p className="text-[9px] text-gray-500 mt-1">展示類別分類精準交叉映射</p>
            </div>
          </label>
        </div>
      </div>
    </div>
  );
};

export default IndicatorSidebar;
