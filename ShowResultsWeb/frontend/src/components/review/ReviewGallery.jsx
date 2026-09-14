import React from 'react';
import { AlertTriangle, ChevronLeft, ChevronRight, Download, Images, RefreshCw } from 'lucide-react';
import { useExperiment } from '../../context/ExperimentContext';
import { REVIEW_PAGE_SIZE } from '../../context/hooks/useReview';
import BoxOverlay from './BoxOverlay';
import {
  BOX_STYLES,
  CHIP,
  COUNT_BADGE,
  GT_DASH,
  LEGEND,
  SORT_OPTIONS,
  STATUS_OPTIONS,
  classDot,
  shortClassName,
  statusCount,
} from './reviewStyles';

// 與後端 review_service.EXPORT_LIMIT_DEFAULT 一致
const EXPORT_LIMIT = 100;

const chipClass = (on) =>
  `px-2.5 py-1 rounded-ds-sm border text-xs transition-colors cursor-pointer focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2 ${
    on ? CHIP.on : CHIP.off
  }`;

const LegendSwatch = ({ status, dashed }) => (
  <svg width="22" height="10" aria-hidden="true" className="flex-shrink-0">
    <line
      x1="1" y1="5" x2="21" y2="5"
      stroke={BOX_STYLES[status].stroke}
      strokeWidth="2"
      strokeDasharray={dashed ? GT_DASH : undefined}
    />
  </svg>
);

const Stat = ({ label, value }) => (
  <div className="min-w-0">
    <p className="text-xs text-ds-neutral-500">{label}</p>
    <p className="text-base text-ink tabular-nums">{value ?? '—'}</p>
  </div>
);

