import React, { createContext, useState, useContext } from 'react';
import { useSessions } from './hooks/useSessions';
import { useDeviceControl } from './hooks/useDeviceControl';
import { useLiveDemoState } from './hooks/useLiveDemoState';
import { useDatasetState } from './hooks/useDatasetState';
import { useModelExport } from './hooks/useModelExport';
import { useLocalLibrary } from './hooks/useLocalLibrary';
import { useEvaluation } from './hooks/useEvaluation';
import { useRegistry } from './hooks/useRegistry';

const ExperimentContext = createContext();

// 這個 Provider 是八個獨立 hook（session / device / live-demo / dataset / export /
// local-library / evaluation / registry 狀態）的組合層，
// 目的是讓既有的 useExperiment() 呼叫點維持單一、扁平的 API，不必逐一遷移。
export const ExperimentProvider = ({ children }) => {
  // 'init', 'metrics', 'demo', 'dataset', 'evaluate', 'registry'
  const [activeTab, setActiveTab] = useState('init');

  const sessionsState = useSessions();
  const deviceState = useDeviceControl();
  const liveDemoState = useLiveDemoState();
  const datasetState = useDatasetState();
  const exportState = useModelExport();
  const localLibraryState = useLocalLibrary();
  const evaluationState = useEvaluation();
  const registryState = useRegistry();

  // 載入回應同時帶回 sessions 與 datasets 兩份快照，分屬不同 hook——
  // 與 deleteSession 同樣的理由，跨 hook 的協調邏輯放在 Provider 層。
  // （掃描本身不需要這層包裝：它不註冊任何東西，兩份快照都不會變動。）
  const registerLocalLibrarySelection = async () => {
    const result = await localLibraryState.registerSelected();
    if (result.success) {
      sessionsState.setSessions(result.sessions);
      datasetState.setDatasets(result.datasets);
    }
    return result.success;
  };

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
      ...localLibraryState,
      ...evaluationState,
      ...registryState,
      deleteSession,
      registerLocalLibrarySelection,
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
