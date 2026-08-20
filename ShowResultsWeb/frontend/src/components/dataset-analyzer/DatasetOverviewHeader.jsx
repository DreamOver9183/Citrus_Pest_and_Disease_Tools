import React from 'react';
import { FolderTree, AlertTriangle, CheckCircle2, Hash } from 'lucide-react';
import { FORMAT_STYLES } from './chartTheme';
import { formatLabel, formatMb, formatDuration, formatNumber } from './datasetFormat';

// 資料集標題列：格式徽章、根目錄、規模與分析耗時。
const DatasetOverviewHeader = ({ stats }) => {
  const prefixCheck = stats.prefix_check || {};
  const showPrefixCheck = prefixCheck.status && prefixCheck.status !== 'not_applicable';

  return (
    <div className="glass-panel p-6 rounded-2xl border border-white/[0.06] shadow-2xl space-y-4 relative overflow-hidden">
      <div className="absolute top-[-25%] right-[-8%] w-[180px] h-[180px] rounded-full bg-rose-500/5 blur-[60px] pointer-events-none"></div>

      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-3 min-w-0">
          <div className="p-2.5 bg-rose-500/10 rounded-xl text-rose-400 flex-shrink-0">
            <FolderTree className="w-5 h-5" />
          </div>
          <div className="min-w-0">
            <h2 className="text-sm font-extrabold text-white font-sans tracking-tight truncate">
              {stats.zip_name}
            </h2>
            <p className="text-[10px] text-gray-400 font-mono mt-0.5 truncate">
              {stats.root_prefix ? `根目錄 ${stats.root_prefix}` : '資料集位於壓縮檔根層'}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-1.5 flex-wrap justify-end">
          <span
            className={`text-[10px] px-2.5 py-1 rounded-md border font-mono font-bold ${
              FORMAT_STYLES[stats.format] || FORMAT_STYLES.yolo
            }`}
          >
            {formatLabel(stats.format)}
          </span>
          {stats.verified ? (
            <span className="text-[10px] px-2.5 py-1 rounded-md border font-mono font-bold bg-emerald-500/10 text-emerald-400 border-emerald-500/30 flex items-center gap-1">
              <CheckCircle2 className="w-3 h-3" />
              深度分析
            </span>
          ) : (
            <span className="text-[10px] px-2.5 py-1 rounded-md border font-mono font-bold bg-amber-500/10 text-amber-400 border-amber-500/30 flex items-center gap-1">
              <AlertTriangle className="w-3 h-3" />
              基本分析
            </span>
          )}
          {(stats.detected_candidates || [])
            .filter((c) => c !== stats.format)
            .map((c) => (
              <span
                key={c}
                className="text-[9px] px-2 py-1 rounded-md border font-mono bg-white/5 text-gray-400 border-white/10"
                title="壓縮檔中同時偵測到此格式的特徵"
              >
                +{formatLabel(c)}
              </span>
            ))}
        </div>
      </div>

      {!stats.verified && stats.unverified_note && (
        <div className="p-3 bg-amber-500/10 border border-amber-500/30 text-amber-300 rounded-xl text-[11px] flex items-start gap-2">
          <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
          <span>
            {stats.unverified_note}——本專案僅使用 YOLO 格式，
            COCO / Pascal VOC 的解析邏輯沒有真實素材可供驗證，統計數字請自行複核。
          </span>
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 pt-1">
        {[
          { label: '壓縮檔大小', value: formatMb(stats.zip_size_mb) },
          { label: '解壓後大小', value: formatMb(stats.uncompressed_size_mb) },
          { label: '壓縮檔成員數', value: formatNumber(stats.member_count) },
          { label: '分析耗時', value: formatDuration(stats.analysis_ms) },
        ].map((item) => (
          <div key={item.label} className="bg-slate-950/30 p-3 rounded-xl border border-white/5">
            <span className="text-gray-500 text-[9px] uppercase font-mono tracking-wider block">
              {item.label}
            </span>
            <span className="text-white text-xs font-mono font-bold mt-0.5 block">{item.value}</span>
          </div>
        ))}
      </div>

      {showPrefixCheck && (
        <div
          className={`p-3 rounded-xl border text-[11px] flex items-start gap-2 ${
            prefixCheck.status === 'ok'
              ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300'
              : 'bg-amber-500/10 border-amber-500/30 text-amber-300'
          }`}
        >
          <Hash className="w-4 h-4 flex-shrink-0 mt-0.5" />
          <span>
            檔名類別提示交叉檢查：
            <span className="font-mono font-bold">
              {' '}{formatNumber(prefixCheck.matched)} / {formatNumber(prefixCheck.checked)}{' '}
            </span>
            相符
            {prefixCheck.status === 'ok'
              ? '（檔名標示的類別皆確實出現在標註內容中）'
              : `，有 ${formatNumber(prefixCheck.mismatched)} 筆不符`}
          </span>
        </div>
      )}

      {stats.truncated && (
        <div className="p-3 bg-amber-500/10 border border-amber-500/30 text-amber-300 rounded-xl text-[11px] flex items-start gap-2">
          <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
          <span>資料集規模超出單次分析上限，僅分析了部分標註檔，統計為近似值。</span>
        </div>
      )}
    </div>
  );
};

export default DatasetOverviewHeader;
