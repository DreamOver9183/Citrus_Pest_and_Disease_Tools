import { useState, useCallback } from 'react';
import { useDropzone } from 'react-dropzone';
import { useExperiment } from '../../context/ExperimentContext';

// 資料集分頁的「暫態」UI 狀態。
//
// 這裡只放丟失也無妨的東西（排序、展開、切換）。真正需要跨分頁存活的資料
// 與進行中的請求都在 context/hooks/useDatasetState.js —— 分頁切換會 unmount
// 本元件，放在這裡的狀態會一併消失。
export const useDatasetAnalysis = () => {
  const {
    datasets,
    datasetCount,
    activeDatasetId,
    setActiveDatasetId,
    activeDataset,
    isAnalyzing,
    analysisError,
    setAnalysisError,
    uploadProgress,
    analyzeDataset,
    deleteDataset,
  } = useExperiment();

  const [localError, setLocalError] = useState(null);
  const [showSplitBreakdown, setShowSplitBreakdown] = useState(false);
  const [classSort, setClassSort] = useState({ key: 'count', dir: 'desc' });
  const [definitionExpanded, setDefinitionExpanded] = useState(false);
  const [issuesExpanded, setIssuesExpanded] = useState(true);

  const onDrop = useCallback((acceptedFiles) => {
    setLocalError(null);
    setAnalysisError(null);
    const file = acceptedFiles?.[0];
    if (!file) return;

    // 與 SystemSpecs 一致：不用 dropzone 的 accept（瀏覽器對 .zip 的 MIME
    // 判定不一致），改為手動驗副檔名。
    if (!file.name.toLowerCase().endsWith('.zip')) {
      setLocalError(`不支援的檔案格式：${file.name}。資料集分析僅接受 .zip 壓縮檔。`);
      return;
    }
    analyzeDataset(file);
  }, [analyzeDataset, setAnalysisError]);

  const dropzone = useDropzone({
    onDrop,
    multiple: false,
    disabled: isAnalyzing,
  });

  const toggleClassSort = (key) => {
    setClassSort((prev) =>
      prev.key === key
        ? { key, dir: prev.dir === 'desc' ? 'asc' : 'desc' }
        : { key, dir: key === 'name' || key === 'id' ? 'asc' : 'desc' }
    );
  };

  return {
    datasets,
    datasetCount,
    activeDatasetId,
    setActiveDatasetId,
    activeDataset,
    isAnalyzing,
    uploadProgress,
    deleteDataset,
    error: localError || analysisError,
    dropzone,
    showSplitBreakdown,
    setShowSplitBreakdown,
    classSort,
    toggleClassSort,
    definitionExpanded,
    setDefinitionExpanded,
    issuesExpanded,
    setIssuesExpanded,
  };
};
