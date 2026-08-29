import React from 'react';
import { Database, Trash2 } from 'lucide-react';
import {
  archStyle,
  fmtDateTime,
  fmtMetric,
  fmtSize,
  shortSha,
  sortArrow,
  sourceLabel,
  sourceStyle,
} from './registryFormat';

const COLUMNS = [
  { key: 'display_name', label: '權重', sortable: true, align: 'text-left' },
  { key: 'epochs', label: 'Epochs', sortable: true, align: 'text-right' },
  { key: 'size_mb', label: '大小', sortable: true, align: 'text-right' },
  { key: 'best_map50', label: '最佳 mAP@50', sortable: true, align: 'text-right' },
  { key: 'best_micro_accuracy', label: '最佳 Micro-Acc', sortable: true, align: 'text-right' },
  { key: 'evaluation_count', label: '評估次數', sortable: true, align: 'text-right' },
  { key: 'last_seen_at', label: '最後出現', sortable: true, align: 'text-right' },
];

/** 權重清單。點一列展開明細，欄位標題可排序。 */
export default function WeightTable({ weights, sort, onSort, selectedSha, onSelect, onDelete }) {
  if (weights.length === 0) {
    return (
      <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 p-10 text-center">
        <Database className="mx-auto mb-3 h-8 w-8 text-slate-600" />
        <p className="text-slate-400">登錄簿裡還沒有任何權重。</p>
        <p className="mt-1 text-sm text-slate-500">
          從「模型與裝置」分頁上傳或載入模型後，會自動記錄在這裡。
        </p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-slate-700/60 bg-slate-900/40">
      <table className="w-full min-w-[900px] text-sm">
        <thead>
          <tr className="border-b border-slate-700/60 text-slate-400">
            {COLUMNS.map((col) => (
              <th
                key={col.key}
                className={`px-4 py-3 font-medium ${col.align} ${
                  col.sortable ? 'cursor-pointer select-none hover:text-slate-200' : ''
                }`}
                onClick={col.sortable ? () => onSort(col.key) : undefined}
              >
                {col.label}
                {col.sortable ? sortArrow(sort, col.key) : ''}
              </th>
            ))}
            <th className="px-4 py-3 text-right font-medium">操作</th>
          </tr>
        </thead>
        <tbody>
          {weights.map((w) => {
            const isSelected = w.sha256 === selectedSha;
            return (
              <tr
                key={w.sha256}
                onClick={() => onSelect(w.sha256)}
                className={`cursor-pointer border-b border-slate-800/60 transition-colors ${
                  isSelected ? 'bg-emerald-500/10' : 'hover:bg-slate-800/40'
                }`}
              >
                <td className="px-4 py-3">
                  <div className="font-medium text-slate-100">{w.display_name || w.filename}</div>
                  <div className="mt-1 flex flex-wrap items-center gap-2">
                    <span className={`rounded border px-1.5 py-0.5 text-xs ${archStyle(w.model_arch)}`}>
                      {w.model_arch || '未知架構'}
                    </span>
                    <span className={`rounded border px-1.5 py-0.5 text-xs ${sourceStyle(w.source_type)}`}>
                      {sourceLabel(w.source_type)}
                    </span>
                    <code className="text-xs text-slate-500" title={w.sha256}>
                      {shortSha(w.sha256)}
                    </code>
                  </div>
                </td>
                <td className="px-4 py-3 text-right text-slate-300">
                  {w.training_run?.epochs ?? '—'}
                </td>
                <td className="px-4 py-3 text-right text-slate-300">{fmtSize(w.size_mb)}</td>
                <td className="px-4 py-3 text-right font-mono text-slate-200">
                  {fmtMetric(w.best_map50)}
                </td>
                <td className="px-4 py-3 text-right font-mono text-slate-200">
                  {fmtMetric(w.best_micro_accuracy)}
                </td>
                <td className="px-4 py-3 text-right text-slate-300">{w.evaluation_count}</td>
                <td className="px-4 py-3 text-right text-xs text-slate-400">
                  {fmtDateTime(w.last_seen_at)}
                </td>
                <td className="px-4 py-3 text-right">
                  <button
                    type="button"
                    title="從登錄簿移除（不會刪除磁碟上的權重檔）"
                    onClick={(e) => {
                      e.stopPropagation();
                      onDelete(w.sha256);
                    }}
                    className="rounded p-1.5 text-slate-500 transition-colors hover:bg-rose-500/10 hover:text-rose-400"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
