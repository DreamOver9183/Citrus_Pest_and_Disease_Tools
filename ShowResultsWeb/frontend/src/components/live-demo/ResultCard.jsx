import React from 'react';
import { CheckCircle, RefreshCw, Maximize2 } from 'lucide-react';
import ImageZoom from './ImageZoom';
import { CLASS_MAP } from './classMap';

// 動態子圖片大小/排版 (卡片內部影像對照區佈局)
const getCardInnerClass = (item, resultsCount) => {
  if (item.showOriginal) {
    // 開啟原始圖時，雙欄並排
    if (resultsCount === 1) return "grid grid-cols-1 sm:grid-cols-2 gap-4 h-80";
    if (resultsCount <= 4) return "grid grid-cols-1 sm:grid-cols-2 gap-4 h-60";
    return "grid grid-cols-1 gap-2";
  } else {
    // 預設僅顯示標註圖，單欄
    if (resultsCount === 1) return "grid grid-cols-1 max-w-xl mx-auto h-80";
    if (resultsCount <= 4) return "grid grid-cols-1 h-60";
    return "grid grid-cols-1";
  }
};

// 動態圖片容器高度與排版
const getImageContainerClass = (item, resultsCount) => {
  if (item.showOriginal) {
    if (resultsCount <= 4) return "relative rounded-lg overflow-hidden border border-white/5 bg-slate-950 flex items-center justify-center h-full";
    return "relative rounded-lg overflow-hidden border border-white/5 bg-slate-950 flex items-center justify-center h-40";
  } else {
    if (resultsCount === 1) return "relative rounded-lg overflow-hidden border border-white/5 bg-slate-950 flex items-center justify-center h-full max-w-xl mx-auto";
    if (resultsCount <= 4) return "relative rounded-lg overflow-hidden border border-white/5 bg-slate-950 flex items-center justify-center h-full";
    return "relative rounded-lg overflow-hidden border border-white/5 bg-slate-950 flex items-center justify-center h-56";
  }
};

