import React, { useState } from 'react';
import { Package, RefreshCw, ArrowDownToLine, AlertCircle, AlertTriangle, Cog, Trash2 } from 'lucide-react';
import { useExperiment } from '../../context/ExperimentContext';
import {
  formatBadgeClass,
  stateStyle,
  formatBytesLabel,
  formatElapsed,
  isIndeterminateStage,
} from './exportFormats';

// 單一 session 卡片上的「模型格式轉換」區塊。
//
// 五種互斥狀態：不符資格 / 閒置 / 進行中 / 完成 / 失敗。
// 不可用的格式刻意「顯示但停用」而非隱藏 —— 使用者應該知道 TFLite 存在、
// 以及要怎樣才能用它（跑 Docker），而不是以為系統沒這個功能。
const ExportPanel = ({ session }) => {
  const {
    exportCapabilities,
    capabilitiesLoading,
    latestJobBySession,
    startExport,
    deleteExportJob,
  } = useExperiment();

  const formats = exportCapabilities?.formats || [];
  const firstAvailable = formats.find((f) => f.available);
  const [selected, setSelected] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  const job = latestJobBySession?.[session.session_id];
  const chosen = selected || firstAvailable?.format || formats[0]?.format || 'onnx';
  const chosenInfo = formats.find((f) => f.format === chosen);

  // 逐 session 閘：SSDLite 或已是匯出格式者不提供轉換
  const modelArch = (session.model_arch || 'yolo').toLowerCase();
  const weightsSuffix = (session.weights_path || '').split('.').pop().toLowerCase();
  let ineligibleReason = null;
  if (modelArch !== 'yolo') {
    ineligibleReason = `僅支援 YOLO 架構的權重匯出，此模型為 ${session.format_label || modelArch}。`;
  } else if (weightsSuffix !== 'pt') {
    ineligibleReason = `此 Session 已是 ${session.format_label || weightsSuffix.toUpperCase()} 格式，無法再次匯出。`;
  }

  const handleExport = async () => {
    setSubmitting(true);
    try {
      await startExport(session.session_id, chosen);
    } finally {
      setSubmitting(false);
    }
  };

  const header = (
    <div className="flex items-center justify-between gap-2 flex-wrap">
      <span className="flex items-center gap-2 text-[11px] font-bold text-white tracking-wider uppercase">
        <Package className="w-3.5 h-3.5 text-orange-400" />
        模型格式轉換
      </span>
      {job && (
        <span className={`text-[9px] px-2 py-0.5 rounded-md border font-mono font-bold ${stateStyle(job.state).chip}`}>
          {stateStyle(job.state).label}
        </span>
      )}
    </div>
  );

  // (a) 不符資格
  if (ineligibleReason) {
    return (
      <div className="pl-2 space-y-2">
        {header}
        <div className="bg-white/5 border border-white/10 rounded-xl p-3 flex items-start gap-2">
          <Package className="w-3.5 h-3.5 text-gray-600 flex-shrink-0 mt-0.5" />
          <span className="text-[10px] text-gray-500 leading-relaxed">{ineligibleReason}</span>
        </div>
      </div>
    );
  }

  // (c) 進行中
  if (job && (job.state === 'queued' || job.state === 'running')) {
    const indeterminate = isIndeterminateStage(job.stage);
    return (
      <div className="pl-2 space-y-2">
        {header}
        <div className="bg-slate-950/40 border border-white/5 rounded-xl p-3 space-y-2.5">
          <div className="flex items-center justify-between gap-2 text-[10px]">
            <span className="flex items-center gap-2 text-orange-400 font-bold">
              <RefreshCw className="w-3.5 h-3.5 animate-spin" />
              {job.stage_label}
              <span className="text-gray-500 font-mono uppercase">{job.format}</span>
            </span>
            <span className="text-gray-500 font-mono">{formatElapsed(job.elapsed_seconds)}</span>
          </div>

          <div className="w-full bg-white/5 h-1.5 rounded-full overflow-hidden border border-white/5">
            {indeterminate ? (
              <div className="bg-gradient-to-r from-orange-500 to-amber-400 h-full w-full rounded-full animate-pulse"></div>
            ) : (
              <div
                className="bg-gradient-to-r from-orange-500 to-amber-400 h-full transition-all duration-500 rounded-full"
                style={{ width: `${job.progress}%` }}
              ></div>
            )}
          </div>

          {job.log_tail?.length > 0 && (
            <div className="space-y-0.5">
              {job.log_tail.slice(-2).map((line, i) => (
                <p key={i} className="text-[9px] font-mono text-gray-600 truncate">{line}</p>
              ))}
            </div>
          )}
        </div>
      </div>
    );
  }

  // (d) 完成
  if (job && job.state === 'done') {
    return (
      <div className="pl-2 space-y-2">
        {header}
        <div className="space-y-2">
          <a
            href={job.download_url}
            download
            className="w-full py-2.5 bg-gradient-to-r from-orange-500 to-amber-500 hover:from-orange-600 hover:to-amber-600 text-white font-extrabold text-xs rounded-xl transition-all shadow-lg hover:shadow-orange-500/20 cursor-pointer inline-flex items-center justify-center gap-2 font-sans"
            title={job.artifact_name}
          >
            <ArrowDownToLine className="w-3.5 h-3.5" />
            <span className="truncate max-w-[240px]">下載 {job.artifact_name}</span>
          </a>
          <div className="flex items-center justify-between gap-2 text-[9px] text-gray-500 font-mono">
            <span>
              {formatBytesLabel(job.artifact_size_mb)} · {formatElapsed(job.elapsed_seconds)}
              {job.imgsz ? ` · 輸入 ${job.imgsz}×${job.imgsz}` : ''}
            </span>
            <button
              onClick={() => deleteExportJob(job.job_id)}
              className="px-2 py-1 bg-white/5 hover:bg-red-500/15 hover:text-red-400 border border-white/10 rounded-md transition-all cursor-pointer font-bold font-sans flex items-center gap-1"
              title="移除此匯出產物"
            >
              <Trash2 className="w-3 h-3" /> 移除
            </button>
          </div>
        </div>
      </div>
    );
  }

  // (e) 失敗
  const failedBlock = job && job.state === 'failed' && (
    <div className="p-3 bg-red-500/10 border border-red-500/30 text-red-400 rounded-xl text-[11px] flex items-start gap-2">
      <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
      <div className="min-w-0 space-y-1">
        <p className="break-words">{job.message}</p>
        {job.log_tail?.length > 0 && (
          <p className="text-[9px] font-mono text-red-400/60 truncate">{job.log_tail.slice(-1)[0]}</p>
        )}
      </div>
    </div>
  );

  // (b) 閒置
  return (
    <div className="pl-2 space-y-2">
      {header}

      {failedBlock}

      {capabilitiesLoading ? (
        <p className="text-[10px] text-gray-600 font-mono">正在檢查可用的匯出格式...</p>
      ) : (
        <div className="space-y-2">
          <select
            value={chosen}
            onChange={(e) => setSelected(e.target.value)}
            className="w-full bg-[#060b1e]/90 border border-white/10 rounded-xl px-3.5 py-2.5 text-xs text-white focus:outline-none focus:border-orange-500 transition-colors cursor-pointer font-sans font-semibold"
          >
            {formats.map((f) => (
              <option key={f.format} value={f.format} disabled={!f.available}>
                {f.label}{f.available ? '' : ' — 不可用'}
              </option>
            ))}
          </select>

          {chosenInfo && !chosenInfo.available && (
            <div className="p-3 bg-amber-500/10 border border-amber-500/30 text-amber-400 rounded-xl text-[11px] flex items-start gap-2">
              <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
              <span className="break-words">{chosenInfo.reason}</span>
            </div>
          )}

          {chosenInfo?.available && chosenInfo.warnings?.length > 0 && (
            <div className="space-y-1">
              {chosenInfo.warnings.map((w, i) => (
                <p key={i} className="text-[9px] text-amber-400/80 font-sans leading-relaxed">※ {w}</p>
              ))}
            </div>
          )}

          <button
            onClick={handleExport}
            disabled={!chosenInfo?.available || submitting}
            className={`w-full py-2.5 font-extrabold text-xs rounded-xl transition-all flex items-center justify-center gap-2 font-sans ${
              !chosenInfo?.available || submitting
                ? 'bg-white/5 text-gray-600 border border-white/10 cursor-not-allowed opacity-60'
                : 'bg-gradient-to-r from-orange-500 to-amber-500 hover:from-orange-600 hover:to-amber-600 text-white shadow-lg hover:shadow-orange-500/20 cursor-pointer'
            }`}
          >
            {submitting ? (
              <><RefreshCw className="w-3.5 h-3.5 animate-spin" /> 送出中...</>
            ) : (
              <><Cog className="w-3.5 h-3.5" /> 轉換為 {chosenInfo?.label || chosen}</>
            )}
          </button>

          {chosenInfo?.description && chosenInfo.available && (
            <p className="text-[9px] text-gray-600 font-sans leading-relaxed">{chosenInfo.description}</p>
          )}
        </div>
      )}
    </div>
  );
};

export default ExportPanel;
