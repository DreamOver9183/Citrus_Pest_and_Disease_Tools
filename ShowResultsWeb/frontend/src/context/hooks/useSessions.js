import { useState, useEffect, useCallback } from 'react';
import axios from 'axios';

// 管理已載入模型 Session 的清單、CRUD 與初次載入狀態。
export const useSessions = () => {
  const [sessions, setSessions] = useState({});
  const [loading, setLoading] = useState(true);

  const fetchSessions = useCallback(async () => {
    try {
      const res = await axios.get('/api/sessions');
      if (res.data.status === 'success') {
        setSessions(res.data.sessions || {});
      }
    } catch (err) {
      console.error('[useSessions] Error fetching sessions on mount:', err);
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
      const formData = new FormData();
      formData.append('session_id', session_id);
      formData.append('custom_name', newName);

      const res = await axios.post('/api/update-session-name', formData);
      if (res.data.status === 'success') {
        setSessions(res.data.sessions);
        return true;
      }
    } catch (err) {
      console.error('[useSessions] Error updating name:', err);
    }
    return false;
  };

  // 刪除 Session 並通知後端清理檔案。回傳是否刪除後已無任何 session（供呼叫端重置分頁用）。
  const deleteSession = async (session_id) => {
    try {
      const formData = new FormData();
      formData.append('session_id', session_id);

      const res = await axios.post('/api/delete-session', formData);
      if (res.data.status === 'success') {
        setSessions(res.data.sessions);
        return { success: true, isEmpty: Object.keys(res.data.sessions).length === 0 };
      }
    } catch (err) {
      console.error('[useSessions] Error deleting session:', err);
    }
    return { success: false, isEmpty: false };
  };

  const sessionCount = Object.keys(sessions).length;
  const isUnzipped = sessionCount > 0;

  return {
    sessions,
    setSessions,
    isUnzipped,
    sessionCount,
    loading,
    addSession,
    removeSessionState,
    updateSessionName,
    deleteSession
  };
};
