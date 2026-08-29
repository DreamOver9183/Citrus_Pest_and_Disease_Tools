import React, { useState, useEffect } from 'react';
import { apiGet } from '../api/client';
import { useExperiment } from '../context/ExperimentContext';
import { Lock, ArrowUp, Zap } from 'lucide-react';
import Lightbox from './Lightbox';
import { METRICS_OPTIONS } from './metric-dashboard/metricsOptions';
import IndicatorSidebar, { SidebarExpandButton } from './metric-dashboard/IndicatorSidebar';
import ChartGrid from './metric-dashboard/ChartGrid';

const MetricDashboard = () => {
  const { isUnzipped, sessions } = useExperiment();
  const sessionIds = Object.keys(sessions);
  const sessionCount = sessionIds.length;

  // 被勾選的指標
  const [selectedMetrics, setSelectedMetrics] = useState(METRICS_OPTIONS.map(opt => opt.key));
  const [showConfusionMatrix, setShowConfusionMatrix] = useState(true);

  // 圖片及載入狀態
  const [metricUrls, setMetricUrls] = useState({}); // { [metric_key]: { [session_id]: { url, sourcePath } } }
  const [loadingMetrics, setLoadingMetrics] = useState({}); // { [metric_key]: boolean }
  const [matrixUrls, setMatrixUrls] = useState({}); // { [session_id]: { url, sourcePath } }
  const [loadingMatrix, setLoadingMatrix] = useState(false);
  const [activeLightboxUrl, setActiveLightboxUrl] = useState(null);
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);

  // 1. 取得指標已裁剪之檔案
  const fetchMetricForModels = async (metricKey) => {
    if (sessionCount === 0) return;
    setLoadingMetrics(prev => ({ ...prev, [metricKey]: true }));

    const urls = {};
    try {
      await Promise.all(sessionIds.map(async (id) => {
        const model = sessions[id];
        const isYolo = model.model_arch === 'yolo' || !model.model_arch;
        const isSsdMetric = metricKey.startsWith('ssd_');

        try {
          let data;
          if (isYolo && !isSsdMetric) {
            data = await apiGet(`/metrics?session_id=${id}&metric_type=${metricKey}`);
          } else if (!isYolo && isSsdMetric) {
            data = await apiGet(`/generate-chart?session_id=${id}&chart_type=${metricKey}`);
          } else {
            urls[id] = null;
            return;
          }
          urls[id] = { url: data.url, sourcePath: data.source_path };
        } catch (e) {
          // 該模型沒有這張圖是常態（例如未產出 results.png），不是錯誤
          urls[id] = null;
        }
      }));

      setMetricUrls(prev => ({ ...prev, [metricKey]: urls }));
    } catch (err) {
      console.error(`Error fetching metrics for ${metricKey}:`, err);
    } finally {
      setLoadingMetrics(prev => ({ ...prev, [metricKey]: false }));
    }
  };

  // 2. 取得混淆矩陣
  const fetchConfusionMatrix = async () => {
    if (sessionCount === 0) return;
    setLoadingMatrix(true);
    const urls = {};

    try {
      await Promise.all(sessionIds.map(async (id) => {
        try {
          const data = await apiGet(`/metrics?session_id=${id}&metric_type=confusion_matrix`);
          urls[id] = { url: data.url, sourcePath: data.source_path };
        } catch (e) {
          urls[id] = null;
        }
      }));
      setMatrixUrls(urls);
    } catch (err) {
      console.error("Error fetching confusion matrices:", err);
    } finally {
      setLoadingMatrix(false);
    }
  };

  // 監聽勾選狀態與 Session 數量變動，動態載入指標
  useEffect(() => {
    if (!isUnzipped || sessionCount === 0) return;
    selectedMetrics.forEach(key => {
      fetchMetricForModels(key);
    });
  }, [selectedMetrics, isUnzipped, sessionCount]);

  // 監聽混淆矩陣顯示
  useEffect(() => {
    if (isUnzipped && showConfusionMatrix && sessionCount > 0) {
      fetchConfusionMatrix();
    }
  }, [showConfusionMatrix, isUnzipped, sessionCount]);

  const handleCheckboxChange = (key) => {
    if (selectedMetrics.includes(key)) {
      setSelectedMetrics(prev => prev.filter(m => m !== key));
    } else {
      setSelectedMetrics(prev => [...prev, key]);
    }
  };

  const handleToggleAll = () => {
    if (selectedMetrics.length === METRICS_OPTIONS.length) {
      setSelectedMetrics([]);
    } else {
      setSelectedMetrics(METRICS_OPTIONS.map(opt => opt.key));
    }
  };

  // 動態網格與寬度自適應類別名計算
  const getGridLayoutClass = () => {
    if (sessionCount === 1) {
      return "grid grid-cols-1 max-w-3xl mx-auto gap-6";
    } else if (sessionCount === 2) {
      return "grid grid-cols-1 md:grid-cols-2 gap-6";
    } else {
      return "grid grid-cols-1 md:grid-cols-3 gap-6";
    }
  };

  // 全域守衛 (Visual Guard) - 無模型時的 Skeleton
  if (!isUnzipped || sessionCount === 0) {
    return (
      <div className="px-2 py-4 max-w-7xl mx-auto text-left">
        <div className="glass-panel rounded-3xl p-16 text-center border border-white/[0.06] shadow-2xl relative overflow-hidden">
          <div className="absolute inset-0 bg-gradient-to-r from-orange-500/10 to-indigo-500/10 blur-3xl opacity-35 pointer-events-none"></div>
          <Lock className="w-12 h-12 mx-auto mb-4 text-orange-500/60 animate-pulse" />
          <h2 className="text-base font-extrabold text-white mb-2 flex items-center justify-center gap-2 font-sans">
            消融看板未解鎖
            <div className="relative group inline-block">
              <button className="cursor-help w-4 h-4 rounded-full bg-white/10 hover:bg-orange-500 hover:text-white text-[10px] text-gray-400 font-bold transition-all flex items-center justify-center border border-white/10" aria-label="解鎖說明">
                ?
              </button>
              <div className="absolute left-1/2 -translate-x-1/2 top-full mt-2 w-72 p-3 bg-slate-950/95 border border-white/10 rounded-xl text-xs text-gray-300 shadow-2xl opacity-0 group-hover:opacity-100 pointer-events-none transition-all duration-300 z-50 leading-relaxed font-sans font-normal backdrop-blur-md text-left">
                載入 YOLO (.pt/.zip) 後系統自動解析訓練圖表；載入 SSDLite (.pth) 後系統依 training_metrics.csv 自動繪製訓練曲線。
              </div>
            </div>
          </h2>
          <p className="text-xs text-gray-500">請載入含有訓練成果紀錄的 YOLO 壓縮包以同步指標。</p>
        </div>
      </div>
    );
  }

  // 檢查是否所有模型都是無指標的單一權重
  const allNoMetrics = sessionIds.every(id => {
    const s = sessions[id];
    return s?.source_type === 'single_weight' || (!s?.results_png && !s?.confusion_matrix);
  });

  // 判斷單一模型是否有指標
  const hasMetrics = (id) => {
    const s = sessions[id];
    if (s?.model_arch !== 'yolo') {
      return !!s?.metrics_csv_path;
    }
    return s?.source_type !== 'single_weight' && (s?.results_png || s?.confusion_matrix);
  };

  return (
    <div className="px-2 py-4 max-w-7xl mx-auto space-y-6 animate-fadeIn text-left relative">

      {/* 全部為無指標模型時的引導畫面 */}
      {allNoMetrics && (
        <div className="glass-panel rounded-2xl p-6 text-center border border-white/[0.06] shadow-xl relative overflow-hidden flex items-center justify-center gap-3">
          <div className="absolute inset-0 bg-gradient-to-r from-orange-500/5 to-indigo-500/5 blur-2xl opacity-35 pointer-events-none"></div>
          <Zap className="w-5 h-5 text-orange-400 animate-pulse flex-shrink-0" />
          <span className="text-xs text-gray-300 font-sans">
            偵測到純權重檔案模型 (無指標數據)
          </span>
          <div className="relative group inline-block">
            <button className="cursor-help w-4 h-4 rounded-full bg-white/10 hover:bg-orange-500 hover:text-white text-[10px] text-gray-400 font-bold transition-all flex items-center justify-center border border-white/10" aria-label="說明">
              ?
            </button>
            <div className="absolute left-1/2 -translate-x-1/2 top-full mt-2 w-72 p-3.5 bg-slate-950/95 border border-white/10 rounded-xl text-xs text-gray-300 shadow-2xl opacity-0 group-hover:opacity-100 pointer-events-none transition-all duration-300 z-50 leading-relaxed font-sans font-normal text-left backdrop-blur-md">
              <p className="font-bold text-orange-400 mb-1">純權重模型說明</p>
              您載入的模型均為純權重檔案，不含訓練過程指標檔案。請直接切換至「即時診斷」頁面測試影像辨識，或上傳含 YOLO `runs/detect/train` 資料夾的壓縮 ZIP 包以同步學術消融看板。
            </div>
          </div>
        </div>
      )}

      {!isSidebarOpen && <SidebarExpandButton onExpand={() => setIsSidebarOpen(true)} />}

      {/* 雙網格版面：側邊設定欄 (Sticky) + 圖表並排主區 */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-8 items-start">

        {isSidebarOpen && (
          <IndicatorSidebar
            selectedMetrics={selectedMetrics}
            onToggleMetric={handleCheckboxChange}
            onToggleAll={handleToggleAll}
            showConfusionMatrix={showConfusionMatrix}
            onToggleConfusionMatrix={() => setShowConfusionMatrix(!showConfusionMatrix)}
            onCollapse={() => setIsSidebarOpen(false)}
          />
        )}

        {/* 右側：指標主圖區 */}
        <div className={`${isSidebarOpen ? 'lg:col-span-3' : 'lg:col-span-4'} space-y-8 transition-all duration-300`}>
          <ChartGrid
            sessionIds={sessionIds}
            sessions={sessions}
            selectedMetrics={selectedMetrics}
            showConfusionMatrix={showConfusionMatrix}
            matrixUrls={matrixUrls}
            loadingMatrix={loadingMatrix}
            metricUrls={metricUrls}
            loadingMetrics={loadingMetrics}
            hasMetrics={hasMetrics}
            gridLayoutClass={getGridLayoutClass()}
            onZoom={setActiveLightboxUrl}
          />
        </div>
      </div>

      {/* 底部回到上方按鈕 */}
      <div className="flex justify-center pt-8 pb-4">
        <button
          onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
          className="px-6 py-3.5 bg-slate-950/60 hover:bg-orange-500 hover:text-white text-gray-400 border border-white/5 hover:border-orange-500/20 text-xs font-bold rounded-2xl transition-all shadow-xl flex items-center gap-2 cursor-pointer font-sans"
          title="回到頁面最上方"
        >
          <ArrowUp className="w-4 h-4" /> 回到最上方
        </button>
      </div>

      {/* Lightbox 彈窗 */}
      {activeLightboxUrl && (
        <Lightbox
          src={activeLightboxUrl}
          onClose={() => setActiveLightboxUrl(null)}
        />
      )}
    </div>
  );
};

export default MetricDashboard;
