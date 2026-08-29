import { useState, useEffect, useCallback, useRef } from 'react';
import { apiGet, apiPost, apiDelete, errorMessage } from '../../api/client';

// 驗證評估的「耐久」狀態，由 Provider 掛載一次。
//
// 這裡的耐久性比其他 hook 更關鍵：一場評估要跑 45–60 秒，使用者幾乎一定會在等待期間
// 切去別的分頁。App.jsx 用純 && 條件渲染，切走等於整棵元件樹 unmount——輪詢迴圈放在
// 分頁本地就會直接消失，回來時看到的是空白畫面而 job 其實還在後端跑。
// 比照 useModelExport.js 的既有作法把輪詢放在 Provider 層。
const POLL_INTERVAL_MS = 2000;

export const useEvaluation = () => {
  const [targets, setTargets] = useState({ datasets: [], sessions: [] });
  const [targetsLoading, setTargetsLoading] = useState(false);
  const [jobs, setJobs] = useState([]);
  const [reports, setReports] = useState([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isGeneratingReport, setIsGeneratingReport] = useState(false);
  const [evalError, setEvalError] = useState(null);

  // 進行中的 job 才需要輪詢；用 ref 讓 interval 讀得到最新值而不必重建 interval
  const activeRef = useRef(false);

  const fetchTargets = useCallback(async () => {
    setTargetsLoading(true);
    try {
      const data = await apiGet('/evaluations/targets');
      setTargets({ datasets: data.datasets || [], sessions: data.sessions || [] });
    } catch (err) {
      console.error('[useEvaluation] Error fetching targets:', err);
    } finally {
      setTargetsLoading(false);
    }
  }, []);

  const fetchJobs = useCallback(async () => {
    try {
      const data = await apiGet('/evaluations');
      const list = data.jobs || [];
      setJobs(list);
      activeRef.current = list.some((j) => j.state === 'queued' || j.state === 'running');
    } catch (err) {
      console.error('[useEvaluation] Error fetching evaluations:', err);
    }
  }, []);

  const fetchReports = useCallback(async () => {
    try {
      const data = await apiGet('/reports');
      setReports(data.reports || []);
    } catch (err) {
      console.error('[useEvaluation] Error fetching reports:', err);
    }
  }, []);

  useEffect(() => {
    fetchJobs();
    fetchReports();
  }, [fetchJobs, fetchReports]);

  // 單一 interval 常駐，只在有進行中的 job 時才真的打 API——比起「每次狀態變化就
  // 重建 timer」更不容易漏掉或重複輪詢。
  useEffect(() => {
    const timer = setInterval(() => {
      if (activeRef.current) fetchJobs();
    }, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [fetchJobs]);

  const submitEvaluation = async (sessionId, datasetId, split) => {
    if (!sessionId || !datasetId) return false;
    setIsSubmitting(true);
    setEvalError(null);
    try {
      await apiPost('/evaluations', {
        session_id: sessionId,
        dataset_id: datasetId,
        split: split || null,
      });
      activeRef.current = true;
      await fetchJobs();
      return true;
    } catch (err) {
      console.error('[useEvaluation] Error submitting evaluation:', err);
      setEvalError(errorMessage(err, '送出評估失敗'));
      return false;
    } finally {
      setIsSubmitting(false);
    }
  };

  const deleteEvaluation = async (jobId) => {
    try {
      await apiDelete(`/evaluations/${jobId}`);
      await fetchJobs();
      return true;
    } catch (err) {
      console.error('[useEvaluation] Error deleting evaluation:', err);
      return false;
    }
  };

  const generateReport = async (jobIds, title) => {
    if (!jobIds || jobIds.length === 0) return null;
    setIsGeneratingReport(true);
    setEvalError(null);
    try {
      const data = await apiPost('/reports', { job_ids: jobIds, title: title || null });
      await fetchReports();
      return data.report;
    } catch (err) {
      console.error('[useEvaluation] Error generating report:', err);
      setEvalError(errorMessage(err, '報告產生失敗'));
      return null;
    } finally {
      setIsGeneratingReport(false);
    }
  };

  const deleteReport = async (reportId) => {
    try {
      await apiDelete(`/reports/${reportId}`);
      await fetchReports();
      return true;
    } catch (err) {
      console.error('[useEvaluation] Error deleting report:', err);
      return false;
    }
  };

  return {
    evalTargets: targets,
    evalTargetsLoading: targetsLoading,
    evalJobs: jobs,
    evalReports: reports,
    isSubmittingEval: isSubmitting,
    isGeneratingReport,
    evalError,
    setEvalError,
    fetchEvalTargets: fetchTargets,
    submitEvaluation,
    deleteEvaluation,
    generateReport,
    deleteReport,
  };
};
