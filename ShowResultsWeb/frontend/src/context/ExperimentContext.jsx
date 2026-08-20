import React, { createContext, useState, useContext } from 'react';
import { useSessions } from './hooks/useSessions';
import { useDeviceControl } from './hooks/useDeviceControl';
import { useLiveDemoState } from './hooks/useLiveDemoState';
import { useDatasetState } from './hooks/useDatasetState';
import { useModelExport } from './hooks/useModelExport';

const ExperimentContext = createContext();

// 這個 Provider 是五個獨立 hook（session / device / live-demo / dataset / export 狀態）的組合層，
// 目的是讓既有的 useExperiment() 呼叫點維持單一、扁平的 API，不必逐一遷移。
export const ExperimentProvider = ({ children }) => {
  const [activeTab, setActiveTab] = useState('init'); // 'init', 'metrics', 'demo', 'dataset'

  const sessionsState = useSessions();
  const deviceState = useDeviceControl();
  const liveDemoState = useLiveDemoState();
  const datasetState = useDatasetState();
  const exportState = useModelExport();

  // 刪除 Session 後，若已無任何 Session 則重置回初始分頁
  const deleteSession = async (session_id) => {
    const { success, isEmpty } = await sessionsState.deleteSession(session_id);
    if (success && isEmpty) {
      setActiveTab('init');
    }
    return success;
  };

  return (
    <ExperimentContext.Provider value={{
      ...sessionsState,
      ...deviceState,
      ...liveDemoState,
      ...datasetState,
      ...exportState,
      deleteSession,
      activeTab,
      setActiveTab
    }}>
      {children}
    </ExperimentContext.Provider>
  );
};

export const useExperiment = () => {
  const context = useContext(ExperimentContext);
  if (!context) {
    throw new Error('useExperiment must be used within an ExperimentProvider');
  }
  return context;
};
