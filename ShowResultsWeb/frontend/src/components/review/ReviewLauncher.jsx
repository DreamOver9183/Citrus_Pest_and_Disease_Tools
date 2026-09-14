import React, { useEffect, useMemo, useState } from 'react';
import { Play, RefreshCw, AlertCircle } from 'lucide-react';
import { useExperiment } from '../../context/ExperimentContext';
import { CHIP } from './reviewStyles';

const SELECT_CLASS =
  'w-full bg-ground border border-ds-neutral-700 rounded-ds px-3 py-2 text-sm text-ink focus:outline-none focus:border-accent transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2';

// 送出一次逐張檢視：挑模型、資料集、split 與推論解析度。
//
// 不可用的選項「顯示但停用並附原因」，比照評估與匯出的既有慣例。
// 表單選擇刻意留在元件本地：重選只要幾秒，而真正要跨分頁存活的 job 與結果在 useReview。
const ReviewLauncher = () => {
  const {
    reviewTargets,
    reviewTargetsLoading,
    fetchReviewTargets,
    submitReview,
    isSubmittingReview,
    reviewError,
  } = useExperiment();

  const [sessionId, setSessionId] = useState('');
  const [datasetId, setDatasetId] = useState('');
  const [split, setSplit] = useState('');
  const [imgsz, setImgsz] = useState('');

  useEffect(() => {
    fetchReviewTargets();
  }, [fetchReviewTargets]);

  const sessions = reviewTargets.sessions || [];
  const datasets = reviewTargets.datasets || [];
  const imgszChoices = reviewTargets.imgsz_choices || [];

  const selectedSession = sessions.find((s) => s.session_id === sessionId);
  const selectedDataset = useMemo(
    () => datasets.find((d) => d.dataset_id === datasetId),
    [datasets, datasetId]
  );
  // TFLite 的輸入尺寸在匯出時就固定了，指定別的解析度只會失敗
  const fixedSize = selectedSession?.weight_format === 'tflite';

  useEffect(() => {
    if (!sessionId) {
      const first = sessions.find((s) => s.available);
      if (first) setSessionId(first.session_id);
    }
    if (!datasetId) {
      const first = datasets.find((d) => d.available);
      if (first) setDatasetId(first.dataset_id);
    }
  }, [sessions, datasets, sessionId, datasetId]);

  useEffect(() => {
    if (selectedDataset?.default_split) setSplit(selectedDataset.default_split);
  }, [selectedDataset]);

  useEffect(() => {
    if (fixedSize) setImgsz('');
  }, [fixedSize]);

  const canSubmit =
    selectedSession?.available && selectedDataset?.available && split && !isSubmittingReview;

  const handleSubmit = async () => {
    await submitReview(sessionId, datasetId, split, imgsz);
  };

  return (
    <section className="rounded-ds border border-ds-neutral-800 bg-surface/40 p-5 space-y-4">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-medium text-ink">新增逐張檢視</h3>
        <button
          onClick={fetchReviewTargets}
          disabled={reviewTargetsLoading}
          className="px-2 py-1 rounded-ds-sm border border-ds-neutral-700 text-xs text-ds-neutral-400 hover:text-ink hover:border-ds-neutral-600 transition-colors cursor-pointer disabled:opacity-40 flex items-center gap-1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2"
        >
          <RefreshCw className={`w-3 h-3 ${reviewTargetsLoading ? 'animate-spin' : ''}`} />
          重新整理
        </button>
      </div>

      <label className="block space-y-1.5">
        <span className="text-xs text-ds-neutral-500">模型</span>
        <select value={sessionId} onChange={(e) => setSessionId(e.target.value)} className={SELECT_CLASS}>
          {sessions.length === 0 && <option value="">（尚未載入任何模型）</option>}
          {sessions.map((s) => (
            <option key={s.session_id} value={s.session_id} disabled={!s.available}>
              {s.name}
              {s.weight_format === 'tflite' ? '（TFLite）' : ''}
              {s.available ? '' : ' — 不支援'}
            </option>
          ))}
        </select>
        {selectedSession && !selectedSession.available && (
          <span className="block text-xs text-warning-300 leading-relaxed">{selectedSession.reason}</span>
        )}
      </label>

      <label className="block space-y-1.5">
        <span className="text-xs text-ds-neutral-500">資料集</span>
        <select value={datasetId} onChange={(e) => setDatasetId(e.target.value)} className={SELECT_CLASS}>
          {datasets.length === 0 && <option value="">（尚未載入任何資料集）</option>}
          {datasets.map((d) => (
            <option key={d.dataset_id} value={d.dataset_id} disabled={!d.available}>
              {d.name}
              {d.available ? '' : ' — 無法檢視'}
            </option>
          ))}
        </select>
        {selectedDataset && !selectedDataset.available && (
          <span className="block text-xs text-warning-300 leading-relaxed">{selectedDataset.reason}</span>
        )}
      </label>

      {selectedDataset?.available && selectedDataset.splits?.length > 0 && (
        <div className="space-y-1.5">
          <span className="text-xs text-ds-neutral-500">Split</span>
          <div className="flex flex-wrap gap-1.5">
            {selectedDataset.splits.map((name) => (
              <button
                key={name}
                onClick={() => setSplit(name)}
                aria-pressed={split === name}
                className={`px-3 py-1 rounded-ds-sm border text-xs transition-colors cursor-pointer focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2 ${
                  split === name ? CHIP.on : CHIP.off
                }`}
              >
                {name}
              </button>
            ))}
          </div>
        </div>
      )}

      <label className="block space-y-1.5">
        <span className="text-xs text-ds-neutral-500">推論解析度</span>
        <select
          value={imgsz}
          onChange={(e) => setImgsz(e.target.value)}
          disabled={fixedSize}
          className={SELECT_CLASS}
        >
          <option value="">{fixedSize ? '依匯出時的固定尺寸' : '模型預設（訓練尺寸）'}</option>
          {!fixedSize &&
            imgszChoices.map((size) => (
              <option key={size} value={size}>{size}</option>
            ))}
        </select>
      </label>

      <button
        onClick={handleSubmit}
        disabled={!canSubmit}
        className={`w-full py-2 rounded-ds border text-sm transition-colors flex items-center justify-center gap-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2 ${
          canSubmit
            ? 'border-accent text-accent hover:bg-accent/10 active:bg-accent/20 cursor-pointer'
            : 'border-ds-neutral-800 text-ds-neutral-600 cursor-not-allowed opacity-60'
        }`}
      >
        {isSubmittingReview ? (
          <><RefreshCw className="w-3.5 h-3.5 animate-spin" /> 送出中…</>
        ) : (
          <><Play className="w-3.5 h-3.5" /> 開始逐張檢視</>
        )}
      </button>

      <p className="text-xs text-ds-neutral-600 leading-relaxed">
        模型會逐張跑過所選 split 並存下所有框；之後調整信心門檻只重新配對，不重新推論。
      </p>

      {reviewError && (
        <div className="rounded-ds border border-danger-700 bg-danger-900/40 px-3 py-2.5 text-xs text-danger-300 flex items-start gap-2">
          <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
          <span className="break-words">{reviewError}</span>
        </div>
      )}
    </section>
  );
};

export default ReviewLauncher;
