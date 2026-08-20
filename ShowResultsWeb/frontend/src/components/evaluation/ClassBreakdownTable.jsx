import React, { useMemo, useState } from 'react';
import { ArrowUpDown } from 'lucide-react';
import { WEAK_AP_THRESHOLD, formatMetric, formatPct } from './evalTheme';

const COLUMNS = [
  { key: 'name', label: '類別', align: 'left' },
  { key: 'ap50', label: 'AP@50' },
  { key: 'ap50_95', label: 'AP@50-95' },
  { key: 'precision', label: 'Precision' },
  { key: 'recall', label: 'Recall' },
  { key: 'boxes', label: '標註框數' },
  { key: 'median_area_pct', label: '中位框面積' },
  { key: 'tiny_pct', label: '極小框佔比' },
];

// 逐類別表現。預設依 AP@50 由低至高排序——使用者最想先看到的是「哪些類別表現差」，
// 而不是從最好的開始往下捲。
const ClassBreakdownTable = ({ perClass, sizeProfile }) => {
  const [sortKey, setSortKey] = useState('ap50');
  const [asc, setAsc] = useState(true);

  const rows = useMemo(() => {
    const sizeById = new Map((sizeProfile || []).map((s) => [s.class_id, s]));
    const merged = (perClass || []).map((entry) => {
      const size = sizeById.get(entry.class_id) || {};
      return {
        ...entry,
        boxes: size.boxes ?? null,
        median_area_pct: size.median_area_pct ?? null,
        tiny_pct: size.tiny_pct ?? null,
      };
    });

    return merged.sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (typeof av === 'string') return asc ? av.localeCompare(bv) : bv.localeCompare(av);
      // null 一律排到最後，不論升降序——「沒有資料」不該被解讀成「值很小」
      if (av === null || av === undefined) return 1;
      if (bv === null || bv === undefined) return -1;
      return asc ? av - bv : bv - av;
    });
  }, [perClass, sizeProfile, sortKey, asc]);

  const toggle = (key) => {
    if (key === sortKey) setAsc(!asc);
    else {
      setSortKey(key);
      setAsc(key === 'name');
    }
  };

  if (rows.length === 0) return null;

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[11px]">
        <thead>
          <tr className="text-gray-500 uppercase tracking-wider text-[9px]">
            {COLUMNS.map((col) => (
              <th
                key={col.key}
                onClick={() => toggle(col.key)}
                className={`py-2 px-2 font-bold cursor-pointer hover:text-gray-300 transition-colors select-none whitespace-nowrap ${
                  col.align === 'left' ? 'text-left' : 'text-right'
                }`}
              >
                <span className="inline-flex items-center gap-1">
                  {col.label}
                  {sortKey === col.key && <ArrowUpDown className="w-2.5 h-2.5" />}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const weak = row.ap50 < WEAK_AP_THRESHOLD;
            return (
              <tr
                key={row.class_id}
                className={`border-t border-white/5 ${weak ? 'bg-red-500/[0.05]' : ''}`}
              >
                <td className="py-2 px-2 text-left font-bold text-white whitespace-nowrap">
                  {weak && <span className="text-red-400 mr-1" title="AP@50 偏低">▲</span>}
                  {row.name}
                </td>
                <td className={`py-2 px-2 text-right font-mono font-bold ${weak ? 'text-red-400' : 'text-emerald-300'}`}>
                  {formatMetric(row.ap50)}
                </td>
                <td className="py-2 px-2 text-right font-mono text-gray-300">{formatMetric(row.ap50_95)}</td>
                <td className="py-2 px-2 text-right font-mono text-gray-400">{formatMetric(row.precision)}</td>
                <td className="py-2 px-2 text-right font-mono text-gray-400">{formatMetric(row.recall)}</td>
                <td className="py-2 px-2 text-right font-mono text-gray-400">
                  {row.boxes === null ? '—' : row.boxes.toLocaleString()}
                </td>
                <td className="py-2 px-2 text-right font-mono text-gray-400">
                  {formatPct(row.median_area_pct)}
                </td>
                <td className="py-2 px-2 text-right font-mono text-gray-400">
                  {row.tiny_pct === null || row.tiny_pct === undefined
                    ? '—'
                    : `${row.tiny_pct.toFixed(1)}%`}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="text-[9px] text-gray-600 mt-2 leading-relaxed">
        ▲ 代表 AP@50 低於 {WEAK_AP_THRESHOLD}。「極小框」指面積小於整張影像 0.1% 的標註。
        標註框數少的類別，其 AP 的統計不確定性較高。
      </p>
    </div>
  );
};

export default ClassBreakdownTable;
