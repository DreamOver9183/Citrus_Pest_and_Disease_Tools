import React, { useState } from 'react';
import { FolderSearch, RefreshCw, Copy, Check, AlertCircle, CheckCircle2 } from 'lucide-react';
import { useExperiment } from '../../context/ExperimentContext';

// 本機資料夾掃描面板。
//
// 使用者用作業系統的檔案總管把訓練成果／資料集放進畫面上顯示的資料夾，再按下掃描。
// 刻意不做「選擇資料夾」的檔案對話框：瀏覽器基於安全機制永遠不會把使用者選取的
// 資料夾轉成後端可用的絕對路徑，固定目錄讓路徑完全不需要經過瀏覽器。
const LocalLibraryPanel = () => {
  const {
    libraryPath,
    libraryExists,
    pathLoading,
    isScanning,
    lastScanSummary,
    scanError,
    scanLocalLibrary,
  } = useExperiment();

  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(libraryPath);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // 剪貼簿在非安全來源(http)下不可用，靜默忽略即可
    }
  };

  return (
    <div className="glass-panel p-6 rounded-2xl border border-white/[0.06] shadow-xl space-y-5 relative overflow-hidden">
      <div className="absolute top-[-25%] right-[-15%] w-[120px] h-[120px] rounded-full bg-teal-500/5 blur-[40px] pointer-events-none"></div>

      <div className="flex items-center justify-between">
        <h3 className="text-xs font-bold text-white tracking-widest uppercase flex items-center gap-2">
          <FolderSearch className="w-4 h-4 text-teal-400" />
          本機資料夾
          <div className="relative group inline-block ml-1">
            <button
              className="cursor-help w-4 h-4 rounded-full bg-white/10 hover:bg-teal-500 hover:text-white text-[10px] text-gray-400 font-bold transition-all flex items-center justify-center border border-white/10 shadow-lg"
              aria-label="說明"
            >
              ?
            </button>
            <div className="absolute left-1/2 -translate-x-1/2 bottom-full mb-2 w-72 p-4 bg-slate-950/95 border border-white/10 rounded-2xl text-xs text-gray-300 shadow-2xl opacity-0 group-hover:opacity-100 pointer-events-none transition-all duration-300 z-50 leading-relaxed font-sans font-normal backdrop-blur-md text-left">
              把訓練成果資料夾（含 <span className="font-mono text-teal-400">weights/best.pt</span> 與{' '}
              <span className="font-mono text-teal-400">args.yaml</span>）或資料集資料夾放進下方路徑，
              再按掃描即可直接使用，<span className="text-teal-400 font-bold">不需上傳、不會複製檔案</span>。
              掃描結果保留至後端關閉為止。
            </div>
          </div>
        </h3>
        <span className="text-[10px] text-teal-400 font-mono font-bold bg-teal-500/10 px-2 py-0.5 rounded-md">
          No Upload
        </span>
      </div>

      {/* 路徑顯示 */}
      <div className="bg-slate-950/50 rounded-xl p-3.5 border border-white/5 space-y-2">
        <div className="flex items-center justify-between gap-2">
          <span className="text-gray-500 text-[10px] uppercase font-mono tracking-wider">
            掃描目標路徑
          </span>
          {libraryPath && (
            <button
              onClick={handleCopy}
              className="text-[9px] px-2 py-1 bg-white/5 hover:bg-teal-500 hover:text-white border border-white/10 rounded-md transition-all cursor-pointer font-bold font-sans flex items-center gap-1 flex-shrink-0"
              title="複製路徑"
            >
              {copied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
              {copied ? '已複製' : '複製'}
            </button>
          )}
        </div>
        <p
          className="text-[10px] text-gray-300 font-mono break-all leading-relaxed"
          title={libraryPath}
        >
          {pathLoading ? '讀取中...' : libraryPath || '（無法取得路徑）'}
        </p>
        {!pathLoading && !libraryExists && (
          <p className="text-[9px] text-amber-400 font-sans">
            此資料夾尚未建立，啟動後端時會自動建立
          </p>
        )}
      </div>

      {/* 掃描按鈕 */}
      <button
        onClick={scanLocalLibrary}
        disabled={isScanning || pathLoading}
        className={`w-full py-2.5 text-white font-extrabold text-xs rounded-xl transition-all shadow-lg flex items-center justify-center gap-2 font-sans ${
          isScanning || pathLoading
            ? 'bg-white/5 text-gray-500 cursor-not-allowed opacity-50'
            : 'bg-gradient-to-r from-teal-500 to-emerald-600 hover:from-teal-600 hover:to-emerald-700 hover:shadow-teal-500/20 cursor-pointer'
        }`}
      >
        {isScanning ? (
          <>
            <RefreshCw className="w-3.5 h-3.5 animate-spin" />
            掃描中...
          </>
        ) : (
          <>
            <FolderSearch className="w-3.5 h-3.5" />
            掃描本機資料夾
          </>
        )}
      </button>

      {/* 掃描結果摘要 */}
      {lastScanSummary && !scanError && (
        <div className="p-3 bg-teal-500/10 border border-teal-500/30 text-teal-300 rounded-xl text-[11px] flex items-start gap-2">
          <CheckCircle2 className="w-4 h-4 flex-shrink-0 mt-0.5" />
          <span className="break-words">{lastScanSummary.message}</span>
        </div>
      )}

      {scanError && (
        <div className="p-3 bg-red-500/10 border border-red-500/30 text-red-400 rounded-xl text-[11px] flex items-start gap-2">
          <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
          <span className="break-words">{scanError}</span>
        </div>
      )}
    </div>
  );
};

export default LocalLibraryPanel;
