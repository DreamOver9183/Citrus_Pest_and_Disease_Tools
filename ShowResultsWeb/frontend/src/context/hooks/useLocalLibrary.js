import { useState, useEffect, useCallback, useRef } from 'react';
import { apiGet, apiPost, errorMessage } from '../../api/client';

// 本機資料夾掃描的「耐久」狀態，由 Provider 掛載一次。
//
// 與其他耐久 hook 同樣的理由：分頁切換會 unmount 元件（App.jsx 用純 && 條件渲染），
// 若進行中的請求與掃描結果放在分頁本地 hook，使用者按下掃描後切走就會全部遺失。
//
// 掃描與載入是兩個獨立動作：掃描只是列出找到什麼（後端不註冊任何東西），
// 使用者勾選後才呼叫 register。勾選狀態同樣要跨分頁存活，所以也放在這裡。
export const useLocalLibrary = () => {
  const [libraryPath, setLibraryPath] = useState('');
  const [libraryExists, setLibraryExists] = useState(true);
  const [pathLoading, setPathLoading] = useState(true);
  const [isScanning, setIsScanning] = useState(false);
  const [isRegistering, setIsRegistering] = useState(false);
  const [candidates, setCandidates] = useState([]);
  const [selectedIds, setSelectedIds] = useState([]);
  const [lastScanMessage, setLastScanMessage] = useState(null);
  const [lastRegisterMessage, setLastRegisterMessage] = useState(null);
  const [scanError, setScanError] = useState(null);

  // 避免重入；後端也有 semaphore 擋第二個請求
  const inFlightRef = useRef(false);

  const fetchLibraryInfo = useCallback(async () => {
    try {
      const data = await apiGet('/local-library');
      setLibraryPath(data.path || '');
      setLibraryExists(!!data.exists);
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
    setLastRegisterMessage(null);

    try {
      // 刻意不設 timeout：大型資料夾走訪與資料集分析可能耗時數十秒，axios 預設的
      // 0（不逾時）才是正確行為，與 useDatasetState 的分析請求一致。
      const data = await apiPost('/local-library/scan');
      const found = data.candidates || [];
      setCandidates(found);
      setLastScanMessage(data.message || null);
      // 預設勾選所有尚未載入的項目——使用者最常見的意圖是「全都要」，
      // 不想要的再取消勾選，比從零開始逐一勾選省事。
      setSelectedIds(found.filter((c) => !c.already_registered).map((c) => c.candidate_id));
      return { success: true };
    } catch (err) {
      console.error('[useLocalLibrary] Error scanning local library:', err);
      setScanError(errorMessage(err, '掃描失敗'));
    } finally {
      inFlightRef.current = false;
      setIsScanning(false);
    }
    return { success: false };
  };

  const toggleCandidate = (candidateId) => {
    setSelectedIds((prev) =>
      prev.includes(candidateId)
        ? prev.filter((id) => id !== candidateId)
        : [...prev, candidateId]
    );
  };

  const setSelectionForKind = (kind, checked) => {
    const idsOfKind = candidates
      .filter((c) => c.kind === kind && !c.already_registered)
      .map((c) => c.candidate_id);
    setSelectedIds((prev) =>
      checked
        ? Array.from(new Set([...prev, ...idsOfKind]))
        : prev.filter((id) => !idsOfKind.includes(id))
    );
  };

  const registerSelected = async () => {
    if (inFlightRef.current || selectedIds.length === 0) return { success: false };
    inFlightRef.current = true;
    setIsRegistering(true);
    setScanError(null);

    try {
      const data = await apiPost('/local-library/register', { candidate_ids: selectedIds });

      setLastRegisterMessage(data.message || null);
      // 後端只在註冊成功時才把項目標成已載入，因此重新標記本地清單，
      // 讓使用者立刻看到哪些已經進去了，不必再掃一次。
      const justRegistered = new Set(selectedIds);
      setCandidates((prev) =>
        prev.map((c) =>
          justRegistered.has(c.candidate_id) && !(data.failed || []).includes(c.name)
            ? { ...c, already_registered: true }
            : c
        )
      );
      setSelectedIds([]);
      return {
        success: true,
        sessions: data.sessions || {},
        datasets: data.datasets || {},
      };
    } catch (err) {
      console.error('[useLocalLibrary] Error registering selection:', err);
      setScanError(errorMessage(err, '載入失敗'));
    } finally {
      inFlightRef.current = false;
      setIsRegistering(false);
    }
    return { success: false };
  };

  return {
    libraryPath,
    libraryExists,
    pathLoading,
    isScanning,
    isRegistering,
    candidates,
    selectedIds,
    lastScanMessage,
    lastRegisterMessage,
    scanError,
    setScanError,
    scanLocalLibrary,
    toggleCandidate,
    setSelectionForKind,
    registerSelected,
  };
};
