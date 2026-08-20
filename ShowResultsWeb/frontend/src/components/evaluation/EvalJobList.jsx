import React from 'react';
import { Trash2, Loader2, CheckCircle2, XCircle, Clock } from 'lucide-react';
import { STATE_STYLES, formatElapsed, formatMetric } from './evalTheme';

const StateIcon = ({ state }) => {
  if (state === 'running') return <Loader2 className="w-3.5 h-3.5 animate-spin" />;
  if (state === 'done') return <CheckCircle2 className="w-3.5 h-3.5" />;
  if (state === 'failed') return <XCircle className="w-3.5 h-3.5" />;
  return <Clock className="w-3.5 h-3.5" />;
};

// 評估紀錄清單。勾選多筆即可產生對照報告。
//
// 進行中的 job 顯示不定量動畫 + 經過秒數 + log 尾巴，**不偽造百分比**——val() 沒有
// 中間進度 callback，給一個假的百分比只會讓使用者誤判剩餘時間。
const EvalJobList = ({ jobs, selectedIds, onToggle, onDelete }) => {
  if (jobs.length === 0) {
    return (
      <div className="glass-panel p-8 rounded-2xl border border-white/[0.06] text-center">
        <p className="text-xs text-gray-500">尚無評估紀錄。從左側送出第一次評估。</p>
      </div>
    );
  }

  return (
    <div className="space-y-2.5">
      {jobs.map((job) => {
        const style = STATE_STYLES[job.state] || STATE_STYLES.queued;
        const done = job.state === 'done';
        const active = job.state === 'running' || job.state === 'queued';

        return (
          <div
            key={job.job_id}
            className={`glass-panel rounded-xl border p-4 transition-all ${
              selectedIds.includes(job.job_id)
                ? 'border-cyan-500/40 bg-cyan-500/[0.04]'
                : 'border-white/[0.06]'
            }`}
          >
            <div className="flex items-start gap-3">
              {done && (
                <input
                  type="checkbox"
                  checked={selectedIds.includes(job.job_id)}
                  onChange={() => onToggle(job.job_id)}
                  className="mt-1 w-3.5 h-3.5 flex-shrink-0 accent-cyan-500 cursor-pointer"
                  title="選取以加入報告"
                />
              )}

              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-xs font-bold text-white truncate">{job.session_name}</span>
                  <span
                    className={`text-[9px] px-1.5 py-0.5 rounded border font-bold flex items-center gap-1 ${style.chip}`}
                  >
                    <StateIcon state={job.state} />
                    {job.stage_label || style.label}
                  </span>
                </div>

                <p className="text-[10px] text-gray-500 font-mono mt-1 truncate">
                  {job.dataset_name} / {job.split}
                  {job.image_count ? ` · ${job.image_count.toLocaleString()} 張` : ''}
                  {job.elapsed_seconds !== null && job.elapsed_seconds !== undefined
                    ? ` · ${formatElapsed(job.elapsed_seconds)}`
                    : ''}
                </p>

                {done && job.overall && (
                  <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2 text-[11px]">
                    <span className="text-gray-400">
                      mAP@50 <b className="text-emerald-300 font-mono">{formatMetric(job.overall.map50)}</b>
                    </span>
                    <span className="text-gray-400">
                      mAP@50-95 <b className="text-white font-mono">{formatMetric(job.overall.map50_95)}</b>
                    </span>
                    <span className="text-gray-400">
                      P <b className="text-white font-mono">{formatMetric(job.overall.precision)}</b>
                    </span>
                    <span className="text-gray-400">
                      R <b className="text-white font-mono">{formatMetric(job.overall.recall)}</b>
                    </span>
                  </div>
                )}

                {active && (
                  <>
                    <div className="mt-2 h-1 rounded-full bg-white/5 overflow-hidden">
                      <div className={`h-full w-1/3 rounded-full ${style.bar} animate-pulse`} />
                    </div>
                    {job.log_tail?.length > 0 && (
                      <p className="text-[9px] text-gray-600 font-mono mt-1.5 truncate">
                        {job.log_tail[job.log_tail.length - 1]}
                      </p>
                    )}
                  </>
                )}

                {job.message && (
                  <p
                    className={`text-[10px] mt-1.5 leading-relaxed ${
                      job.state === 'failed' ? 'text-red-400' : 'text-amber-400'
                    }`}
                  >
                    {job.message}
                  </p>
                )}
              </div>

              <button
                onClick={() => onDelete(job.job_id)}
                className="text-gray-600 hover:text-red-400 transition-colors cursor-pointer flex-shrink-0"
                title="刪除這筆評估"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
};

export default EvalJobList;
