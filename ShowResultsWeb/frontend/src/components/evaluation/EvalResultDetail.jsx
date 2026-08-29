import React, { useState } from 'react';
import { AlertTriangle, CheckCircle2, BarChart3, Grid3x3 } from 'lucide-react';
import ClassBreakdownTable from './ClassBreakdownTable';
import ApSizeScatter from './ApSizeScatter';
import { VOCAB_STYLES, formatElapsed, formatMetric } from './evalTheme';

const KPI = ({ label, value, accent }) => (
  <div className="bg-slate-950/50 rounded-xl p-3.5 border border-white/5">
    <p className="text-[9px] text-gray-500 uppercase font-mono tracking-wider">{label}</p>
    <p className={`text-xl font-extrabold font-mono mt-1 ${accent || 'text-white'}`}>{value}</p>
  </div>
);

// 單一評估結果的完整檢視。
const EvalResultDetail = ({ job, onOpenPlot }) => {
  const [plotKey, setPlotKey] = useState('confusion_matrix');

  if (!job || job.state !== 'done') return null;

  const vocab = job.vocab_check || {};
  const vocabStyle = VOCAB_STYLES[vocab.status];
  const plots = job.plot_urls || {};
  const plotKeys = Object.keys(plots);

  const PLOT_LABELS = {
    confusion_matrix: '混淆矩陣',
    confusion_matrix_normalized: '正規化混淆矩陣',
    pr_curve: 'PR 曲線',
    f1_curve: 'F1 曲線',
    p_curve: 'Precision 曲線',
    r_curve: 'Recall 曲線',
  };

  return (
    <div className="space-y-6">
      {/* 標頭 */}
      <div className="glass-panel p-6 rounded-2xl border border-white/[0.06] shadow-xl space-y-4">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div className="min-w-0">
            <h3 className="text-sm font-bold text-white">{job.session_name}</h3>
            <p className="text-[10px] text-gray-500 font-mono mt-0.5">
              {job.dataset_name} / {job.split} · {job.image_count?.toLocaleString()} 張影像 ·
              耗時 {formatElapsed(job.elapsed_seconds)}
            </p>
          </div>
          {vocabStyle && (
            <span
              className={`text-[9px] px-2 py-1 rounded-md border font-bold flex items-center gap-1 flex-shrink-0 ${vocabStyle.chip}`}
            >
              {vocab.status === 'match' ? (
                <CheckCircle2 className="w-3 h-3" />
              ) : (
                <AlertTriangle className="w-3 h-3" />
              )}
              {vocabStyle.label}
            </span>
          )}
        </div>

        {vocab.status === 'name_drift' && (
          <div className="p-3 bg-amber-500/10 border border-amber-500/30 text-amber-300 rounded-xl text-[11px] space-y-1">
            <p>{vocab.message}</p>
            {(vocab.differences || []).slice(0, 5).map((d) => (
              <p key={d.index} className="font-mono text-[10px] text-amber-400/80">
                索引 {d.index}：模型「{d.model}」 vs 資料集「{d.dataset}」
              </p>
            ))}
          </div>
        )}

        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
          <KPI label="mAP@50" value={formatMetric(job.overall?.map50)} accent="text-emerald-300" />
          <KPI label="mAP@50-95" value={formatMetric(job.overall?.map50_95)} />
          <KPI label="Precision" value={formatMetric(job.overall?.precision)} />
          <KPI label="Recall" value={formatMetric(job.overall?.recall)} />
          <KPI label="F1" value={formatMetric(job.overall?.f1)} />
          <KPI
            label="Micro-Acc"
            value={formatMetric(job.micro?.micro_accuracy)}
            accent="text-cyan-300"
          />
        </div>

        <p className="text-[9px] text-gray-500 leading-relaxed">
          以上數值由本機在此 split 上重新計算，與訓練過程留下的歷史數值無關。
          {job.speed_ms?.inference
            ? ` 單張推論約 ${job.speed_ms.inference.toFixed(1)} ms（CPU）。`
            : ''}
        </p>

        {/* Micro-Accuracy 的門檻前提必須跟著數字一起出現：它是門檻相依的單點量測，
            與對所有門檻積分的 mAP 不是同一類指標，放在一起而不說明會被誤讀。 */}
        {job.micro?.micro_accuracy !== null && job.micro?.micro_accuracy !== undefined && (
          <p className="text-[9px] text-cyan-300/70 leading-relaxed">
            Micro-Accuracy（Jaccard index）= TP/(TP+FP+FN) ={' '}
            {job.micro.tp.toLocaleString()}/({job.micro.tp.toLocaleString()}+
            {job.micro.fp.toLocaleString()}+{job.micro.fn.toLocaleString()})，
            於 conf ≥ {job.micro.conf_threshold} 且 IoU ≥ {job.micro.iou_threshold} 的固定門檻下統計
            （微平均 P={formatMetric(job.micro.micro_precision)}、R=
            {formatMetric(job.micro.micro_recall)}）。這是門檻相依的單點量測，
            與對所有門檻積分的 mAP 不可直接並列解讀。
          </p>
        )}
      </div>

      {/* 逐類別 */}
      <div className="glass-panel p-6 rounded-2xl border border-white/[0.06] shadow-xl">
        <h4 className="text-xs font-bold text-white tracking-widest uppercase flex items-center gap-2 mb-3">
          <Grid3x3 className="w-4 h-4 text-cyan-400" />
          逐類別表現
        </h4>
        <ClassBreakdownTable perClass={job.per_class} sizeProfile={job.size_profile} />
      </div>

      {/* AP × 尺寸 */}
      <div className="glass-panel p-6 rounded-2xl border border-white/[0.06] shadow-xl">
        <h4 className="text-xs font-bold text-white tracking-widest uppercase flex items-center gap-2 mb-1">
          <BarChart3 className="w-4 h-4 text-cyan-400" />
          AP 與物件尺度的關係
        </h4>
        <p className="text-[10px] text-gray-500 mb-3 leading-relaxed">
          每個點是一個類別。若低 AP 集中在左側（小物件），代表瓶頸在小尺度特徵擷取——
          這正是高解析度 P2 檢測層要解決的問題。
        </p>
        <ApSizeScatter perClass={job.per_class} sizeProfile={job.size_profile} />
      </div>

      {/* 圖表 */}
      {plotKeys.length > 0 && (
        <div className="glass-panel p-6 rounded-2xl border border-white/[0.06] shadow-xl space-y-3">
          <h4 className="text-xs font-bold text-white tracking-widest uppercase">評估圖表</h4>
          <div className="flex flex-wrap gap-1.5">
            {plotKeys.map((key) => (
              <button
                key={key}
                onClick={() => setPlotKey(key)}
                className={`px-3 py-1.5 rounded-lg text-[10px] font-bold border transition-all cursor-pointer ${
                  plotKey === key
                    ? 'bg-cyan-500/20 border-cyan-500/50 text-cyan-300'
                    : 'bg-white/5 border-white/10 text-gray-400 hover:border-white/25'
                }`}
              >
                {PLOT_LABELS[key] || key}
              </button>
            ))}
          </div>
          {plots[plotKey] && (
            <img
              src={plots[plotKey]}
              alt={PLOT_LABELS[plotKey] || plotKey}
              onClick={() => onOpenPlot?.(plots[plotKey])}
              className="w-full rounded-xl border border-white/10 bg-white cursor-zoom-in"
            />
          )}
        </div>
      )}
    </div>
  );
};

export default EvalResultDetail;
