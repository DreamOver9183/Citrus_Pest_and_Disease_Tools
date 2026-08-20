import React, { useEffect, useMemo, useState } from 'react';
import { GaugeCircle, AlertTriangle } from 'lucide-react';
import { useExperiment } from '../context/ExperimentContext';
import EvalLauncher from './evaluation/EvalLauncher';
import EvalJobList from './evaluation/EvalJobList';
import EvalResultDetail from './evaluation/EvalResultDetail';
import ReportPanel from './evaluation/ReportPanel';
import Lightbox from './Lightbox';

// 驗證評估分頁的協調器。
//
// 這是本系統第一個讓「模型」與「資料集」相遇的地方。在此之前兩者是完全不交集的
// 子系統：消融分析顯示的是訓練當時寫進 results.png 的舊數字，而那些數字可能來自
// 不同的資料集，因此模型之間並不真的可比。
const Evaluation = () => {
  const { evalJobs, deleteEvaluation, isUnzipped } = useExperiment();

  const [selectedIds, setSelectedIds] = useState([]);
  const [focusedId, setFocusedId] = useState(null);
  const [lightboxSrc, setLightboxSrc] = useState(null);

  const completed = useMemo(() => evalJobs.filter((j) => j.state === 'done'), [evalJobs]);

  // 預設聚焦最新完成的一筆，讓使用者一進來就看得到結果而不必先點一下
  useEffect(() => {
    if (completed.length === 0) {
      setFocusedId(null);
      return;
    }
    if (!focusedId || !completed.some((j) => j.job_id === focusedId)) {
      setFocusedId(completed[0].job_id);
    }
  }, [completed, focusedId]);

  // 已刪除的 job 要從選取清單移除，否則產生報告時會送出不存在的 id
  useEffect(() => {
    setSelectedIds((prev) => prev.filter((id) => completed.some((j) => j.job_id === id)));
  }, [completed]);

  const focused = completed.find((j) => j.job_id === focusedId) || null;

  const toggleSelect = (jobId) => {
    setSelectedIds((prev) =>
      prev.includes(jobId) ? prev.filter((id) => id !== jobId) : [...prev, jobId]
    );
    setFocusedId(jobId);
  };

  // 不同資料集/split 的指標不可直接比較——這正是本功能存在的理由，
  // 若在報告裡默默並列會比不做這功能更糟。
  const comparableHint = useMemo(() => {
    const chosen = completed.filter((j) => selectedIds.includes(j.job_id));
    if (chosen.length < 2) return '';
    const keys = new Set(chosen.map((j) => `${j.dataset_name}/${j.split}`));
    return keys.size === 1
      ? '這些評估使用同一份測試集，可直接比較。'
      : '⚠ 這些評估使用了不同的資料集或 split，指標不可直接比較。';
  }, [completed, selectedIds]);

  if (!isUnzipped) {
    return (
      <div className="glass-panel p-12 rounded-2xl border border-white/[0.06] text-center space-y-3">
        <GaugeCircle className="w-10 h-10 text-gray-700 mx-auto" />
        <p className="text-sm text-gray-400 font-bold">尚未載入任何模型</p>
        <p className="text-xs text-gray-600">
          請先在「模型與裝置」分頁載入模型與資料集，才能進行驗證評估。
        </p>
      </div>
    );
  }

  return (
    <>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-1 space-y-6">
          <EvalLauncher />
          <ReportPanel selectedIds={selectedIds} comparableHint={comparableHint} />
        </div>

        <div className="lg:col-span-2 space-y-6">
          <div>
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-xs font-bold text-white tracking-widest uppercase flex items-center gap-2">
                <GaugeCircle className="w-4 h-4 text-cyan-400" />
                評估紀錄
                <span className="text-gray-600 font-mono">({evalJobs.length})</span>
              </h3>
              {selectedIds.length > 1 && comparableHint.startsWith('⚠') && (
                <span className="text-[9px] text-amber-400 flex items-center gap-1">
                  <AlertTriangle className="w-3 h-3" />
                  選取的評估不可直接比較
                </span>
              )}
            </div>
            <EvalJobList
              jobs={evalJobs}
              selectedIds={selectedIds}
              onToggle={toggleSelect}
              onDelete={deleteEvaluation}
            />
          </div>

          {focused && <EvalResultDetail job={focused} onOpenPlot={setLightboxSrc} />}
        </div>
      </div>

      {lightboxSrc && (
        <Lightbox src={lightboxSrc} onClose={() => setLightboxSrc(null)} />
      )}
    </>
  );
};

export default Evaluation;
