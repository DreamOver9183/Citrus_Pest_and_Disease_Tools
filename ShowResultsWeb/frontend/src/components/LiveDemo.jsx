import React from 'react';
import Lightbox from './Lightbox';
import { Layers, Sparkles, Compass } from 'lucide-react';
import ResultCard from './live-demo/ResultCard';
import ControlPanel from './live-demo/ControlPanel';
import { useLiveDemoInference } from './live-demo/useLiveDemoInference';

// 動態網格排版計算 (卡片佈局)
const getGridClass = (resultsCount) => {
  if (resultsCount === 1) {
    return "grid grid-cols-1 max-w-3xl mx-auto gap-6";
  } else if (resultsCount <= 4) {
    return "grid grid-cols-1 md:grid-cols-2 gap-6";
  } else if (resultsCount <= 9) {
    return "grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6";
  } else {
    return "grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6";
  }
};

const LiveDemo = () => {
  const {
    isUnzipped,
    sessions,
    sessionIds,
    currentDeviceLabel,
    selectedSessionId,
    setSelectedSessionId,
    confThreshold,
    setConfThreshold,
    sampleSize,
    setSampleSize,
    results,
    uploadedFiles,
    activeLightboxUrl,
    setActiveLightboxUrl,
    dropzone,
    handleResample,
    clearResults,
    toggleOriginal,
    reRunInferenceWithNewConf
  } = useLiveDemoInference();

  const { getRootProps, getInputProps, isDragActive } = dropzone;

  // 全域守衛 (Visual Guard) - ZIP 尚未解壓時的 Skeleton
  if (!isUnzipped || sessionIds.length === 0) {
    return (
      <div className="px-2 py-4 max-w-7xl mx-auto text-left">
        <div className="glass-panel rounded-3xl p-16 text-center border border-white/[0.06] shadow-2xl relative overflow-hidden">
          <div className="absolute inset-0 bg-gradient-to-r from-orange-500/10 to-indigo-500/10 blur-3xl opacity-35 pointer-events-none"></div>
          <Layers className="w-12 h-12 mx-auto mb-4 text-orange-500/60 animate-pulse" />
          <h2 className="text-base font-extrabold text-white mb-2 flex items-center justify-center gap-2 font-sans">
            即時推論控制台已鎖定
            <div className="relative group inline-block">
              <button className="cursor-help w-4 h-4 rounded-full bg-white/10 hover:bg-orange-500 hover:text-white text-[10px] text-gray-400 font-bold transition-all flex items-center justify-center border border-white/10" aria-label="鎖定說明">
                ?
              </button>
              <div className="absolute left-1/2 -translate-x-1/2 top-full mt-2 w-72 p-3 bg-slate-950/95 border border-white/10 rounded-xl text-xs text-gray-300 shadow-2xl opacity-0 group-hover:opacity-100 pointer-events-none transition-all duration-300 z-50 leading-relaxed font-sans font-normal backdrop-blur-md text-left">
                請先在「模型與裝置」分頁中載入含有訓練權重檔案的壓縮 ZIP 包或單一權重，系統載入後將自動開啟此處以進行高精度即時巡診。
              </div>
            </div>
          </h2>
          <p className="text-xs text-gray-500">請載入含有 YOLO 訓練權重檔案的壓縮包或單一權重。</p>
        </div>
      </div>
    );
  }

  return (
    <div className="px-2 py-4 max-w-7xl mx-auto animate-fadeIn text-left">
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-8 items-start">

        {/* 左側：結果展示區 */}
        <div className="lg:col-span-3 space-y-6">
          {results.length === 0 ? (
            <div className="glass-panel p-20 rounded-3xl border border-white/[0.06] text-center text-gray-500 shadow-2xl relative overflow-hidden">
              <div className="absolute inset-0 bg-gradient-to-br from-orange-500/5 to-indigo-500/5 pointer-events-none"></div>
              <Sparkles className="w-10 h-10 mx-auto mb-3 text-orange-400/50 animate-pulse" />
              <div className="text-white text-sm font-bold tracking-tight flex items-center justify-center gap-2 font-sans">
                等待載入影像...
              </div>
              <p className="text-[10px] text-gray-500 font-sans mt-1">請在右側設定面板上傳圖片或資料夾</p>
            </div>
          ) : (
            <div className="space-y-6">
              <div className="flex items-center justify-between border-b border-white/5 pb-3">
                <div className="flex items-center gap-2.5">
                  <div className="p-2 bg-orange-500/10 rounded-lg text-orange-400">
                    <Compass className="w-4 h-4" />
                  </div>
                  <div>
                    <h3 className="text-sm font-extrabold text-white tracking-tight uppercase">病蟲害即時巡檢報告</h3>
                    <p className="text-[10px] text-gray-400 font-mono mt-0.5">Real-Time Phytosanitary Inspection Reports ({results.length} Samples)</p>
                  </div>
                </div>
              </div>

              <div className={getGridClass(results.length)}>
                {results.map((item, index) => (
                  <ResultCard
                    key={item.id}
                    item={item}
                    resultsCount={results.length}
                    modelCustomName={sessions[selectedSessionId]?.custom_name}
                    onToggleOriginal={() => toggleOriginal(index)}
                    onZoom={setActiveLightboxUrl}
                  />
                ))}
              </div>
            </div>
          )}
        </div>

        {/* 右側：上傳與設定控制欄 (Sticky 固定防偏移) */}
        <ControlPanel
          currentDeviceLabel={currentDeviceLabel}
          getRootProps={getRootProps}
          getInputProps={getInputProps}
          isDragActive={isDragActive}
          sessionIds={sessionIds}
          sessions={sessions}
          selectedSessionId={selectedSessionId}
          setSelectedSessionId={setSelectedSessionId}
          sampleSize={sampleSize}
          setSampleSize={setSampleSize}
          confThreshold={confThreshold}
          setConfThreshold={setConfThreshold}
          onConfCommit={reRunInferenceWithNewConf}
          uploadedFilesCount={uploadedFiles.length}
          onResample={handleResample}
          resultsCount={results.length}
          onClear={clearResults}
        />

      </div>

      {/* Lightbox 彈出視窗 */}
      {activeLightboxUrl && (
        <Lightbox
          src={activeLightboxUrl}
          onClose={() => setActiveLightboxUrl(null)}
        />
      )}
    </div>
  );
};

export default LiveDemo;
