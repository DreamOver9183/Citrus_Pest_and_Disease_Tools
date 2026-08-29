import { useState, useEffect, useCallback, useRef } from 'react';
import { apiGet, apiDelete, apiUpload, errorMessage } from '../../api/client';

// 資料集分析的「耐久」狀態，由 Provider 掛載一次。
//
// 分頁切換會 unmount 元件（App.jsx 用純 && 條件渲染，無 keep-alive），因此
// 進行中的 axios 請求也必須放在這裡：若放在分頁元件自己的 hook 裡，使用者按下
// 分析後切走，該 hook 會被卸載，promise resolve 到已卸載的元件，結果靜默遺失，
// React 18 連警告都不會給。這與 useLiveDemoState 存在的理由相同。
export const useDatasetState = () => {
  const [datasets, setDatasets] = useState({});
  const [activeDatasetId, setActiveDatasetId] = useState(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [analysisError, setAnalysisError] = useState(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [datasetsLoading, setDatasetsLoading] = useState(true);

  // 分析期間避免重入；同時後端也有 semaphore 擋第二個請求
  const inFlightRef = useRef(false);

  const fetchDatasets = useCallback(async () => {
    try {
      const data = await apiGet('/datasets');
      setDatasets(data.datasets || {});
    } catch (err) {
      console.error('[useDatasetState] Error fetching datasets on mount:', err);
    } finally {
      setDatasetsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchDatasets();
  }, [fetchDatasets]);

  const analyzeDataset = async (file) => {
    if (inFlightRef.current) return false;
    inFlightRef.current = true;
    setIsAnalyzing(true);
    setAnalysisError(null);
    setUploadProgress(0);

    const formData = new FormData();
    formData.append('file', file);

    try {
      // 刻意不設 timeout：大型資料集分析可能耗時數十秒，axios 預設的 0（不逾時）
      // 才是正確行為。
      const data = await apiUpload('/upload-dataset', formData, {
        onUploadProgress: (evt) => {
          if (evt.total) {
            setUploadProgress(Math.round((evt.loaded * 100) / evt.total));
          }
        },
      });
      setDatasets(data.datasets || {});
      setActiveDatasetId(data.dataset_id);
      return true;
    } catch (err) {
      console.error('[useDatasetState] Error analyzing dataset:', err);
      setAnalysisError(errorMessage(err, '分析失敗'));
    } finally {
      inFlightRef.current = false;
      setIsAnalyzing(false);
      setUploadProgress(0);
    }
    return false;
  };

  const deleteDataset = async (datasetId) => {
    try {
      const data = await apiDelete(`/datasets/${encodeURIComponent(datasetId)}`);
      setDatasets(data.datasets || {});
      setActiveDatasetId((current) => (current === datasetId ? null : current));
      return true;
    } catch (err) {
      console.error('[useDatasetState] Error deleting dataset:', err);
      setAnalysisError(errorMessage(err, '刪除失敗'));
      return false;
    }
  };

  const datasetCount = Object.keys(datasets).length;
  const activeDataset = activeDatasetId ? datasets[activeDatasetId] || null : null;

  return {
    datasets,
    // 供本機資料夾掃描把回應快照推進來（掃描回應同時帶 sessions 與 datasets，
    // 分屬不同 hook，由 ExperimentContext 在 Provider 層協調）
    setDatasets,
    datasetCount,
    datasetsLoading,
    activeDatasetId,
    setActiveDatasetId,
    activeDataset,
    isAnalyzing,
    analysisError,
    setAnalysisError,
    uploadProgress,
    analyzeDataset,
    deleteDataset,
  };
};
