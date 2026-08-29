import { useState, useEffect, useCallback, useRef } from 'react';
import { apiGet, apiPost, apiDelete, errorMessage } from '../../api/client';

// 模型匯出的「耐久」狀態，由 Provider 掛載一次。
//
// 輪詢迴圈與 job 狀態都必須放在這裡，不能放進分頁元件自己的 hook：
// App.jsx 用裸 && 條件渲染、沒有 keep-alive，切分頁就會 unmount。而使用者在
// 一個要跑數十秒到數分鐘的匯出期間切去別的分頁看東西，正是最可能發生的行為。
//
// 輪詢用自排程 setTimeout 鏈而不是 setInterval：
//   - setInterval 在後端忙碌時會堆疊請求，鏈式結構天然不會重疊
//   - 背景分頁的計時器會被節流，鏈式只是變慢，setInterval 的 tick 則會被丟棄
//   - 清理只要一個 clearTimeout

const POLL_FAST_MS = 1000;
const POLL_MID_MS = 2000;
const POLL_SLOW_MS = 5000;
const FAST_WINDOW_MS = 15000;
const MID_WINDOW_MS = 60000;

export const useModelExport = () => {
  const [exportCapabilities, setExportCapabilities] = useState(null);
  const [capabilitiesLoading, setCapabilitiesLoading] = useState(true);
  const [exportJobs, setExportJobs] = useState({});
  const [exportError, setExportError] = useState(null);

  const timerRef = useRef(null);
  const cancelledRef = useRef(false);
  const pollStartRef = useRef(0);
  const inFlightRef = useRef(new Set());

  const fetchCapabilities = useCallback(async () => {
    try {
      setExportCapabilities(await apiGet('/export/capabilities'));
    } catch (err) {
      console.error('[useModelExport] Error fetching capabilities:', err);
    } finally {
      setCapabilitiesLoading(false);
    }
  }, []);

  // 掛載時抓一次全部 job：伺服器會從 manifest 還原已完成的匯出，
  // 因此重新整理頁面不會弄丟已經轉好的檔案。
  const fetchAllJobs = useCallback(async () => {
    try {
      const data = await apiGet('/export/jobs');
      setExportJobs(data.jobs || {});
    } catch (err) {
      console.error('[useModelExport] Error fetching export jobs:', err);
    }
  }, []);

  useEffect(() => {
    fetchCapabilities();
    fetchAllJobs();
  }, [fetchCapabilities, fetchAllJobs]);

  const hasActiveJob = Object.values(exportJobs).some(
    (job) => job.state === 'queued' || job.state === 'running'
  );

  // 輪詢迴圈
  useEffect(() => {
    if (!hasActiveJob) {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
      return undefined;
    }

    cancelledRef.current = false;
    if (!pollStartRef.current) pollStartRef.current = Date.now();

    const nextDelay = () => {
      const elapsed = Date.now() - pollStartRef.current;
      if (elapsed < FAST_WINDOW_MS) return POLL_FAST_MS;
      if (elapsed < MID_WINDOW_MS) return POLL_MID_MS;
      return POLL_SLOW_MS;
    };

    const tick = async () => {
      try {
        const polled = await apiGet('/export/jobs?active=1');
        if (cancelledRef.current) return;
        {
          const active = polled.jobs || {};
          // 伺服器是唯一真相來源：先合併進行中的，再對「不在 active 清單裡」的
          // 舊 job 補抓一次終態。絕不從計時器推導完成與否 —— 計時器被凍結只會
          // 延遲更新，不會讓狀態出錯。
          setExportJobs((prev) => {
            const merged = { ...prev, ...active };
            Object.keys(prev).forEach((jobId) => {
              const wasActive = prev[jobId].state === 'queued' || prev[jobId].state === 'running';
              if (wasActive && !active[jobId]) {
                // 剛結束，稍後由 refreshJob 補上終態
                inFlightRef.current.add(jobId);
              }
            });
            return merged;
          });

          const finished = [...inFlightRef.current];
          inFlightRef.current.clear();
          await Promise.all(
            finished.map(async (jobId) => {
              try {
                const one = await apiGet(`/export/${jobId}`);
                if (!cancelledRef.current && one.job) {
                  setExportJobs((prev) => ({ ...prev, [jobId]: one.job }));
                }
              } catch {
                // job 可能已被刪除，忽略
              }
            })
          );
        }
      } catch (err) {
        if (!cancelledRef.current) {
          console.error('[useModelExport] Poll error:', err);
        }
      }
      if (!cancelledRef.current) {
        timerRef.current = setTimeout(tick, nextDelay());
      }
    };

    timerRef.current = setTimeout(tick, nextDelay());

    // 背景分頁的計時器會被瀏覽器嚴重節流（Chrome 可壓到每分鐘一次）。
    // 使用者切回來時立刻補一次並把退避重置，否則可能盯著過期的「轉換中」很久。
    const onVisible = () => {
      if (document.visibilityState === 'visible' && !cancelledRef.current) {
        pollStartRef.current = Date.now();
        if (timerRef.current) clearTimeout(timerRef.current);
        timerRef.current = setTimeout(tick, 0);
      }
    };
    document.addEventListener('visibilitychange', onVisible);

    return () => {
      cancelledRef.current = true;
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [hasActiveJob]);

  useEffect(() => {
    if (!hasActiveJob) pollStartRef.current = 0;
  }, [hasActiveJob]);

  const startExport = async (sessionId, format) => {
    setExportError(null);
    try {
      const { job } = await apiPost('/export', { session_id: sessionId, format });
      setExportJobs((prev) => ({ ...prev, [job.job_id]: job }));
      return true;
    } catch (err) {
      console.error('[useModelExport] Error starting export:', err);
      setExportError(errorMessage(err, '匯出失敗'));
      return false;
    }
  };

  const deleteExportJob = async (jobId) => {
    try {
      await apiDelete(`/export/${jobId}`);
      setExportJobs((prev) => {
        const next = { ...prev };
        delete next[jobId];
        return next;
      });
      return true;
    } catch (err) {
      console.error('[useModelExport] Error deleting export job:', err);
    }
    return false;
  };

  // session_id -> 該 session 最新的 job
  const latestJobBySession = {};
  Object.values(exportJobs).forEach((job) => {
    const current = latestJobBySession[job.session_id];
    if (!current || String(job.created_at || '') > String(current.created_at || '')) {
      latestJobBySession[job.session_id] = job;
    }
  });

  return {
    exportCapabilities,
    capabilitiesLoading,
    exportJobs,
    latestJobBySession,
    exportError,
    setExportError,
    startExport,
    deleteExportJob,
  };
};
