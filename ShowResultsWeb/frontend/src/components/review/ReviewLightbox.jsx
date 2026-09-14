import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight, X } from 'lucide-react';
import { axios, errorMessage } from '../../api/client';
import { useExperiment } from '../../context/ExperimentContext';
import BoxOverlay from './BoxOverlay';
import { CHIP, LAYER_OPTIONS } from './reviewStyles';

const MIN_SCALE = 1;
const MAX_SCALE = 6;

// 讓影像在可用空間內等比例放到最大。長寬比必須與影像一致，SVG 疊加層的座標才會對齊。
const useFittedSize = (ref, aspect) => {
  const [size, setSize] = useState({ width: 0, height: 0 });
  useEffect(() => {
    const el = ref.current;
    if (!el || !aspect) return undefined;
    const update = () => {
      const { clientWidth, clientHeight } = el;
      if (!clientWidth || !clientHeight) return;
      const width = Math.min(clientWidth, clientHeight * aspect);
      setSize({ width, height: width / aspect });
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, [ref, aspect]);
  return size;
};

const Counts = ({ counts }) => (
  <span className="flex items-center gap-2 text-xs tabular-nums text-ds-neutral-500 flex-shrink-0">
    <span>正確 {counts.tp}</span>
    <span className="text-warning-300">漏 {counts.fn}</span>
    <span className="text-danger-300">誤 {counts.fp}</span>
    <span className="text-cat-12-400">錯 {counts.wrong}</span>
  </span>
);

const jobLabel = (job) =>
  `${job.session_name} · 解析度 ${job.imgsz_used ?? '模型預設'}${job.weight_format === 'tflite' ? ' · TFLite' : ''}`;

const Panel = ({ job, state, layer, transform, onWheel, onMouseDown }) => {
  const viewportRef = useRef(null);
  const item = state.item;
  const size = useFittedSize(viewportRef, item ? item.width / item.height : null);

  return (
    <section className="flex-1 min-w-0 flex flex-col rounded-ds border border-ds-neutral-800 bg-surface/40">
      <header className="flex items-center justify-between gap-3 px-3 py-2 border-b border-ds-neutral-800">
        <span className="text-xs text-ink truncate">{jobLabel(job)}</span>
        {item && <Counts counts={item.counts} />}
      </header>
      <div
        ref={viewportRef}
        className="relative flex-1 min-h-0 overflow-hidden flex items-center justify-center cursor-grab active:cursor-grabbing"
        onWheel={onWheel}
        onMouseDown={onMouseDown}
      >
        {item && size.width > 0 && (
          <div className="relative flex-shrink-0" style={{ width: size.width, height: size.height, transform }}>
            <img
              src={item.image_url}
              alt={item.name}
              draggable={false}
              className="absolute inset-0 w-full h-full select-none"
            />
            <BoxOverlay item={item} classNames={job.class_names} layer={layer} showLabels />
          </div>
        )}
        {!item && !state.error && <p className="text-sm text-ds-neutral-500">讀取中…</p>}
        {state.error && <p className="text-sm text-danger-300 px-4 text-center">{state.error}</p>}
      </div>
    </section>
  );
};

// 單張放大檢視：圖層切換、信心門檻（只重新查詢）、上一張／下一張，以及與另一次檢視並排。
//
// 並排的對象限定為**同一批影像**（image_set_key 相同）的已完成檢視——典型用法是 320 vs 640、
// .pt vs .tflite。兩側共用同一組縮放與平移，才能對著同一個位置比較框。
const ReviewLightbox = ({ job, names, startIndex, onClose }) => {
  const {
    reviewJobs,
    reviewFilters,
    updateReviewFilters,
    reviewCompareJobId,
    setReviewCompareJobId,
    fetchReviewItem,
  } = useExperiment();

  const [index, setIndex] = useState(startIndex);
  const [layer, setLayer] = useState('both');
  const [primary, setPrimary] = useState({ item: null, error: null });
  const [secondary, setSecondary] = useState({ item: null, error: null });
  const [scale, setScale] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [dragStart, setDragStart] = useState(null);
  const dialogRef = useRef(null);

  const name = names[index];
  const conf = reviewFilters.conf;
  const candidates = reviewJobs.filter(
    (j) => j.state === 'done' && j.job_id !== job.job_id && j.image_set_key && j.image_set_key === job.image_set_key
  );
  const compareJob = candidates.find((j) => j.job_id === reviewCompareJobId) || null;

  const go = useCallback(
    (delta) => setIndex((i) => Math.min(names.length - 1, Math.max(0, i + delta))),
    [names.length]
  );

  useEffect(() => {
    setScale(1);
    setOffset({ x: 0, y: 0 });
  }, [name]);

  useEffect(() => {
    const controller = new AbortController();
    const load = async (jobId, setter) => {
      try {
        const item = await fetchReviewItem(jobId, name, conf, controller.signal);
        setter({ item, error: null });
      } catch (err) {
        if (axios.isCancel(err)) return;
        setter({ item: null, error: errorMessage(err, '讀取失敗') });
      }
    };
    const timer = setTimeout(() => {
      load(job.job_id, setPrimary);
      if (compareJob) load(compareJob.job_id, setSecondary);
    }, 150);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [job.job_id, compareJob?.job_id, name, conf, fetchReviewItem]);

  useEffect(() => {
    document.body.style.overflow = 'hidden';
    dialogRef.current?.focus();
    const onKeyDown = (e) => {
      if (e.key === 'Escape') onClose();
      if (e.key === 'ArrowLeft') go(-1);
      if (e.key === 'ArrowRight') go(1);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => {
      document.body.style.overflow = '';
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [onClose, go]);

  useEffect(() => {
    if (!dragStart) return undefined;
    const onMove = (e) => setOffset({ x: e.clientX - dragStart.x, y: e.clientY - dragStart.y });
    const onUp = () => setDragStart(null);
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
  }, [dragStart]);

  const onWheel = (e) => {
    const next = Math.min(MAX_SCALE, Math.max(MIN_SCALE, scale + (e.deltaY > 0 ? -0.25 : 0.25)));
    setScale(next);
    if (next === MIN_SCALE) setOffset({ x: 0, y: 0 });
  };

  const onMouseDown = (e) => {
    if (scale === MIN_SCALE) return;
    e.preventDefault();
    setDragStart({ x: e.clientX - offset.x, y: e.clientY - offset.y });
  };

  const transform = `translate(${offset.x}px, ${offset.y}px) scale(${scale})`;

  return (
    <div
      ref={dialogRef}
      role="dialog"
      aria-modal="true"
      aria-label={`逐張檢視：${name}`}
      tabIndex={-1}
      className="fixed inset-0 z-50 flex flex-col bg-ground focus:outline-none"
    >
      <div className="flex items-center gap-x-4 gap-y-2 flex-wrap px-4 py-3 border-b border-ds-neutral-800">
        <div className="flex items-center gap-1.5">
          <button
            onClick={() => go(-1)}
            disabled={index === 0}
            aria-label="上一張"
            className="p-1.5 rounded-ds-sm border border-ds-neutral-700 text-ds-neutral-400 hover:text-ink disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>
          <span className="text-xs text-ds-neutral-500 tabular-nums w-14 text-center">
            {index + 1}／{names.length}
          </span>
          <button
            onClick={() => go(1)}
            disabled={index + 1 >= names.length}
            aria-label="下一張"
            className="p-1.5 rounded-ds-sm border border-ds-neutral-700 text-ds-neutral-400 hover:text-ink disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
          >
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>

        <span className="text-sm text-ink truncate max-w-[16rem]" title={name}>{name}</span>

        <div className="flex gap-1" role="group" aria-label="圖層">
          {LAYER_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => setLayer(opt.value)}
              aria-pressed={layer === opt.value}
              className={`px-2.5 py-1 rounded-ds-sm border text-xs transition-colors cursor-pointer ${
                layer === opt.value ? CHIP.on : CHIP.off
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>

        <label className="flex items-center gap-2 text-xs text-ds-neutral-500">
          信心門檻
          <input
            type="range"
            min={job.store_conf || 0.05}
            max="0.95"
            step="0.05"
            value={conf}
            onChange={(e) => updateReviewFilters({ conf: Number(e.target.value), page: reviewFilters.page })}
            className="w-28 h-1 cursor-pointer [accent-color:var(--color-accent)]"
          />
          <span className="text-ink tabular-nums w-8">{conf.toFixed(2)}</span>
        </label>

        <label className="flex items-center gap-2 text-xs text-ds-neutral-500">
          並排比較
          <select
            value={compareJob?.job_id || ''}
            onChange={(e) => setReviewCompareJobId(e.target.value || null)}
            disabled={candidates.length === 0}
            className="bg-ground border border-ds-neutral-700 rounded-ds px-2 py-1 text-xs text-ink focus:outline-none focus:border-accent cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed max-w-[16rem]"
          >
            <option value="">{candidates.length === 0 ? '無同批影像的其他檢視' : '不比較'}</option>
            {candidates.map((j) => (
              <option key={j.job_id} value={j.job_id}>{jobLabel(j)}</option>
            ))}
          </select>
        </label>

        <button
          onClick={onClose}
          aria-label="關閉"
          className="ml-auto p-1.5 rounded-ds-sm text-ds-neutral-500 hover:text-ink hover:bg-ds-neutral-800/60 transition-colors cursor-pointer focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2"
        >
          <X className="w-5 h-5" />
        </button>
      </div>

      <div className="flex-1 min-h-0 flex flex-col md:flex-row gap-3 p-3">
        <Panel job={job} state={primary} layer={layer} transform={transform} onWheel={onWheel} onMouseDown={onMouseDown} />
        {compareJob && (
          <Panel job={compareJob} state={secondary} layer={layer} transform={transform} onWheel={onWheel} onMouseDown={onMouseDown} />
        )}
      </div>

      <p className="px-4 pb-3 text-xs text-ds-neutral-600">
        實線為預測、虛線為標註。滾輪縮放、放大後可拖曳；← → 切換影像，Esc 關閉。
      </p>
    </div>
  );
};

export default ReviewLightbox;
