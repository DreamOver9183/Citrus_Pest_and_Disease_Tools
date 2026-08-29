import React, { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import {
  fmtDateTime,
  fmtInt,
  fmtMetric,
  fmtSeconds,
  shortSha,
} from './registryFormat';

/** 常被拿來比較的超參數優先列出，其餘收在「完整 args.yaml」底下。 */
const HIGHLIGHT_KEYS = [
  ['epochs', 'Epochs'],
  ['optimizer', 'Optimizer'],
  ['model_cfg', '基礎模型'],
  ['imgsz', '影像尺寸'],
  ['batch', 'Batch'],
  ['lr0', '初始 LR'],
  ['lrf', '最終 LR'],
  ['momentum', 'Momentum'],
  ['weight_decay', 'Weight decay'],
  ['patience', 'Patience'],
  ['seed', 'Seed'],
];

function Field({ label, value }) {
  return (
    <div className="rounded-lg border border-slate-700/50 bg-slate-900/50 px-3 py-2">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="mt-0.5 font-mono text-sm text-slate-200">
        {value === null || value === undefined || value === '' ? '—' : String(value)}
      </div>
    </div>
  );
}

/** 單一權重的明細：完整訓練超參數 + 歷次評估。 */
export default function WeightDetailPanel({ detail }) {
  const [showAllHyper, setShowAllHyper] = useState(false);

  if (!detail) {
    return (
      <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 p-6 text-center text-slate-500">
        載入明細中…
      </div>
    );
  }

  const { weight, training_run: run, evaluations } = detail;
  const allHyper = run?.hyperparameters || {};
  const extraKeys = Object.keys(allHyper)
    .filter((k) => !HIGHLIGHT_KEYS.some(([hk]) => hk === k) && k !== 'model')
    .sort();

  return (
    <div className="space-y-6 rounded-xl border border-emerald-500/30 bg-slate-900/60 p-5">
      <div>
        <h3 className="text-lg font-semibold text-slate-100">
          {weight.display_name || weight.filename}
        </h3>
        <p className="mt-1 text-xs text-slate-500">
          SHA-256 <code title={weight.sha256}>{shortSha(weight.sha256)}</code>
          {' · '}首次記錄 {fmtDateTime(weight.first_seen_at)}
          {' · '}最後出現 {fmtDateTime(weight.last_seen_at)}
        </p>
        {weight.class_names?.length > 0 && (
          <p className="mt-2 text-xs text-slate-400">
            類別表（{weight.class_names.length}）：{weight.class_names.join('、')}
          </p>
        )}
      </div>

      {/* --- 訓練超參數 --- */}
      <section>
        <h4 className="mb-2 text-sm font-semibold text-slate-300">訓練超參數</h4>
        {run ? (
          <>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
              {HIGHLIGHT_KEYS.map(([key, label]) => (
                <Field key={key} label={label} value={run[key]} />
              ))}
            </div>

            {extraKeys.length > 0 && (
              <div className="mt-3">
                <button
                  type="button"
                  onClick={() => setShowAllHyper((v) => !v)}
                  className="flex items-center gap-1 text-xs text-slate-400 transition-colors hover:text-slate-200"
                >
                  {showAllHyper ? (
                    <ChevronDown className="h-3.5 w-3.5" />
                  ) : (
                    <ChevronRight className="h-3.5 w-3.5" />
                  )}
                  完整 args.yaml（其餘 {extraKeys.length} 項）
                </button>
                {showAllHyper && (
                  <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
                    {extraKeys.map((key) => (
                      <Field key={key} label={key} value={allHyper[key]} />
                    ))}
                  </div>
                )}
              </div>
            )}

            <div className="mt-4">
              <h5 className="mb-2 text-xs font-semibold text-slate-400">
                訓練當時記錄的指標（results.csv 最後一列）
              </h5>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                <Field label="mAP@50" value={fmtMetric(run.map50)} />
                <Field label="mAP@50-95" value={fmtMetric(run.map50_95)} />
                <Field label="Precision" value={fmtMetric(run.precision)} />
                <Field label="Recall" value={fmtMetric(run.recall)} />
              </div>
              <p className="mt-2 text-xs text-slate-500">
                這些是訓練當時在<strong className="text-slate-400">當時那個 val split</strong>
                上的數字，與下方本系統重新跑出來的實測值不是同一回事，不可混為一談。
              </p>
            </div>
          </>
        ) : (
          <p className="text-sm text-slate-500">
            這顆權重沒有附帶 args.yaml 或 results.csv（散落的單一權重檔屬於正常情況）。
          </p>
        )}
      </section>

      {/* --- 歷次評估 --- */}
      <section>
        <h4 className="mb-2 text-sm font-semibold text-slate-300">
          歷次實測（{evaluations.length}）
        </h4>
        {evaluations.length === 0 ? (
          <p className="text-sm text-slate-500">
            這顆權重還沒有被實測過。到「驗證評估」分頁跑一次，結果會自動記進登錄簿。
          </p>
        ) : (
          <div className="space-y-3">
            {evaluations.map((ev) => (
              <div
                key={ev.job_id}
                className="rounded-lg border border-slate-700/50 bg-slate-900/50 p-3"
              >
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="text-sm text-slate-200">
                    {ev.dataset_name} / {ev.split}
                    <span className="ml-2 text-xs text-slate-500">
                      {fmtInt(ev.image_count)} 張影像 · 耗時 {fmtSeconds(ev.elapsed_seconds)}
                    </span>
                  </span>
                  <span className="text-xs text-slate-500">{fmtDateTime(ev.finished_at)}</span>
                </div>

                <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
                  <Field label="mAP@50" value={fmtMetric(ev.map50)} />
                  <Field label="mAP@50-95" value={fmtMetric(ev.map50_95)} />
                  <Field label="Precision" value={fmtMetric(ev.precision)} />
                  <Field label="Recall" value={fmtMetric(ev.recall)} />
                  <Field label="F1" value={fmtMetric(ev.f1)} />
                  <Field label="Micro-Acc" value={fmtMetric(ev.micro_accuracy)} />
                </div>

                {ev.micro_accuracy !== null && ev.micro_accuracy !== undefined && (
                  <p className="mt-2 text-xs text-slate-500">
                    Micro-Accuracy = TP/(TP+FP+FN) = {fmtInt(ev.micro_tp)}/(
                    {fmtInt(ev.micro_tp)}+{fmtInt(ev.micro_fp)}+{fmtInt(ev.micro_fn)})
                    ，於 conf ≥ {ev.conf_threshold} 且 IoU ≥ {ev.iou_threshold} 的固定門檻下統計。
                    這是門檻相依的單點量測，與對所有門檻積分的 mAP 不可直接並列解讀。
                  </p>
                )}

                {ev.vocab_status === 'name_drift' && (
                  <p className="mt-2 rounded border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-xs text-amber-300">
                    {ev.vocab_message}
                  </p>
                )}
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
