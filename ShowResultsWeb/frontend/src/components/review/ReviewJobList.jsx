import React from 'react';
import { RefreshCw, Trash2 } from 'lucide-react';
import { useExperiment } from '../../context/ExperimentContext';
import { stateStyle } from '../system-specs/exportFormats';
import { formatElapsed, tfliteSuffix } from './reviewStyles';

// 逐張檢視紀錄。已完成的可點選成為目前檢視的對象。
//
// 進度條是真實的百分比（已處理張數／總張數）：與匯出不同，逐張推論每一張都回報得出來。
const ReviewJobList = () => {
  const { reviewJobs, reviewSelectedJobId, selectReviewJob, deleteReview } = useExperiment();

  if (reviewJobs.length === 0) {
    return <p className="text-xs text-ds-neutral-600">尚無逐張檢視紀錄。</p>;
  }

  return (
    <div className="space-y-2">
      {reviewJobs.map((job) => {
        const selected = job.job_id === reviewSelectedJobId;
        const running = job.state === 'queued' || job.state === 'running';
        const size = job.imgsz_used ?? job.imgsz_requested;
        return (
          <div
            key={job.job_id}
            className={`rounded-ds border px-3 py-2.5 space-y-2 transition-colors ${
              selected ? 'border-accent bg-accent/10' : 'border-ds-neutral-800'
            }`}
          >
            <div className="flex items-start justify-between gap-2">
              <button
                onClick={() => selectReviewJob(job.job_id)}
                disabled={job.state !== 'done'}
                aria-pressed={selected}
                aria-label={`檢視 ${job.session_name}（${job.dataset_name} / ${job.split}，解析度 ${size ?? '模型預設'}）`}
                className="min-w-0 text-left cursor-pointer disabled:cursor-default focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2 rounded-ds-sm"
              >
                <p className="text-sm text-ink truncate">{job.session_name}</p>
                <p className="text-xs text-ds-neutral-500 truncate tabular-nums">
                  {job.dataset_name} / {job.split} · 解析度 {size ?? '模型預設'}
                  {tfliteSuffix(job.session_name, job.weight_format)}
                </p>
              </button>
              <div className="flex items-center gap-1.5 flex-shrink-0">
                <span className={`text-[10px] px-1.5 py-0.5 rounded-ds-sm border ${stateStyle(job.state).chip}`}>
                  {stateStyle(job.state).label}
                </span>
                <button
                  onClick={() => deleteReview(job.job_id)}
                  aria-label={`刪除 ${job.session_name} 的逐張檢視`}
                  title={running ? '停止並刪除' : '刪除'}
                  className="p-1 rounded-ds-sm text-ds-neutral-500 hover:text-danger-300 transition-colors cursor-pointer focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>

            {running && (
              <div className="space-y-1.5">
                <div className="w-full h-1.5 rounded-full overflow-hidden bg-ds-neutral-800">
                  <div
                    className="bg-accent h-full transition-all duration-500 rounded-full"
                    style={{ width: `${job.progress}%` }}
                  />
                </div>
                <p className="flex items-center gap-1.5 text-xs text-ds-neutral-500 tabular-nums">
                  <RefreshCw className="w-3 h-3 animate-spin text-accent" />
                  {job.stage_label}
                  {job.image_count ? ` · ${job.processed}／${job.image_count} 張` : ''}
                  {job.elapsed_seconds != null ? ` · ${formatElapsed(job.elapsed_seconds)}` : ''}
                </p>
              </div>
            )}

            {job.state === 'done' && (
              <p className="text-xs text-ds-neutral-600 tabular-nums">
                {job.image_count} 張 · 耗時 {formatElapsed(job.elapsed_seconds)}
              </p>
            )}

            {job.state === 'failed' && (
              <p className="text-xs text-danger-300 break-words leading-relaxed">{job.message}</p>
            )}
          </div>
        );
      })}
    </div>
  );
};

export default ReviewJobList;
