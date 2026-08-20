import React from 'react';
import { Eye, Zap } from 'lucide-react';

// Tailwind 需要完整、靜態的 class 字串才能在 production build 掃描到，
// 因此以查表方式取代字串樣板動態組字串。
const ACCENT_STYLES = {
  orange: {
    hoverBorder: 'hover:border-orange-500/20',
    badge: 'text-orange-400 font-mono font-semibold bg-orange-500/10 border border-orange-500/20',
    sourceText: 'text-orange-300'
  },
  indigo: {
    hoverBorder: 'hover:border-indigo-500/20',
    badge: 'text-indigo-400 font-mono font-semibold bg-indigo-500/10 border border-indigo-500/20',
    sourceText: 'text-indigo-300'
  }
};

// 單一模型的指標圖卡片，共用於混淆矩陣區塊與各指標曲線區塊
const ModelMetricCard = ({ model, imgUrl, sourcePath, metricHasData, imgAlt, onZoom, accent = 'orange', emptyHeightClass = 'h-32', emptyDescription = null }) => {
  const styles = ACCENT_STYLES[accent] || ACCENT_STYLES.orange;

  return (
    <div className={`bg-[#0c1228]/40 rounded-2xl p-4.5 border border-white/5 flex flex-col items-center gap-4 transition-all relative ${styles.hoverBorder}`}>
      <div className="w-full flex items-center justify-between gap-2 border-b border-white/5 pb-2">
        <span className="text-xs font-bold text-white px-3 py-1 bg-white/5 rounded-full border border-white/5">
          {model.custom_name}
        </span>
        <span className={`text-[9px] px-2 py-0.5 rounded-full ${styles.badge}`}>
          {model.source_type === 'single_weight' ? 'Weight Only' : 'Runs Log'}
        </span>
      </div>

      {!metricHasData ? (
        <div className={`flex flex-col items-center justify-center ${emptyHeightClass} border border-dashed border-white/10 rounded-xl bg-slate-950/20 gap-2 p-4 w-full`}>
          <Zap className="w-6 h-6 text-orange-500/30 animate-pulse" />
          <p className="text-[10px] text-center text-gray-500 font-sans">無指標對齊資料</p>
          {emptyDescription && (
            <p className="text-[9px] text-center text-gray-600 leading-relaxed font-mono">{emptyDescription}</p>
          )}
        </div>
      ) : imgUrl ? (
        <div
          className="relative overflow-hidden rounded-xl cursor-zoom-in group border border-white/10 bg-slate-950/60 w-full"
          onClick={() => onZoom(imgUrl)}
        >
          <img
            src={`${imgUrl}?t=${Date.now()}`}
            alt={imgAlt}
            className="w-full object-contain group-hover:scale-[1.03] transition-transform duration-300"
            referrerPolicy="no-referrer"
          />
          <div className="absolute inset-0 bg-black/60 opacity-0 group-hover:opacity-100 transition-opacity flex flex-col items-center justify-center gap-1">
            <Eye className="w-6 h-6 text-white" />
            <span className="text-[10px] text-white font-sans font-bold">點擊放大檢視</span>
          </div>
        </div>
      ) : (
        <div className={`text-xs text-gray-600 ${emptyHeightClass} flex items-center justify-center border border-dashed border-white/5 rounded-xl w-full bg-slate-950/20 font-mono`}>
          未產出此指標
        </div>
      )}

      <div className="w-full space-y-1 text-left">
        <span className="text-[9px] text-gray-500 font-mono block truncate" title={model.dir_path}>
          目錄: {model.dir_path}
        </span>
        {sourcePath && (
          <div className={`w-full p-2 bg-slate-950/75 rounded-lg border border-white/5 text-[9px] font-mono break-all leading-normal ${styles.sourceText}`}>
            <span className="text-gray-500 block text-[8px] uppercase tracking-wider mb-0.5 font-sans font-bold">Inference Target File</span>
            {sourcePath}
          </div>
        )}
      </div>
    </div>
  );
};

export default ModelMetricCard;
