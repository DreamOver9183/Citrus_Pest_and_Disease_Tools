import React from 'react';
import { UploadCloud, RefreshCw, Trash2, Sliders, Settings } from 'lucide-react';

// 右側：上傳與設定控制欄
const ControlPanel = ({
  currentDeviceLabel,
  getRootProps,
  getInputProps,
  isDragActive,
  sessionIds,
  sessions,
  selectedSessionId,
  setSelectedSessionId,
  sampleSize,
  setSampleSize,
  confThreshold,
  setConfThreshold,
  onConfCommit,
  uploadedFilesCount,
  onResample,
  resultsCount,
  onClear
}) => {
  return (
    <div className="lg:col-span-1 sticky top-24 self-start space-y-6">
      <div className="glass-panel p-5 rounded-2xl border border-white/[0.06] space-y-6 shadow-2xl relative overflow-hidden">
        <div className="absolute top-[-25%] right-[-15%] w-[120px] h-[120px] rounded-full bg-orange-500/5 blur-[40px] pointer-events-none"></div>

        {/* 標題 */}
        <div className="flex items-center justify-between pb-4 border-b border-white/5">
          <div className="flex items-center gap-2">
            <Sliders className="w-4 h-4 text-orange-400" />
            <h3 className="font-extrabold text-white text-xs tracking-wider uppercase font-sans">控制台設定</h3>
          </div>
          <div className="text-[9px] uppercase font-mono font-bold bg-green-500/10 text-green-400 border border-green-500/20 px-2.5 py-0.5 rounded-full">
            {currentDeviceLabel}
          </div>
        </div>

        {/* 上傳區 */}
        <div className="space-y-2">
          <label className="text-[11px] text-gray-400 font-bold tracking-wider uppercase block">1. 批次上傳影像</label>
          <div
            {...getRootProps()}
            className={`p-6 rounded-xl border-2 border-dashed text-center cursor-pointer transition-all duration-300 ${
              isDragActive
                ? 'border-orange-500 bg-orange-500/10 shadow-[0_0_20px_rgba(249,115,22,0.15)]'
                : 'border-white/10 hover:border-orange-500/30 hover:bg-slate-900/40'
            }`}
          >
            <input {...getInputProps()} />
            <UploadCloud className={`w-9 h-9 mx-auto mb-2 transition-transform duration-300 ${isDragActive ? '-translate-y-1 text-orange-400' : 'text-gray-400 hover:text-orange-400'}`} />
            <p className="text-[11px] text-gray-200 font-bold font-sans">拖曳圖片/資料夾或點擊</p>
            <p className="text-[9px] text-gray-500 mt-1 font-sans">支援多檔案、整包目錄掃描推論</p>
          </div>
        </div>

        {/* YOLO 權重選擇 */}
        <div className="space-y-2">
          <label className="text-[11px] text-gray-400 font-bold tracking-wider uppercase block">2. 選擇推理模型</label>
          <div className="relative">
            <select
              value={selectedSessionId}
              onChange={(e) => setSelectedSessionId(e.target.value)}
              className="w-full bg-[#060b1e]/90 border border-white/10 rounded-xl px-3.5 py-2.5 text-xs text-white focus:outline-none focus:border-orange-500 transition-colors cursor-pointer font-sans font-semibold appearance-none"
            >
              {sessionIds.map(id => (
                <option key={id} value={id}>
                  {sessions[id].custom_name}
                </option>
              ))}
            </select>
            <div className="absolute inset-y-0 right-3.5 flex items-center pointer-events-none text-gray-500">
              <Settings className="w-3.5 h-3.5" />
            </div>
          </div>
        </div>

        {/* 隨機測試數量選擇 */}
        <div className="space-y-2">
          <label className="text-[11px] text-gray-400 font-bold tracking-wider uppercase block">3. 隨機抽樣模式</label>
          <select
            value={sampleSize}
            onChange={(e) => setSampleSize(e.target.value)}
            className="w-full bg-[#060b1e]/90 border border-white/10 rounded-xl px-3.5 py-2.5 text-xs text-white focus:outline-none focus:border-orange-500 transition-colors cursor-pointer font-sans font-semibold"
          >
            <option value="1">隨機 1 張檢驗</option>
            <option value="4">隨機 4 張並列</option>
            <option value="9">隨機 9 張矩陣</option>
            <option value="all">載入全部圖片</option>
          </select>
        </div>

        {/* 信心度門檻 */}
        <div className="space-y-2.5">
          <div className="flex items-center justify-between text-[11px]">
            <label className="text-gray-400 font-bold tracking-wider uppercase flex items-center gap-1.5">
              4. 信心閾值 (Confidence)
              <div className="relative group inline-block">
                <button className="cursor-help w-4 h-4 rounded-full bg-white/10 hover:bg-orange-500 hover:text-white text-[10px] text-gray-400 font-bold transition-all flex items-center justify-center border border-white/10" aria-label="信心閥值說明">
                  ?
                </button>
                <div className="absolute right-0 top-full mt-2 w-64 p-3 bg-slate-950/95 border border-white/10 rounded-xl text-xs text-gray-300 shadow-2xl opacity-0 group-hover:opacity-100 pointer-events-none transition-all duration-300 z-50 leading-relaxed font-sans font-normal text-left backdrop-blur-md">
                  調高信心值可過濾背景噪聲；調低能提升潛在微小病蟲特徵檢出率。
                </div>
              </div>
            </label>
            <span className="text-orange-400 font-mono font-extrabold bg-orange-500/10 px-2 py-0.5 rounded">{confThreshold.toFixed(2)}</span>
          </div>
          <input
            type="range"
            min="0.1"
            max="0.9"
            step="0.05"
            value={confThreshold}
            onChange={(e) => setConfThreshold(parseFloat(e.target.value))}
            onMouseUp={() => onConfCommit(confThreshold)}
            onTouchEnd={() => onConfCommit(confThreshold)}
            className="w-full accent-orange-500 h-1 bg-white/10 rounded-lg cursor-pointer"
          />
        </div>

        {/* 按鈕組 */}
        <div className="pt-4 border-t border-white/5 space-y-2">
          {uploadedFilesCount > 0 && (
            <button
              onClick={onResample}
              className="w-full py-2.5 bg-gradient-to-r from-orange-500 to-amber-500 hover:from-orange-600 hover:to-amber-600 text-white font-extrabold text-xs rounded-xl transition-all shadow-lg hover:shadow-orange-500/20 cursor-pointer flex items-center justify-center gap-2 font-sans"
            >
              <RefreshCw className="w-3.5 h-3.5 animate-spin-slow" /> 重新抽樣 ({uploadedFilesCount} 張)
            </button>
          )}

          {resultsCount > 0 && (
            <button
              onClick={onClear}
              className="w-full py-2.5 bg-white/5 hover:bg-red-500/15 hover:text-red-400 hover:border-red-500/20 text-gray-400 font-extrabold border border-white/10 text-xs rounded-xl transition-all cursor-pointer flex items-center justify-center gap-2 font-sans"
            >
              <Trash2 className="w-3.5 h-3.5" /> 清除巡診歷史
            </button>
          )}
        </div>

      </div>
    </div>
  );
};

export default ControlPanel;
