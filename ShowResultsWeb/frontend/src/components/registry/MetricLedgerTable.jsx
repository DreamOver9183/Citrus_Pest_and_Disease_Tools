import React from 'react';
import { METRIC_COLUMNS, fmtDateTime, fmtInt, fmtMetric, sortArrow } from './registryFormat';

/**
 * 跨權重的指標帳本。
 *
 * 這張表是整個登錄簿的目的：把不同權重在**同一個資料集與 split** 上的實測值並排，
 * 才是方法學上有效的消融比較。因此資料集與 split 兩欄永遠顯示，不可省略——
 * 沒有它們，並列的數字就只是好看而已。
 */
export default function MetricLedgerTable({ rows, sort, onSort }) {
  if (rows.length === 0) {
    return (
      <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 p-8 text-center text-slate-500">
        還沒有任何實測紀錄。到「驗證評估」分頁跑一次評估，結果會自動記進這裡。
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-slate-700/60 bg-slate-900/40">
      <table className="w-full min-w-[1000px] text-sm">
        <thead>
          <tr className="border-b border-slate-700/60 text-slate-400">
            <th className="px-4 py-3 text-left font-medium">權重</th>
            <th className="px-4 py-3 text-left font-medium">資料集 / split</th>
            <th
              className="cursor-pointer select-none px-4 py-3 text-right font-medium hover:text-slate-200"
              onClick={() => onSort('image_count')}
            >
              影像數{sortArrow(sort, 'image_count')}
            </th>
            {METRIC_COLUMNS.map((col) => (
              <th
                key={col.key}
                title={col.hint}
                className="cursor-pointer select-none px-4 py-3 text-right font-medium hover:text-slate-200"
                onClick={() => onSort(col.key)}
              >
                {col.label}
                {sortArrow(sort, col.key)}
              </th>
            ))}
            <th
              className="cursor-pointer select-none px-4 py-3 text-right font-medium hover:text-slate-200"
              onClick={() => onSort('finished_at')}
            >
              完成時間{sortArrow(sort, 'finished_at')}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.job_id} className="border-b border-slate-800/60 hover:bg-slate-800/40">
              <td className="px-4 py-3 text-slate-200">{row.weight_name || '—'}</td>
              <td className="px-4 py-3 text-slate-300">
                {row.dataset_name}
                <span className="ml-1 text-xs text-slate-500">/ {row.split}</span>
              </td>
              <td className="px-4 py-3 text-right text-slate-300">{fmtInt(row.image_count)}</td>
              {METRIC_COLUMNS.map((col) => (
                <td key={col.key} className="px-4 py-3 text-right font-mono text-slate-200">
                  {fmtMetric(row[col.key])}
                </td>
              ))}
              <td className="px-4 py-3 text-right text-xs text-slate-400">
                {fmtDateTime(row.finished_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