// 單張推論結果卡片
const ResultCard = ({ item, resultsCount, modelCustomName, onToggleOriginal, onZoom }) => {
  const cardInnerClass = getCardInnerClass(item, resultsCount);
  const imgContainerClass = getImageContainerClass(item, resultsCount);

  return (
    <div className="glass-panel p-5 rounded-2xl border border-white/[0.06] space-y-4 relative overflow-hidden shadow-2xl hover:border-orange-500/20 transition-all duration-300">
      {/* 狀態列與對照開關 */}
      <div className="flex items-center justify-between text-xs border-b border-white/5 pb-3 font-mono">
        <span className="text-gray-300 truncate max-w-[120px] font-semibold text-[11px]" title={item.filename}>
          {item.filename}
        </span>
        <div className="flex items-center gap-2 flex-wrap justify-end">
          {item.resultUrl && (
            <>
              <button
                onClick={onToggleOriginal}
                className={`px-2.5 py-1 rounded-md text-[10px] font-bold border transition-all cursor-pointer font-sans ${
                  item.showOriginal
                    ? 'bg-orange-500/20 border-orange-500/40 text-orange-400 shadow-sm'
                    : 'bg-white/5 border-white/10 text-gray-400 hover:text-white hover:bg-white/10'
                }`}
                title={item.showOriginal ? "隱藏原始圖片" : "對照原始圖片"}
              >
                {item.showOriginal ? '關閉對照' : '對照原始圖'}
              </button>
              <button
                onClick={() => onZoom(item.resultUrl)}
                className="px-2.5 py-1 rounded-md text-[10px] font-bold border border-white/10 text-gray-300 hover:text-white hover:bg-white/10 transition-all cursor-pointer flex items-center gap-1 font-sans"
                title="放大檢視"
              >
                <Maximize2 className="w-3 h-3" /> 放大
              </button>
            </>
          )}
          <div>
            {item.loading && (
              <span className="text-orange-400 flex items-center gap-1 animate-pulse font-bold text-[10px]">
                <RefreshCw className="w-3 h-3 animate-spin" /> 推論中...
              </span>
            )}
            {item.resultUrl && (
              <span className="text-emerald-400 flex items-center gap-1 font-bold text-[10px]">
                <CheckCircle className="w-3.5 h-3.5" /> 標註成功
              </span>
            )}
            {item.error && (
              <span className="text-red-400 font-bold text-[10px]">❌ {item.error}</span>
            )}
          </div>
        </div>
      </div>

      {/* 影像展示區 */}
      <div className={cardInnerClass}>
        {/* 原始圖片 (僅在使用者點擊對照時開啟) */}
        {item.showOriginal && (
          <div className={imgContainerClass}>
            <img
              src={item.originalUrl}
              alt="Original"
              className="max-h-full max-w-full object-contain"
              referrerPolicy="no-referrer"
            />
            <div className="absolute top-2 left-2 px-2.5 py-0.5 bg-black/60 border border-white/10 text-[9px] text-gray-300 rounded-md font-mono">
              ORIGINAL
            </div>
          </div>
        )}

        {/* 標註結果圖 */}
        <div className={imgContainerClass}>
          {item.loading ? (
            <div className="flex flex-col items-center justify-center gap-3">
              <div className="w-8 h-8 border-3 border-orange-500/20 border-t-orange-500 rounded-full animate-spin"></div>
              <span className="text-[10px] text-gray-500 font-mono">推論中…</span>
            </div>
          ) : item.resultUrl ? (
            <div className="relative w-full h-full">
              <ImageZoom
                src={`${item.resultUrl}?t=${Date.now()}`}
                alt="Annotated"
                className="max-h-full max-w-full object-contain"
              />
              <div className="absolute top-2 left-2 px-2.5 py-0.5 bg-orange-500/80 border border-orange-400/20 text-[9px] text-white rounded-md font-mono font-bold animate-fadeIn pointer-events-none z-20">
                {modelCustomName || 'YOLO'} 診斷
              </div>
            </div>
          ) : (
            <div className="text-gray-500 text-xs font-mono">等待解算...</div>
          )}
        </div>
      </div>

      {/* 雙軌病徵統計徽章 */}
      {item.resultUrl && (
        <div className="bg-slate-950/40 rounded-xl p-3 border border-white/5 flex flex-col gap-2 text-left text-[10px] font-mono">
          <div className="text-gray-400 flex items-center justify-between border-b border-white/5 pb-1.5">
            <span>檢出: <span className="text-orange-400 font-extrabold">{item.counts} 個病徵特徵</span></span>
            {item.deviceUsed && (
              <span className="text-[8px] uppercase tracking-wider font-extrabold bg-orange-500/10 text-orange-400 px-2 py-0.5 rounded border border-orange-500/20" title="推論裝置">
                ENGINE: {item.deviceUsed.includes('cuda') ? 'GPU' : item.deviceUsed.includes('MPS') ? 'MPS' : 'CPU'}
              </span>
            )}
          </div>
          {item.counts > 0 ? (
            <div className="flex flex-wrap gap-1.5 pt-0.5">
              {Object.entries(item.detections).map(([raw_cls, count]) => {
                const matched = CLASS_MAP[raw_cls] || { name: raw_cls, type: 'unknown', color: 'bg-gray-500/10 text-gray-400 border-gray-500/20' };
                return (
                  <span
                    key={raw_cls}
                    className={`px-2 py-1 rounded-md border text-[9px] font-bold flex items-center gap-1.5 font-sans ${matched.color}`}
                  >
                    <span className={`w-1.5 h-1.5 rounded-full ${matched.type === 'pest' ? 'bg-red-500' : 'bg-amber-400'}`}></span>
                    {matched.name}: {count}
                  </span>
                );
              })}
            </div>
          ) : (
            <span className="text-emerald-400 font-extrabold flex items-center gap-1 text-[10px] py-0.5 font-sans">
              <CheckCircle className="w-3.5 h-3.5" /> 經診斷無明顯異常病蟲害
            </span>
          )}
        </div>
      )}
    </div>
  );
};

export default ResultCard;
