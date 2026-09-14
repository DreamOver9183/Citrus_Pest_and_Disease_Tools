import { useState, useEffect, useCallback, useRef } from 'react';
import { apiGet, apiPost, apiDelete, errorMessage, axios } from '../../api/client';

// 逐張檢視（看圖驗收）的耐久狀態，由 Provider 掛載一次。
//
// 一次檢視要逐張跑完整個 split（CPU 上數分鐘），使用者一定會在等待期間切去別的分頁；
// 看結果時設好的篩選條件、翻到的頁數，切回來也還要在。App.jsx 用純 && 條件渲染，
// 放在分頁元件本地就會隨 unmount 消失（CLAUDE.md 硬規則 2）。
//
// 輪詢比照 useModelExport 的自排程 setTimeout 鏈：請求不會重疊，背景分頁被節流時只是
// 變慢；分頁重新可見時立刻補一次。
//
// 逐張結果的查詢（拖門檻滑桿、切篩選）只打 /items，**不重新推論**；舊請求用
// AbortController 取消，避免慢的舊回應蓋掉新條件的結果。

const POLL_FAST_MS = 1000;
const POLL_SLOW_MS = 3000;
const FAST_WINDOW_MS = 20000;
const QUERY_DEBOUNCE_MS = 200;
export const REVIEW_PAGE_SIZE = 24;

const DEFAULT_FILTERS = { conf: 0.25, classes: [], status: 'all', sort: 'errors', page: 0 };

const isActive = (job) => job.state === 'queued' || job.state === 'running';

