import React, { useState } from 'react';
import { AlertTriangle, Database, RefreshCw, Search, Trophy } from 'lucide-react';
import { useExperiment } from '../context/ExperimentContext';
import WeightTable from './registry/WeightTable';
import WeightDetailPanel from './registry/WeightDetailPanel';
import MetricLedgerTable from './registry/MetricLedgerTable';
import { fmtMetric } from './registry/registryFormat';

/**
 * 權重登錄簿分頁。
 *
 * 與其他分頁最大的差別：這裡的資料**不依賴任何 session 還活著**。使用者可以刪掉所有
 * 已載入的模型、重啟整個系統，「這顆權重的超參數是什麼、在哪個資料集上實測到多少」
 * 仍然查得到。這正是加資料庫要解決的那個缺口——session_id 每次掃描都會變，
 * LocalLibrary 來源的 session 依設計不落地。
 */
export default function Registry() {
  const {
    registryStats,
    registryAvailable,
    registryWeights,
    registryWeightsTotal,
    registryLedger,
    registrySelectedSha,
    registryWeightDetail,
    registryLoading,
    registryError,
    registryQuery,
    setRegistryQuery,
    registryWeightSort,
    registryLedgerSort,
    toggleRegistryWeightSort,
    toggleRegistryLedgerSort,
    refreshRegistry,
    selectRegistryWeight,
    deleteRegistryWeight,
  } = useExperiment();

  const [view, setView] = useState('weights');

  if (!registryAvailable) {
    return (
      <div className="mx-auto max-w-3xl px-2 py-16 text-center">
        <AlertTriangle className="mx-auto mb-4 h-10 w-10 text-amber-400" />
        <h2 className="text-xl font-semibold text-slate-100">權重登錄簿目前離線</h2>
        <p className="mt-3 text-slate-400">
          資料庫無法連線（後端回報 {registryStats?.backend || '未知'} 引擎）。
          這<strong className="text-slate-200">不影響</strong>模型載入、推論、資料集分析與
          驗證評估——登錄簿是附加的長期帳本，其餘功能都以檔案系統為準，照常運作。
        </p>
        <p className="mt-2 text-sm text-slate-500">
          Docker 部署時請確認 <code>db</code> 服務已啟動；本機開發預設使用 SQLite 檔案，
          通常不需要任何設定。
        </p>
        <button
          type="button"
          onClick={refreshRegistry}
          className="mt-6 inline-flex items-center gap-2 rounded-lg border border-slate-600 px-4 py-2 text-sm text-slate-200 transition-colors hover:bg-slate-800"
        >
          <RefreshCw className="h-4 w-4" />
          重新檢查
        </button>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-7xl space-y-6 px-2 py-4 text-left animate-fadeIn">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="flex items-center gap-2 text-2xl font-semibold text-slate-100">
            <Database className="h-6 w-6 text-emerald-400" />
            權重登錄簿
          </h2>
          <p className="mt-1 max-w-3xl text-sm text-slate-400">
            以權重檔內容的 SHA-256 為身分的長期帳本，記錄每顆權重的訓練超參數與歷次實測指標。
            與已載入的 Session 生命週期脫鉤——刪除模型或重啟系統都不會影響這裡的紀錄。
          </p>
        </div>
        <button
          type="button"
          onClick={refreshRegistry}
          disabled={registryLoading}
          className="inline-flex items-center gap-2 rounded-lg border border-slate-600 px-3 py-1.5 text-sm text-slate-200 transition-colors hover:bg-slate-800 disabled:opacity-50"
        >
          <RefreshCw className={`h-4 w-4 ${registryLoading ? 'animate-spin' : ''}`} />
          重新整理
        </button>
      </header>

      {registryError && (
        <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
          {registryError}
        </div>
      )}

      {/* --- 總覽磚 --- */}
      {registryStats && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatTile label="已記錄權重" value={registryStats.total_weights} />
          <StatTile label="訓練紀錄" value={registryStats.total_training_runs} />
          <StatTile label="實測次數" value={registryStats.total_evaluations} />
          <StatTile
            label="資料庫引擎"
            value={registryStats.backend}
            hint={`${registryStats.datasets_evaluated.length} 個資料集被評估過`}
          />
        </div>
      )}

      {registryStats?.best?.length > 0 && (
        <section className="rounded-xl border border-slate-700/60 bg-slate-900/40 p-4">
          <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-300">
            <Trophy className="h-4 w-4 text-amber-400" />
            各指標的最佳紀錄
          </h3>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {registryStats.best.map((entry) => (
              <div
                key={entry.metric}
                className="rounded-lg border border-slate-700/50 bg-slate-900/50 px-3 py-2"
              >
                <div className="text-xs text-slate-500">{entry.metric}</div>
                <div className="mt-0.5 font-mono text-lg text-emerald-300">
                  {fmtMetric(entry.value)}
                </div>
                <div className="mt-0.5 truncate text-xs text-slate-400" title={entry.weight_name}>
                  {entry.weight_name} · {entry.dataset_name} / {entry.split}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* --- 檢視切換 --- */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="inline-flex rounded-lg border border-slate-700 p-0.5">
          <button
            type="button"
            onClick={() => setView('weights')}
            className={`rounded-md px-3 py-1.5 text-sm transition-colors ${
              view === 'weights' ? 'bg-emerald-500/20 text-emerald-300' : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            權重清單（{registryWeightsTotal}）
          </button>
          <button
            type="button"
            onClick={() => setView('ledger')}
            className={`rounded-md px-3 py-1.5 text-sm transition-colors ${
              view === 'ledger' ? 'bg-emerald-500/20 text-emerald-300' : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            指標帳本（{registryLedger.length}）
          </button>
        </div>

        {view === 'weights' && (
          <div className="relative flex-1 sm:max-w-xs">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
            <input
              type="text"
              value={registryQuery}
              onChange={(e) => setRegistryQuery(e.target.value)}
              placeholder="搜尋權重名稱或檔名"
              className="w-full rounded-lg border border-slate-700 bg-slate-900/60 py-1.5 pl-9 pr-3 text-sm text-slate-200 placeholder-slate-500 focus:border-emerald-500/50 focus:outline-none"
            />
          </div>
        )}
      </div>

      {view === 'weights' ? (
        <div className="space-y-5">
          <WeightTable
            weights={registryWeights}
            sort={registryWeightSort}
            onSort={toggleRegistryWeightSort}
            selectedSha={registrySelectedSha}
            onSelect={selectRegistryWeight}
            onDelete={deleteRegistryWeight}
          />
          {registrySelectedSha && <WeightDetailPanel detail={registryWeightDetail} />}
        </div>
      ) : (
        <div className="space-y-3">
          <MetricLedgerTable
            rows={registryLedger}
            sort={registryLedgerSort}
            onSort={toggleRegistryLedgerSort}
          />
          <p className="text-xs text-slate-500">
            並列比較只有在<strong className="text-slate-300">資料集與 split 相同</strong>時
            才有方法學上的意義。Micro-Accuracy 是 TP/(TP+FP+FN)，於固定的 conf/IoU 門檻下統計，
            與對所有門檻積分的 mAP 不是同一類指標。
          </p>
        </div>
      )}
    </div>
  );
}

function StatTile({ label, value, hint }) {
  return (
    <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 px-4 py-3">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-slate-100">{value}</div>
      {hint && <div className="mt-0.5 text-xs text-slate-500">{hint}</div>}
    </div>
  );
}
