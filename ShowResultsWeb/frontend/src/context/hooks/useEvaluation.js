import { useState, useEffect, useCallback, useRef } from 'react';
import axios from 'axios';

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
      const res = await axios.get('/api/evaluations/targets');
      if (res.data.status === 'success') {
        setTargets({ datasets: res.data.datasets || [], sessions: res.data.sessions || [] });
      }
    } catch (err) {
      console.error('[useEvaluation] Error fetching targets:', err);
    } finally {
      setTargetsLoading(false);
    }
  }, []);

  const fetchJobs = useCallback(async () => {
    try {
      const res = await axios.get('/api/evaluations');
      if (res.data.status === 'success') {
        const list = res.data.jobs || [];
        setJobs(list);
        activeRef.current = list.some((j) => j.state === 'queued' || j.state === 'running');
      }
    } catch (err) {
      console.error('[useEvaluation] Error fetching evaluations:', err);
    }
  }, []);

  const fetchReports = useCallback(async () => {
    try {
      const res = await axios.get('/api/reports');
      if (res.data.status === 'success') setReports(res.data.reports || []);
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
      const form = new FormData();
      form.append('session_id', sessionId);
      form.append('dataset_id', datasetId);
      if (split) form.append('split', split);

      const res = await axios.post('/api/evaluations', form);
      if (res.data.status === 'success') {
        activeRef.current = true;
        await fetchJobs();
        return true;
      }
      setEvalError(res.data.message || '送出評估失敗');
    } catch (err) {
      console.error('[useEvaluation] Error submitting evaluation:', err);
      setEvalError(err.response?.data?.detail || err.message || '連線後端 API 失敗');
    } finally {
      setIsSubmitting(false);
    }
    return false;
  };

  const deleteEvaluation = async (jobId) => {
    try {
      await axios.post(`/api/evaluations/${jobId}/delete`);
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
      const res = await axios.post('/api/reports', { job_ids: jobIds, title: title || null });
      if (res.data.status === 'success') {
        await fetchReports();
        return res.data.report;
      }
      setEvalError(res.data.message || '報告產生失敗');
    } catch (err) {
      console.error('[useEvaluation] Error generating report:', err);
      setEvalError(err.response?.data?.detail || err.message || '連線後端 API 失敗');
    } finally {
      setIsGeneratingReport(false);
    }
    return null;
  };

  const deleteReport = async (reportId) => {
    try {
      await axios.post(`/api/reports/${reportId}/delete`);
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
