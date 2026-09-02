import React from 'react';
import { Layers, RefreshCw, BarChart2, TrendingUp } from 'lucide-react';
import { METRICS_OPTIONS } from './metricsOptions';
import ModelMetricCard from './ModelMetricCard';

// 右側指標主圖區：混淆矩陣對比 + 各指標曲線對比
const ChartGrid = ({
  sessionIds,
  sessions,
  selectedMetrics,
  showConfusionMatrix,
  matrixUrls,
  loadingMatrix,
  metricUrls,
  loadingMetrics,
  hasMetrics,
  gridLayoutClass,
  onZoom
}) => {
  return (
    <>
      {selectedMetrics.length === 0 && !showConfusionMatrix && (
        <div className="glass-panel p-16 text-center rounded-2xl border border-white/[0.06] shadow-xl flex flex-col items-center justify-center gap-3">
          <BarChart2 className="w-12 h-12 text-gray-600 animate-pulse" />
          <p className="text-gray-400 text-xs">請在左側選單中勾選所需指標，系統將即時對齊繪製消融圖表</p>
        </div>
      )}

      {/* 混淆矩陣對比區 */}
      {showConfusionMatrix && (
        <div className="glass-panel p-6 rounded-2xl border border-white/[0.06] space-y-6 shadow-2xl relative overflow-hidden">
          <div className="absolute top-[-20%] right-[-10%] w-[150px] h-[150px] rounded-full bg-indigo-500/5 blur-[50px] pointer-events-none"></div>

          <div className="flex items-center justify-between border-b border-white/5 pb-4">
            <div className="flex items-center gap-2.5">
              <div className="p-2 bg-indigo-500/10 rounded-lg text-indigo-400">
                <Layers className="w-4 h-4" />
              </div>
              <div className="text-left">
                <h3 className="font-extrabold text-white text-sm font-sans tracking-tight">學術混淆矩陣消融分析 (Confusion Matrix)</h3>
              </div>
            </div>
            {loadingMatrix && <RefreshCw className="w-4 h-4 text-indigo-400 animate-spin" />}
          </div>

          {loadingMatrix ? (
            <div className={gridLayoutClass}>
              {sessionIds.map(id => (
                <div key={id} className="bg-slate-950/40 rounded-xl h-64 border border-white/5 animate-pulse"></div>
              ))}
            </div>
          ) : (
            <div className={gridLayoutClass}>
              {sessionIds.map(id => {
                const model = sessions[id];
                const imgUrlObj = matrixUrls[id];
                return (
                  <ModelMetricCard
                    key={id}
                    model={model}
                    imgUrl={imgUrlObj?.url}
                    sourcePath={imgUrlObj?.sourcePath}
                    metricHasData={hasMetrics(id)}
                    imgAlt={`${model.custom_name} Confusion Matrix`}
                    onZoom={onZoom}
                    accent="indigo"
                    emptyHeightClass="h-52"
                    emptyDescription="Single weight file format skips training phase validation matrices."
                  />
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* 指標曲線動態對比區 */}
      {selectedMetrics.map(metricKey => {
        const opt = METRICS_OPTIONS.find(o => o.key === metricKey);
        const urls = metricUrls[metricKey] || {};
        const loading = loadingMetrics[metricKey];

        return (
          <div
            key={metricKey}
            className="glass-panel p-6 rounded-2xl border border-white/[0.06] space-y-6 shadow-2xl relative overflow-hidden"
          >
            <div className="absolute top-[-20%] right-[-10%] w-[150px] h-[150px] rounded-full bg-orange-500/5 blur-[50px] pointer-events-none"></div>

            <div className="flex items-center justify-between border-b border-white/5 pb-4">
              <div className="flex items-center gap-2.5">
                <div className="p-2 bg-orange-500/10 rounded-lg text-orange-400">
                  <TrendingUp className="w-4 h-4" />
                </div>
                <div className="text-left">
                  <h4 className="font-extrabold text-white text-sm font-sans tracking-tight">{opt ? opt.name : metricKey}</h4>
                  <p className="text-[10px] text-gray-400 font-sans mt-0.5">{opt ? opt.desc : ''}</p>
                </div>
              </div>
              {loading && <RefreshCw className="w-4 h-4 text-orange-400 animate-spin" />}
            </div>

            {loading ? (
              <div className={gridLayoutClass}>
                {sessionIds.map(id => (
                  <div key={id} className="bg-slate-950/40 rounded-xl h-48 border border-white/5 animate-pulse"></div>
                ))}
              </div>
            ) : (
              <div className={gridLayoutClass}>
                {sessionIds.map(id => {
                  const model = sessions[id];
                  const imgUrlObj = urls[id];
                  return (
                    <ModelMetricCard
                      key={id}
                      model={model}
                      imgUrl={imgUrlObj?.url}
                      sourcePath={imgUrlObj?.sourcePath}
                      metricHasData={hasMetrics(id)}
                      imgAlt={`${model.custom_name} ${metricKey}`}
                      onZoom={onZoom}
                      accent="orange"
                      emptyHeightClass="h-32"
                    />
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </>
  );
};

export default ChartGrid;
