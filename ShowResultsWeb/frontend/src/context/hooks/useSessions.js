import { useState, useEffect, useCallback } from 'react';
import { apiGet, apiPost, apiDelete, errorMessage } from '../../api/client';

// 管理已載入模型 Session 的清單、CRUD 與初次載入狀態。
export const useSessions = () => {
  const [sessions, setSessions] = useState({});
  const [loading, setLoading] = useState(true);
  const [sessionError, setSessionError] = useState(null);

  const fetchSessions = useCallback(async () => {
    try {
      const data = await apiGet('/sessions');
      setSessions(data.sessions || {});
      setSessionError(null);
    } catch (err) {
      console.error('[useSessions] Error fetching sessions on mount:', err);
      setSessionError(errorMessage(err, '無法取得模型清單'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSessions();
  }, [fetchSessions]);

  const addSession = (session_id, sessionData) => {
    setSessions(prev => ({
      ...prev,
      [session_id]: sessionData
    }));
  };

  const removeSessionState = (session_id) => {
    setSessions(prev => {
      const next = { ...prev };
      delete next[session_id];
      return next;
    });
  };

  // 修改名稱並通知後端
  const updateSessionName = async (session_id, newName) => {
    try {
      const data = await apiPost('/update-session-name', {
        session_id,
        custom_name: newName,
      });
      setSessions(data.sessions);
      return true;
    } catch (err) {
      console.error('[useSessions] Error updating name:', err);
      setSessionError(errorMessage(err, '更名失敗'));
      return false;
    }
  };

  // 刪除 Session 並通知後端清理檔案。回傳是否刪除後已無任何 session（供呼叫端重置分頁用）。
  // 注意：這只移除執行期的 session，**不會**動到權重登錄簿裡的長期紀錄。
  const deleteSession = async (session_id) => {
    try {
      const data = await apiDelete(`/sessions/${encodeURIComponent(session_id)}`);
      setSessions(data.sessions);
      return { success: true, isEmpty: Object.keys(data.sessions).length === 0 };
    } catch (err) {
      console.error('[useSessions] Error deleting session:', err);
      setSessionError(errorMessage(err, '刪除失敗'));
      return { success: false, isEmpty: false };
    }
  };

  const sessionCount = Object.keys(sessions).length;
  const isUnzipped = sessionCount > 0;

  return {
    sessions,
    setSessions,
    isUnzipped,
    sessionCount,
    loading,
    sessionError,
    setSessionError,
    fetchSessions,
    addSession,
    removeSessionState,
    updateSessionName,
    deleteSession
  };
};