// 目前選中之逐張檢視的圖庫：計數、篩選、縮圖格與分頁。
//
// 計數一律標成「逐張計數（非評估指標）」。工具包刻意不自己實作 mAP（architecture §7），
// 這裡的 TP／FP／FN 只是替影像分類、排序用的，不能被讀成 Precision 或 Recall。
const ReviewGallery = ({ job, onOpen }) => {
  const { reviewItems, reviewItemsLoading, reviewFilters, updateReviewFilters } = useExperiment();

  if (!job) {
    return (
      <div className="border border-dashed border-ds-neutral-800 rounded-ds px-6 py-16 text-center">
        <Images className="w-8 h-8 text-ds-neutral-700 mx-auto mb-4" />
        <p className="text-sm text-ink">還沒有可檢視的結果</p>
        <p className="text-sm text-ds-neutral-500 mt-1.5 max-w-sm mx-auto leading-relaxed">
          完成一次逐張檢視後，每張影像的標註框與預測框會疊在這裡。
        </p>
      </div>
    );
  }

  const data = reviewItems && reviewItems.job_id === job.job_id ? reviewItems : null;
  const classNames = job.class_names?.length ? job.class_names : data?.class_names || [];
  const summary = data?.summary;
  const totalPages = data ? Math.max(1, Math.ceil(data.total / REVIEW_PAGE_SIZE)) : 1;
  const issues = job.label_issues || {};
  const skippedLines = (issues.polygon || 0) + (issues.malformed || 0) + (issues.class_out_of_range || 0);

  // 匯出沿用畫面上的篩選條件：先篩出「有漏抓」再匯出，就是一份漏抓案例集
  const exportParams = new URLSearchParams({
    conf: String(reviewFilters.conf),
    status: reviewFilters.status,
    sort: reviewFilters.sort,
    limit: String(EXPORT_LIMIT),
  });
  if (reviewFilters.classes.length > 0) exportParams.set('classes', reviewFilters.classes.join(','));
  const exportHref = `/api/reviews/${job.job_id}/export?${exportParams}`;

  const toggleClass = (index) => {
    const current = reviewFilters.classes;
    updateReviewFilters({
      classes: current.includes(index) ? current.filter((c) => c !== index) : [...current, index],
    });
  };

  return (
    <div className="space-y-5">
      <header className="flex items-end justify-between gap-3 flex-wrap">
        <div className="min-w-0">
          <h3 className="text-base font-medium text-ink truncate">{job.session_name}</h3>
          <p className="text-sm text-ds-neutral-500 mt-0.5 tabular-nums">
            {job.dataset_name} / {job.split} · {job.image_count} 張 · 解析度 {job.imgsz_used ?? '模型預設'}
            {job.weight_format === 'tflite' ? ' · TFLite' : ''}
          </p>
        </div>
        <div className="flex items-center gap-3">
          {reviewItemsLoading && <RefreshCw className="w-4 h-4 text-accent animate-spin" aria-label="更新中" />}
          <a
            href={exportHref}
            download
            title={`以目前的篩選條件匯出（最多 ${EXPORT_LIMIT} 張），影像與框全部內嵌，可離線開啟或列印成 PDF`}
            className="flex items-center gap-2 px-3 py-1.5 rounded-ds border border-accent text-accent text-sm hover:bg-accent/10 active:bg-accent/20 transition-colors cursor-pointer focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2"
          >
            <Download className="w-3.5 h-3.5" />
            匯出 HTML
          </a>
        </div>
      </header>

      {job.vocab_check?.status === 'name_drift' && (
        <div className="rounded-ds border border-warning-700 bg-warning-900/40 px-3 py-2.5 text-xs text-warning-300 flex items-start gap-2">
          <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
          <span className="break-words">{job.vocab_check.message}</span>
        </div>
      )}

      {(issues.missing > 0 || skippedLines > 0 || job.unreadable?.length > 0) && (
        <ul className="text-xs text-ds-neutral-500 space-y-0.5 list-disc pl-4">
          {issues.missing > 0 && <li>{issues.missing} 張沒有標註檔，視為背景影像。</li>}
          {skippedLines > 0 && (
            <li>
              略過 {skippedLines} 行無法當成框的標註
              （多邊形 {issues.polygon || 0}、格式錯誤 {issues.malformed || 0}、類別超出範圍 {issues.class_out_of_range || 0}）。
            </li>
          )}
          {job.unreadable?.length > 0 && (
            <li title={job.unreadable.join('\n')}>{job.unreadable.length} 張影像無法解碼，未列入。</li>
          )}
        </ul>
      )}

      {/* 逐張計數 */}
      <section className="rounded-ds border border-ds-neutral-800 bg-surface/40 px-4 py-3 space-y-3">
        <div className="flex items-baseline justify-between gap-2 flex-wrap">
          <h4 className="text-sm font-medium text-ink">逐張計數（非評估指標）</h4>
          <span className="text-xs text-ds-neutral-600 tabular-nums">
            信心 ≥ {reviewFilters.conf.toFixed(2)}、同類別 IoU ≥ {job.iou_threshold}
          </span>
        </div>
        <div className="grid grid-cols-3 sm:grid-cols-6 gap-3">
          <Stat label="影像" value={summary?.images} />
          <Stat label="全對" value={summary?.clean} />
          <Stat label="正確框" value={summary?.tp} />
          <Stat label="漏抓框" value={summary?.fn} />
          <Stat label="誤報框" value={summary?.fp} />
          <Stat label="類別錯框" value={summary?.wrong} />
        </div>
        <p className="text-xs text-ds-neutral-600 leading-relaxed">
          只用來篩選與排序影像，不是 mAP、Precision 或 Recall；指標請看「指標評估」。
        </p>
      </section>

      {/* 篩選 */}
      <section className="space-y-3">
        <div className="flex items-center gap-3 flex-wrap">
          <label htmlFor="review-conf" className="text-xs text-ds-neutral-500 w-16 flex-shrink-0">信心門檻</label>
          <input
            id="review-conf"
            type="range"
            min={job.store_conf || 0.05}
            max="0.95"
            step="0.05"
            value={reviewFilters.conf}
            onChange={(e) => updateReviewFilters({ conf: Number(e.target.value) })}
            className="flex-1 min-w-[160px] h-1 cursor-pointer [accent-color:var(--color-accent)]"
          />
          <span className="text-sm text-ink tabular-nums w-10 text-right">{reviewFilters.conf.toFixed(2)}</span>
        </div>

        <div className="flex items-start gap-3">
          <span className="text-xs text-ds-neutral-500 w-16 flex-shrink-0 pt-1.5">狀態</span>
          <div className="flex flex-wrap gap-1.5">
            {STATUS_OPTIONS.map((opt) => {
              const count = statusCount(opt.value, summary);
              return (
                <button
                  key={opt.value}
                  onClick={() => updateReviewFilters({ status: opt.value })}
                  aria-pressed={reviewFilters.status === opt.value}
                  className={chipClass(reviewFilters.status === opt.value)}
                >
                  {opt.label}
                  {count != null && <span className="ml-1 text-ds-neutral-500 tabular-nums">{count}</span>}
                </button>
              );
            })}
          </div>
        </div>

        {classNames.length > 0 && (
          <div className="flex items-start gap-3">
            <span className="text-xs text-ds-neutral-500 w-16 flex-shrink-0 pt-1.5">類別</span>
            <div className="flex flex-wrap gap-1.5">
              {classNames.map((name, index) => (
                <button
                  key={name}
                  onClick={() => toggleClass(index)}
                  aria-pressed={reviewFilters.classes.includes(index)}
                  className={`${chipClass(reviewFilters.classes.includes(index))} flex items-center gap-1.5`}
                  aria-label={`${shortClassName(name)}（${name}）`}
                >
                  <span className={`w-2 h-2 rounded-full ${classDot(name)}`} />
                  {shortClassName(name)}
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-3">
            <label htmlFor="review-sort" className="text-xs text-ds-neutral-500 w-16 flex-shrink-0">排序</label>
            <select
              id="review-sort"
              value={reviewFilters.sort}
              onChange={(e) => updateReviewFilters({ sort: e.target.value })}
              className="bg-ground border border-ds-neutral-700 rounded-ds px-2.5 py-1.5 text-xs text-ink focus:outline-none focus:border-accent cursor-pointer"
            >
              {SORT_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-3 flex-wrap text-xs text-ds-neutral-500">
            {LEGEND.map((entry) => (
              <span key={entry.status} className="flex items-center gap-1.5">
                <LegendSwatch status={entry.status} dashed={entry.dashed} />
                {entry.label}
              </span>
            ))}
            <span className="text-ds-neutral-600">實線為預測、虛線為標註</span>
          </div>
        </div>
      </section>

      {/* 縮圖格 */}
      {data && data.items.length === 0 && (
        <p className="border border-dashed border-ds-neutral-800 rounded-ds px-6 py-10 text-center text-sm text-ds-neutral-500">
          沒有符合條件的影像。
        </p>
      )}

      {data && data.items.length > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3 items-start">
          {data.items.map((item, position) => (
            <button
              key={item.index}
              onClick={() => onOpen(data.items.map((i) => i.name), position)}
              aria-label={`開啟 ${item.name}：正確 ${item.counts.tp}、漏抓 ${item.counts.fn}、誤報 ${item.counts.fp}、類別錯 ${item.counts.wrong}`}
              className="text-left rounded-ds border border-ds-neutral-800 hover:border-ds-neutral-600 bg-surface/40 overflow-hidden transition-colors cursor-pointer focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2"
            >
              <div className="relative bg-ds-neutral-900" style={{ aspectRatio: `${item.width} / ${item.height}` }}>
                <img
                  src={item.thumb_url}
                  alt={item.name}
                  loading="lazy"
                  className="absolute inset-0 w-full h-full"
                />
                <BoxOverlay item={item} classNames={classNames} layer="both" />
              </div>
              <div className="px-2.5 py-2 space-y-1.5">
                <p className="text-xs text-ds-neutral-400 truncate" title={item.name}>{item.name}</p>
                <div className="flex flex-wrap gap-1">
                  {item.errors === 0 && (
                    <span className={`text-[10px] px-1.5 py-0.5 rounded-ds-sm border ${COUNT_BADGE.clean}`}>全對</span>
                  )}
                  {item.counts.fn > 0 && (
                    <span className={`text-[10px] px-1.5 py-0.5 rounded-ds-sm border tabular-nums ${COUNT_BADGE.fn}`}>漏 {item.counts.fn}</span>
                  )}
                  {item.counts.fp > 0 && (
                    <span className={`text-[10px] px-1.5 py-0.5 rounded-ds-sm border tabular-nums ${COUNT_BADGE.fp}`}>誤 {item.counts.fp}</span>
                  )}
                  {item.counts.wrong > 0 && (
                    <span className={`text-[10px] px-1.5 py-0.5 rounded-ds-sm border tabular-nums ${COUNT_BADGE.wrong}`}>錯 {item.counts.wrong}</span>
                  )}
                </div>
              </div>
            </button>
          ))}
        </div>
      )}

      {data && data.total > REVIEW_PAGE_SIZE && (
        <nav className="flex items-center justify-center gap-3 text-sm" aria-label="分頁">
          <button
            onClick={() => updateReviewFilters({ page: reviewFilters.page - 1 })}
            disabled={reviewFilters.page === 0}
            aria-label="上一頁"
            className="p-1.5 rounded-ds-sm border border-ds-neutral-700 text-ds-neutral-400 hover:text-ink disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>
          <span className="text-ds-neutral-500 tabular-nums">
            第 {reviewFilters.page + 1}／{totalPages} 頁 · 共 {data.total} 張
          </span>
          <button
            onClick={() => updateReviewFilters({ page: reviewFilters.page + 1 })}
            disabled={reviewFilters.page + 1 >= totalPages}
            aria-label="下一頁"
            className="p-1.5 rounded-ds-sm border border-ds-neutral-700 text-ds-neutral-400 hover:text-ink disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
          >
            <ChevronRight className="w-4 h-4" />
          </button>
        </nav>
      )}
    </div>
  );
};

export default ReviewGallery;
