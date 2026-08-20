import React, { useEffect, useMemo, useState } from 'react';
import { Play, RefreshCw, AlertCircle, Database, Box } from 'lucide-react';
import { useExperiment } from '../../context/ExperimentContext';

// 送出一場評估：挑模型、挑資料集、挑 split。
//
// 不可用的選項刻意「顯示但停用並附原因」，比照匯出面板的既有慣例——把上傳的 ZIP
// 資料集藏起來，使用者只會困惑於「我剛分析的資料集去哪了」，而真正的原因（分析不
// 解壓縮，位元組已釋放）永遠傳達不到。
const EvalLauncher = () => {
  const {
    evalTargets,
    evalTargetsLoading,
    fetchEvalTargets,
    submitEvaluation,
    isSubmittingEval,
    evalError,
  } = useExperiment();

  const [sessionId, setSessionId] = useState('');
  const [datasetId, setDatasetId] = useState('');
  const [split, setSplit] = useState('');

  useEffect(() => {
    fetchEvalTargets();
  }, [fetchEvalTargets]);

  const sessions = evalTargets.sessions || [];
  const datasets = evalTargets.datasets || [];

  const selectedDataset = useMemo(
    () => datasets.find((d) => d.dataset_id === datasetId),
    [datasets, datasetId]
  );

  // 預選第一個可用的項目，讓常見情況不需要任何點擊
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

  const canSubmit =
    sessionId &&
    datasetId &&
    selectedDataset?.available &&
    sessions.find((s) => s.session_id === sessionId)?.available &&
    !isSubmittingEval;

  const handleSubmit = async () => {
    const ok = await submitEvaluation(sessionId, datasetId, split);
    if (ok) fetchEvalTargets();
  };

  return (
    <div className="glass-panel p-6 rounded-2xl border border-white/[0.06] shadow-xl space-y-5">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-bold text-white tracking-widest uppercase flex items-center gap-2">
          <Play className="w-4 h-4 text-cyan-400" />
          送出評估
        </h3>
        <button
          onClick={fetchEvalTargets}
          disabled={evalTargetsLoading}
          className="text-[9px] px-2 py-1 bg-white/5 hover:bg-white/10 border border-white/10 rounded-md transition-all cursor-pointer font-bold flex items-center gap-1 disabled:opacity-40"
        >
          <RefreshCw className={`w-3 h-3 ${evalTargetsLoading ? 'animate-spin' : ''}`} />
          重新整理
        </button>
      </div>

      {/* 模型 */}
      <div className="space-y-1.5">
        <label className="text-[10px] text-gray-500 uppercase font-mono tracking-wider flex items-center gap-1.5">
          <Box className="w-3 h-3" /> 模型
        </label>
        <select
          value={sessionId}
          onChange={(e) => setSessionId(e.target.value)}
          className="w-full bg-slate-950/60 border border-white/10 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-cyan-500/50 cursor-pointer"
        >
          {sessions.length === 0 && <option value="">（尚未載入任何模型）</option>}
          {sessions.map((s) => (
            <option key={s.session_id} value={s.session_id} disabled={!s.available}>
              {s.name}
              {s.epochs && s.epochs !== 'N/A' ? ` · ${s.epochs} epochs` : ''}
              {s.available ? '' : ' —（不支援）'}
            </option>
          ))}
        </select>
        {sessions.find((s) => s.session_id === sessionId && !s.available) && (
          <p className="text-[9px] text-amber-400">
            {sessions.find((s) => s.session_id === sessionId).reason}
          </p>
        )}
      </div>

      {/* 資料集 */}
      <div className="space-y-1.5">
        <label className="text-[10px] text-gray-500 uppercase font-mono tracking-wider flex items-center gap-1.5">
          <Database className="w-3 h-3" /> 資料集
        </label>
        <select
          value={datasetId}
          onChange={(e) => setDatasetId(e.target.value)}
          className="w-full bg-slate-950/60 border border-white/10 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-cyan-500/50 cursor-pointer"
        >
          {datasets.length === 0 && <option value="">（尚未載入任何資料集）</option>}
          {datasets.map((d) => (
            <option key={d.dataset_id} value={d.dataset_id} disabled={!d.available}>
              {d.name}
              {d.available ? '' : ' —（無法評估）'}
            </option>
          ))}
        </select>
        {selectedDataset && !selectedDataset.available && (
          <p className="text-[9px] text-amber-400 leading-relaxed">{selectedDataset.reason}</p>
        )}
      </div>

      {/* Split */}
      {selectedDataset?.available && selectedDataset.splits?.length > 0 && (
        <div className="space-y-1.5">
          <label className="text-[10px] text-gray-500 uppercase font-mono tracking-wider">
            評估 Split
          </label>
          <div className="flex flex-wrap gap-1.5">
            {selectedDataset.splits.map((name) => (
              <button
                key={name}
                onClick={() => setSplit(name)}
                className={`px-3 py-1.5 rounded-lg text-[11px] font-bold border transition-all cursor-pointer ${
                  split === name
                    ? 'bg-cyan-500/20 border-cyan-500/50 text-cyan-300'
                    : 'bg-white/5 border-white/10 text-gray-400 hover:border-white/25'
                }`}
              >
                {name}
              </button>
            ))}
          </div>
          {split === 'train' && (
            <p className="text-[9px] text-amber-400">
              train 是模型見過的資料，指標會過度樂觀。作為泛化能力的依據請用 test。
            </p>
          )}
        </div>
      )}

      <button
        onClick={handleSubmit}
        disabled={!canSubmit}
        className={`w-full py-2.5 text-white font-extrabold text-xs rounded-xl transition-all shadow-lg flex items-center justify-center gap-2 ${
          canSubmit
            ? 'bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-600 hover:to-blue-700 hover:shadow-cyan-500/20 cursor-pointer'
            : 'bg-white/5 text-gray-500 cursor-not-allowed opacity-50'
        }`}
      >
        {isSubmittingEval ? (
          <>
            <RefreshCw className="w-3.5 h-3.5 animate-spin" /> 送出中...
          </>
        ) : (
          <>
            <Play className="w-3.5 h-3.5" /> 開始評估
          </>
        )}
      </button>

      <p className="text-[9px] text-gray-500 leading-relaxed">
        評估會讓模型實際跑過所選 split 並重新計算指標，與訓練時記錄的舊數值無關。
        CPU 上實測單張約 0.4 秒，445 張影像約需 4 分鐘；期間可自由切換分頁，進度不會遺失。
      </p>

      {evalError && (
        <div className="p-3 bg-red-500/10 border border-red-500/30 text-red-400 rounded-xl text-[11px] flex items-start gap-2">
          <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
          <span className="break-words">{evalError}</span>
        </div>
      )}
    </div>
  );
};

export default EvalLauncher;
