import { useState } from 'react';

// LiveDemo 分頁的推論結果/已上傳檔案狀態。獨立於 Context 頂層，
// 目的是讓分頁切換時不遺失使用者正在檢視的測試結果。
export const useLiveDemoState = () => {
  const [liveDemoResults, setLiveDemoResults] = useState([]);
  const [liveDemoUploadedFiles, setLiveDemoUploadedFiles] = useState([]);

  return {
    liveDemoResults,
    setLiveDemoResults,
    liveDemoUploadedFiles,
    setLiveDemoUploadedFiles
  };
};
