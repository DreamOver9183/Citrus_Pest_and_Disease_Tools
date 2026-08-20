import React from 'react';
import { FolderTree, RefreshCw, Sparkles, AlertCircle, Trash2, FileArchive } from 'lucide-react';
import { formatNumber, formatTimestamp, formatLabel } from './datasetFormat';
import { FORMAT_STYLES } from './chartTheme';

// 左側：上傳區 + 已分析記錄清單
const DatasetUploadPanel = ({
  dropzone,
  isAnalyzing,
  uploadProgress,
  error,
  datasets,
  activeDatasetId,
  onSelect,
  onDelete,
}) => {
  const { getRootProps, getInputProps, isDragActive } = dropzone;
  const records = Object.values(datasets || {}).sort(
    (a, b) => String(b.created_at || '').localeCompare(String(a.created_at || ''))
  );

  return (
    <div className="lg:col-span-1 sticky top-24 self-start space-y-6">
      <div className="glass-panel p-6 rounded-2xl border border-white/[0.06] shadow-xl space-y-5 relative overflow-hidden">
        <div className="absolute top-[-25%] right-[-15%] w-[120px] h-[120px] rounded-full bg-rose-500/5 blur-[40px] pointer-events-none"></div>

        <div className="flex items-center justify-between">
          <h3 className="text-xs font-bold text-white tracking-widest uppercase flex items-center gap-2">
            <FolderTree className="w-4 h-4 text-rose-400" />
            上傳資料集
            <div className="relative group inline-block ml-1">
              <button
                className="cursor-help w-4 h-4 rounded-full bg-white/10 hover:bg-rose-500 hover:text-white text-[10px] text-gray-400 font-bold transition-all flex items-center justify-center border border-white/10 shadow-lg"
                aria-label="頁面說明"
              >
                ?
              </button>
              <div className="absolute left-1/2 -translate-x-1/2 top-full mt-2 w-72 p-4 bg-slate-950/95 border border-white/10 rounded-2xl text-xs text-gray-300 shadow-2xl opacity-0 group-hover:opacity-100 pointer-events-none transition-all duration-300 z-50 leading-relaxed font-sans font-normal backdrop-blur-md text-left">
                系統會自動辨識 YOLO / COCO / Pascal VOC 格式並統計圖片數、標註數與類別分佈。
                分析全程只讀取標註文字檔，<span className="text-rose-400 font-bold">不會解壓縮任何影像</span>，
                因此數 GB 的資料集也能快速分析且不佔用磁碟。
              </div>
            </div>
          </h3>
          <span className="text-[10px] text-rose-400 font-mono font-bold bg-rose-500/10 px-2 py-0.5 rounded-md">
            ZIP Only
          </span>
        </div>

        <div
          {...getRootProps()}
          className={`p-6 rounded-xl border-2 border-dashed text-center transition-all duration-300 relative flex flex-col items-center justify-center min-h-[190px] ${
            isAnalyzing ? 'cursor-wait' : 'cursor-pointer'
          } ${
            isDragActive
              ? 'border-rose-500 bg-rose-500/5 shadow-[0_0_20px_rgba(244,63,94,0.15)]'
              : 'border-white/10 hover:border-rose-500/40 hover:bg-rose-500/[0.01]'
          }`}
        >
          <input {...getInputProps()} />
          {isAnalyzing ? (
            <div className="space-y-3 w-full">
              <div className="relative flex items-center justify-center">
                <RefreshCw className="w-10 h-10 text-rose-400 animate-spin" />
                <Sparkles className="absolute w-4 h-4 text-pink-300 animate-pulse" />
              </div>
              <p className="text-xs text-white font-bold animate-pulse">
                {uploadProgress > 0 && uploadProgress < 100
                  ? `上傳中 ${uploadProgress}%`
                  : '正在解析資料集結構...'}
              </p>
              <p className="text-[10px] text-gray-500 font-mono">
                Scanning archive index &amp; annotations
              </p>
              {uploadProgress > 0 && (
                <div className="w-full bg-white/5 h-1.5 rounded-full overflow-hidden border border-white/5">
                  <div
                    className="bg-gradient-to-r from-rose-500 to-pink-400 h-full transition-all duration-300 rounded-full"
                    style={{ width: `${uploadProgress}%` }}
                  ></div>
                </div>
              )}
            </div>
          ) : (
            <>
              <div className="p-3 bg-white/5 rounded-2xl w-12 h-12 mx-auto flex items-center justify-center mb-3">
                <FileArchive className="w-6 h-6 text-rose-400" />
              </div>
              <p className="text-xs text-white font-bold">拖曳資料集 ZIP 或點擊選擇</p>
              <p className="text-[10px] text-gray-400 leading-relaxed max-w-[200px] mx-auto mt-1">
                支援 YOLO / COCO / Pascal VOC，可含巢狀資料夾
              </p>
            </>
          )}
        </div>

        {error && (
          <div className="p-3 bg-red-500/10 border border-red-500/30 text-red-400 rounded-xl text-[11px] flex items-start gap-2">
            <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
            <span className="break-words">{error}</span>
          </div>
        )}
      </div>

      {records.length > 0 && (
        <div className="glass-panel p-5 rounded-2xl border border-white/[0.06] shadow-xl space-y-3">
          <h3 className="text-xs font-bold text-white tracking-widest uppercase flex items-center gap-2 pb-3 border-b border-white/5">
            分析紀錄
            <span className="text-[9px] text-gray-500 font-mono normal-case tracking-normal">
              ({records.length})
            </span>
          </h3>
          <div className="space-y-2 max-h-[320px] overflow-y-auto pr-1">
            {records.map((record) => {
              const isActive = record.dataset_id === activeDatasetId;
              return (
                <div
                  key={record.dataset_id}
                  onClick={() => onSelect(record.dataset_id)}
                  className={`p-3 rounded-xl border transition-all cursor-pointer group ${
                    isActive
                      ? 'bg-rose-500/10 border-rose-500/30'
                      : 'border-white/5 hover:bg-slate-900/40 hover:border-white/10'
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <span
                      className="text-[11px] font-bold text-white truncate flex-1"
                      title={record.zip_name}
                    >
                      {record.zip_name}
                    </span>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        onDelete(record.dataset_id);
                      }}
                      className="text-gray-600 hover:text-red-400 transition-colors flex-shrink-0"
                      title="刪除此分析紀錄"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                  <div className="flex items-center gap-1.5 mt-1.5 flex-wrap">
                    <span
                      className={`text-[9px] px-1.5 py-0.5 rounded border font-mono font-bold ${
                        FORMAT_STYLES[record.format] || FORMAT_STYLES.yolo
                      }`}
                    >
                      {formatLabel(record.format)}
                    </span>
                    <span className="text-[9px] text-gray-500 font-mono">
                      {formatNumber(record.total_images)} 圖 / {formatNumber(record.total_annotations)} 標註
                    </span>
                  </div>
                  <p className="text-[9px] text-gray-600 font-mono mt-1">
                    {formatTimestamp(record.created_at)}
                  </p>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};

export default DatasetUploadPanel;