export const useReview = () => {
  // 驗證評估分頁內的模式：'metrics'（指標評估）或 'review'（逐張檢視）
  const [view, setView] = useState('metrics');
  const [targets, setTargets] = useState({ datasets: [], sessions: [], imgsz_choices: [] });
  const [targetsLoading, setTargetsLoading] = useState(false);
  const [jobs, setJobs] = useState([]);
  const [selectedJobId, setSelectedJobId] = useState(null);
  const [compareJobId, setCompareJobId] = useState(null);
  const [filters, setFilters] = useState(DEFAULT_FILTERS);
  const [items, setItems] = useState(null);
  const [itemsLoading, setItemsLoading] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState(null);

  // 捲動位置只在離開／回到分頁時讀寫，不需要觸發重新渲染
  const scrollRef = useRef(0);
  const pollStartRef = useRef(0);
  const itemsAbortRef = useRef(null);

  const fetchTargets = useCallback(async () => {
    setTargetsLoading(true);
    try {
      const data = await apiGet('/reviews/targets');
      setTargets({
        datasets: data.datasets || [],
        sessions: data.sessions || [],
        imgsz_choices: data.imgsz_choices || [],
      });
    } catch (err) {
      console.error('[useReview] Error fetching targets:', err);
    } finally {
      setTargetsLoading(false);
    }
  }, []);

  const fetchJobs = useCallback(async () => {
    try {
      const data = await apiGet('/reviews');
      setJobs(data.jobs || []);
    } catch (err) {
      console.error('[useReview] Error fetching reviews:', err);
    }
  }, []);

  useEffect(() => {
    fetchJobs();
  }, [fetchJobs]);

  const hasActiveJob = jobs.some(isActive);

  useEffect(() => {
    if (!hasActiveJob) {
      pollStartRef.current = 0;
      return undefined;
    }
    let cancelled = false;
    let timer = null;
    if (!pollStartRef.current) pollStartRef.current = Date.now();

    const nextDelay = () =>
      Date.now() - pollStartRef.current < FAST_WINDOW_MS ? POLL_FAST_MS : POLL_SLOW_MS;

    const tick = async () => {
      await fetchJobs();
      if (!cancelled) timer = setTimeout(tick, nextDelay());
    };
    timer = setTimeout(tick, nextDelay());

    const onVisible = () => {
      if (document.visibilityState === 'visible' && !cancelled) {
        pollStartRef.current = Date.now();
        clearTimeout(timer);
        timer = setTimeout(tick, 0);
      }
    };
    document.addEventListener('visibilitychange', onVisible);

    return () => {
      cancelled = true;
      clearTimeout(timer);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [hasActiveJob, fetchJobs]);

  // 選中的必須是已完成的 job；被刪除或被淘汰時退回最新完成的一筆
  useEffect(() => {
    const done = jobs.filter((j) => j.state === 'done');
    const fallback = done[0]?.job_id ?? null;
    if (!done.some((j) => j.job_id === selectedJobId) && selectedJobId !== fallback) {
      setSelectedJobId(fallback);
      setFilters((prev) => ({ ...prev, classes: [], page: 0 }));
    }
    if (compareJobId && !done.some((j) => j.job_id === compareJobId)) setCompareJobId(null);
  }, [jobs, selectedJobId, compareJobId]);

  const selectJob = useCallback((jobId) => {
    setSelectedJobId(jobId);
    setCompareJobId(null);
    // 類別索引屬於各自的模型詞彙，換 job 時清掉；門檻、狀態與排序沿用
    setFilters((prev) => ({ ...prev, classes: [], page: 0 }));
    scrollRef.current = 0;
  }, []);

  // 任何條件改變都回到第一頁，除非呼叫端明確指定頁數
  const updateFilters = useCallback((patch) => {
    setFilters((prev) => ({ ...prev, ...patch, page: patch.page ?? 0 }));
  }, []);

  useEffect(() => {
    if (!selectedJobId) {
      setItems(null);
      return undefined;
    }
    const timer = setTimeout(async () => {
      itemsAbortRef.current?.abort();
      const controller = new AbortController();
      itemsAbortRef.current = controller;
      setItemsLoading(true);
      try {
        const params = {
          conf: filters.conf,
          status: filters.status,
          sort: filters.sort,
          offset: filters.page * REVIEW_PAGE_SIZE,
          limit: REVIEW_PAGE_SIZE,
        };
        if (filters.classes.length > 0) params.classes = filters.classes.join(',');
        const data = await apiGet(`/reviews/${selectedJobId}/items`, {
          params,
          signal: controller.signal,
        });
        setItems({ ...data, job_id: selectedJobId });
      } catch (err) {
        if (axios.isCancel(err)) return;
        console.error('[useReview] Error fetching items:', err);
        setError(errorMessage(err, '讀取逐張結果失敗'));
      } finally {
        if (itemsAbortRef.current === controller) setItemsLoading(false);
      }
    }, QUERY_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [selectedJobId, filters]);

  // 燈箱與並排比較用：以檔名取單張，呼叫端自己管取消
  const fetchItem = useCallback(async (jobId, name, conf, signal) => {
    const data = await apiGet(`/reviews/${jobId}/item`, { params: { name, conf }, signal });
    return data.item;
  }, []);

  const submitReview = async (sessionId, datasetId, split, imgsz) => {
    if (!sessionId || !datasetId) return false;
    setIsSubmitting(true);
    setError(null);
    try {
      const { job } = await apiPost('/reviews', {
        session_id: sessionId,
        dataset_id: datasetId,
        split: split || null,
        imgsz: imgsz ? Number(imgsz) : null,
      });
      setJobs((prev) => [job, ...prev.filter((j) => j.job_id !== job.job_id)]);
      return true;
    } catch (err) {
      console.error('[useReview] Error submitting review:', err);
      setError(errorMessage(err, '送出逐張檢視失敗'));
      return false;
    } finally {
      setIsSubmitting(false);
    }
  };

  const deleteReview = async (jobId) => {
    try {
      await apiDelete(`/reviews/${jobId}`);
      await fetchJobs();
      return true;
    } catch (err) {
      console.error('[useReview] Error deleting review:', err);
      setError(errorMessage(err, '刪除逐張檢視失敗'));
      return false;
    }
  };

  return {
    reviewView: view,
    setReviewView: setView,
    reviewTargets: targets,
    reviewTargetsLoading: targetsLoading,
    fetchReviewTargets: fetchTargets,
    reviewJobs: jobs,
    reviewSelectedJobId: selectedJobId,
    selectReviewJob: selectJob,
    reviewCompareJobId: compareJobId,
    setReviewCompareJobId: setCompareJobId,
    reviewFilters: filters,
    updateReviewFilters: updateFilters,
    reviewItems: items,
    reviewItemsLoading: itemsLoading,
    reviewScrollRef: scrollRef,
    reviewError: error,
    setReviewError: setError,
    isSubmittingReview: isSubmitting,
    submitReview,
    deleteReview,
    fetchReviewItem: fetchItem,
  };
};
