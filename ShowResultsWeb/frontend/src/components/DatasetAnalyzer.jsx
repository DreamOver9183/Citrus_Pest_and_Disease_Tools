import React from 'react';
import { FolderTree } from 'lucide-react';
import { useDatasetAnalysis } from './dataset-analyzer/useDatasetAnalysis';
import DatasetUploadPanel from './dataset-analyzer/DatasetUploadPanel';
import DatasetOverviewHeader from './dataset-analyzer/DatasetOverviewHeader';
import DatasetSummaryCards from './dataset-analyzer/DatasetSummaryCards';
import ClassDistributionChart from './dataset-analyzer/ClassDistributionChart';
import SplitCompositionChart from './dataset-analyzer/SplitCompositionChart';
import SplitDensityChart from './dataset-analyzer/SplitDensityChart';
import ClassStatsTable from './dataset-analyzer/ClassStatsTable';
import ValidationIssueList from './dataset-analyzer/ValidationIssueList';
import DefinitionViewer from './dataset-analyzer/DefinitionViewer';

const DatasetAnalyzer = () => {
  const {
    datasets,
    activeDatasetId,
    setActiveDatasetId,
    activeDataset,
    isAnalyzing,
    uploadProgress,
    deleteDataset,
    error,
    dropzone,
    showSplitBreakdown,
    setShowSplitBreakdown,
    classSort,
    toggleClassSort,
    definitionExpanded,
    setDefinitionExpanded,
    issuesExpanded,
    setIssuesExpanded,
  } = useDatasetAnalysis();

  // 有紀錄但尚未選取時，預設顯示最新的一筆
  const records = Object.values(datasets || {});
  const stats =
    activeDataset ||
    (records.length > 0
      ? [...records].sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')))[0]
      : null);

  return (
    <div className="max-w-7xl mx-auto px-2 py-4 space-y-8 animate-fadeIn text-left">
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-8 items-start">
        <DatasetUploadPanel
          dropzone={dropzone}
          isAnalyzing={isAnalyzing}
          uploadProgress={uploadProgress}
          error={error}
          datasets={datasets}
          activeDatasetId={stats?.dataset_id || activeDatasetId}
          onSelect={setActiveDatasetId}
          onDelete={deleteDataset}
        />

        <div className="lg:col-span-3 space-y-6">
          {!stats ? (
            <div className="glass-panel rounded-3xl p-16 text-center border border-white/[0.06] shadow-2xl relative overflow-hidden">
              <div className="absolute inset-0 bg-gradient-to-r from-rose-500/10 to-indigo-500/10 blur-3xl opacity-35 pointer-events-none"></div>
              <FolderTree className="w-12 h-12 mx-auto mb-4 text-rose-500/60 animate-pulse" />
              <h2 className="text-base font-extrabold text-white mb-2 flex items-center justify-center gap-2 font-sans">
                資料集分析
                <div className="relative group inline-block">
                  <button
                    className="cursor-help w-4 h-4 rounded-full bg-white/10 hover:bg-rose-500 hover:text-white text-[10px] text-gray-400 font-bold transition-all flex items-center justify-center border border-white/10"
                    aria-label="說明"
                  >
                    ?
                  </button>
                  <div className="absolute left-1/2 -translate-x-1/2 top-full mt-2 w-72 p-3 bg-slate-950/95 border border-white/10 rounded-xl text-xs text-gray-300 shadow-2xl opacity-0 group-hover:opacity-100 pointer-events-none transition-all duration-300 z-50 leading-relaxed font-sans font-normal backdrop-blur-md text-left">
                    上傳資料集壓縮檔後，系統會自動辨識格式並統計影像數、標註數、類別分佈，
                    同時檢查標註與宣告是否一致。
                  </div>
                </div>
              </h2>
              <p className="text-xs text-gray-500">請自左側拖入資料集 ZIP 壓縮檔以開始分析。</p>
            </div>
          ) : (
            <>
              <DatasetOverviewHeader stats={stats} />
              <DatasetSummaryCards stats={stats} />

              <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
                <SplitCompositionChart stats={stats} />
                <SplitDensityChart stats={stats} />
              </div>

              <ClassDistributionChart
                stats={stats}
                showSplitBreakdown={showSplitBreakdown}
                onToggleBreakdown={() => setShowSplitBreakdown((v) => !v)}
              />

              <ClassStatsTable stats={stats} sort={classSort} onSort={toggleClassSort} />

              <ValidationIssueList
                issues={stats.issues}
                expanded={issuesExpanded}
                onToggle={() => setIssuesExpanded((v) => !v)}
              />

              <DefinitionViewer
                definition={stats.definition}
                expanded={definitionExpanded}
                onToggle={() => setDefinitionExpanded((v) => !v)}
              />
            </>
          )}
        </div>
      </div>
    </div>
  );
};

export default DatasetAnalyzer;
