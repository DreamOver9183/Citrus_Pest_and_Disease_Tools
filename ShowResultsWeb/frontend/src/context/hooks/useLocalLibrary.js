import { useState, useEffect, useCallback, useRef } from 'react';
import axios from 'axios';

// 本機資料夾掃描的「耐久」狀態，由 Provider 掛載一次。
//
// 與其他耐久 hook 同樣的理由：分頁切換會 unmount 元件（App.jsx 用純 && 條件渲染），
// 若進行中的請求與掃描摘要放在分頁本地 hook，使用者按下掃描後切走就會全部遺失。
export const useLocalLibrary = () => {
  const [libraryPath, setLibraryPath] = useState('');
  const [libraryExists, setLibraryExists] = useState(true);
  const [pathLoading, setPathLoading] = useState(true);
  const [isScanning, setIsScanning] = useState(false);
  const [lastScanSummary, setLastScanSummary] = useState(null);
  const [scanError, setScanError] = useState(null);

  // 避免重入；後端也有 semaphore 擋第二個請求
  const inFlightRef = useRef(false);

  const fetchLibraryInfo = useCallback(async () => {
    try {
      const res = await axios.get('/api/local-library');
      if (res.data.status === 'success') {
        setLibraryPath(res.data.path || '');
        setLibraryExists(!!res.data.exists);
      }
    } catch (err) {
      console.error('[useLocalLibrary] Error fetching library info:', err);
    } finally {
      setPathLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchLibraryInfo();
  }, [fetchLibraryInfo]);

  const scanLocalLibrary = async () => {
    if (inFlightRef.current) return { success: false };
    inFlightRef.current = true;
    setIsScanning(true);
    setScanError(null);

    try {
      // 刻意不設 timeout：大型資料夾走訪可能耗時數十秒，axios 預設的 0（不逾時）
      // 才是正確行為，與 useDatasetState 的分析請求一致。
      const res = await axios.post('/api/local-library/scan');

      if (res.data.status === 'success') {
        setLastScanSummary({
          message: res.data.message,
          registeredSessions: (res.data.registered_sessions || []).length,
          registeredDatasets: (res.data.registered_datasets || []).length,
          skipped: (res.data.skipped_sessions || 0) + (res.data.skipped_datasets || 0),
          at: new Date().toISOString(),
        });
        return {
          success: true,
          sessions: res.data.sessions || {},
          datasets: res.data.datasets || {},
        };
      }
      setScanError(res.data.message || '掃描失敗');
    } catch (err) {
      console.error('[useLocalLibrary] Error scanning local library:', err);
      setScanError(
        err.response?.data?.detail || err.message || '連線後端 API 失敗，請確認 FastAPI 服務是否運行'
      );
    } finally {
      inFlightRef.current = false;
      setIsScanning(false);
    }
    return { success: false };
  };

  return {
    libraryPath,
    libraryExists,
    pathLoading,
    isScanning,
    lastScanSummary,
    scanError,
    setScanError,
    scanLocalLibrary,
  };
};
