import { useState, useCallback, useEffect, useRef } from 'react';
import { useDropzone } from 'react-dropzone';
import { apiUpload, errorMessage, axios } from '../../api/client';
import { useExperiment } from '../../context/ExperimentContext';
import { traverseFileTree } from './traverseFileTree';

// 封裝 LiveDemo 的推論資料流：session/裝置狀態、上傳/重抽樣/信心閾值調整、
// AbortController 取消邏輯。元件端只需消費回傳的狀態與 handler。
export const useLiveDemoInference = () => {
  const { isUnzipped, sessions, deviceLoading, currentDeviceLabel, liveDemoResults, setLiveDemoResults, liveDemoUploadedFiles, setLiveDemoUploadedFiles } = useExperiment();
  const sessionIds = Object.keys(sessions);

  const [selectedSessionId, setSelectedSessionId] = useState('');
  const [confThreshold, setConfThreshold] = useState(0.25);
  const [sampleSize, setSampleSize] = useState('4');
  const [activeLightboxUrl, setActiveLightboxUrl] = useState(null);

  // 圖片預測狀態 (已提升至 Context，切換分頁不會遺失)
  const results = liveDemoResults;
  const setResults = setLiveDemoResults;
  const uploadedFiles = liveDemoUploadedFiles;
  const setUploadedFiles = setLiveDemoUploadedFiles;

  // AbortController 用於取消舊的推論請求 (防止資料錯位)
  const abortControllerRef = useRef(null);

  // 監聽 sessions 變更，同步預設選取之 Session ID
  useEffect(() => {
    if (sessionIds.length > 0) {
      if (!selectedSessionId || !sessions[selectedSessionId]) {
        setSelectedSessionId(sessionIds[0]);
      }
    } else {
      setSelectedSessionId('');
    }
  }, [sessions, selectedSessionId, sessionIds]);

  const runSingleInference = async (index, sessionId, file, confVal, signal) => {
    try {
      // session_id 與 conf 改成 multipart 表單欄位（原本在 query string）：
      // 這個端點本來就必須是 multipart，把參數留在 query 等於同一個請求有兩套
      // 參數傳遞方式。統一之後的規則是「POST 的參數都在 body 裡」，沒有例外。
      const formData = new FormData();
      formData.append('file', file);
      formData.append('session_id', sessionId);
      formData.append('conf', confVal);
      const data = await apiUpload('/inference', formData, { signal });

      setResults(prev => prev.map((item, idx) => idx === index ? {
        ...item,
        loading: false,
        resultUrl: data.url,
        originalUrl: data.original_url || item.originalUrl,
        counts: data.counts,
        detections: data.detections,
        deviceUsed: data.device_used
      } : item));
    } catch (err) {
      if (axios.isCancel(err)) return; // 被 AbortController 取消的請求，靜默忽略
      setResults(prev => prev.map((item, idx) => idx === index ? {
        ...item,
        loading: false,
        error: errorMessage(err, '推論失敗')
      } : item));
    }
  };

  const buildResultItems = (files) => files.map(file => ({
    id: Math.random().toString(36).substr(2, 9),
    filename: file.name,
    fileObject: file, // 儲存原始 File 物件以供動態調整信心閾值重新推論
    originalUrl: URL.createObjectURL(file),
    resultUrl: null,
    counts: 0,
    detections: {},
    loading: true,
    error: null,
    showOriginal: false // 預設顯示標註圖片模式（不顯示原始圖片對照）
  }));

  const sampleFiles = (files) => {
    if (sampleSize === 'all') return [...files];
    const count = parseInt(sampleSize, 10);
    return [...files].sort(() => 0.5 - Math.random()).slice(0, count);
  };

  const dispatchInference = (filesToProcess, newItems, signal) => {
    newItems.forEach((item, idx) => {
      const file = filesToProcess[idx];
      runSingleInference(idx, selectedSessionId, file, confThreshold, signal);
    });
  };

  // 處理拖放檔案上傳並進行隨機抽樣 (支援多圖/資料夾過濾僅載入圖片)
  const onDrop = useCallback((acceptedFiles) => {
    if (!isUnzipped || !selectedSessionId || deviceLoading) return;

    const imageFiles = acceptedFiles.filter(file => file.type.startsWith('image/'));
    if (imageFiles.length === 0) return;

    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    abortControllerRef.current = new AbortController();

    setUploadedFiles(imageFiles);

    const filesToProcess = sampleFiles(imageFiles);
    const newItems = buildResultItems(filesToProcess);

    // 每次拖入時清空之前的結果，以避免 DOM 積壓卡頓
    setResults(newItems);

    dispatchInference(filesToProcess, newItems, abortControllerRef.current.signal);
  }, [selectedSessionId, isUnzipped, sampleSize, confThreshold]);

  // 重新抽取圖片 (利用已儲存的原始上傳檔案)
  const handleResample = () => {
    if (uploadedFiles.length === 0 || !selectedSessionId || deviceLoading) return;

    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    abortControllerRef.current = new AbortController();

    const filesToProcess = sampleFiles(uploadedFiles);
    const newItems = buildResultItems(filesToProcess);

    setResults(newItems);

    dispatchInference(filesToProcess, newItems, abortControllerRef.current.signal);
  };

  const dropzone = useDropzone({
    onDrop,
    accept: { 'image/*': [] },
    disabled: !isUnzipped || !selectedSessionId || deviceLoading,
    getFilesFromEvent: async (event) => {
      if (event.type === 'drop') {
        const files = [];
        const items = event.dataTransfer ? event.dataTransfer.items : null;
        if (items) {
          const promises = [];
          for (let i = 0; i < items.length; i++) {
            const item = items[i];
            const entry = item.webkitGetAsEntry ? item.webkitGetAsEntry() : null;
            if (entry) {
              promises.push(traverseFileTree(entry));
            } else {
              const file = item.getAsFile();
              if (file) files.push(file);
            }
          }
          const collected = await Promise.all(promises);
          return files.concat(collected.flat());
        }
      }
      return Array.from(event.target.files || []);
    }
  });

  const clearResults = () => {
    setResults([]);
    setUploadedFiles([]);
  };

  // 切換對照原始圖片的開關
  const toggleOriginal = (index) => {
    setResults(prev => prev.map((item, idx) => idx === index ? {
      ...item,
      showOriginal: !item.showOriginal
    } : item));
  };

  // 動態調整信心閾值重新推論
  const reRunInferenceWithNewConf = (newConf) => {
    if (results.length === 0 || !selectedSessionId) return;

    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    abortControllerRef.current = new AbortController();
    const signal = abortControllerRef.current.signal;

    setResults(prev => prev.map(item => ({
      ...item,
      loading: true,
      resultUrl: null,
      error: null
    })));

    results.forEach((item, idx) => {
      if (item.fileObject) {
        runSingleInference(idx, selectedSessionId, item.fileObject, newConf, signal);
      }
    });
  };

  return {
    isUnzipped,
    sessions,
    sessionIds,
    currentDeviceLabel,
    selectedSessionId,
    setSelectedSessionId,
    confThreshold,
    setConfThreshold,
    sampleSize,
    setSampleSize,
    results,
    uploadedFiles,
    activeLightboxUrl,
    setActiveLightboxUrl,
    dropzone,
    handleResample,
    clearResults,
    toggleOriginal,
    reRunInferenceWithNewConf
  };
};
