import React from 'react';
import { ArrowUpDown, Table2 } from 'lucide-react';
import { seriesColor } from './chartTheme';
import { formatNumber, formatPct, sortClasses } from './datasetFormat';

// 類別明細表。圖表看趨勢，表格看確切數字，兩者互補。
const ClassStatsTable = ({ stats, sort, onSort }) => {
  const classes = stats.classes || [];
  if (classes.length === 0) return null;

  const splitNames = (stats.splits || []).map((s) => s.name);
  // 顏色必須對應原始索引，排序後才不會與長條圖對不上
  const colorByName = new Map(classes.map((c, i) => [c.name, seriesColor(i)]));
  const rows = sortClasses(classes, sort.key, sort.dir);

  const header = (key, label, align = 'left') => (
    <th
      onClick={() => onSort(key)}
      className={`px-3 py-2 text-[10px] font-mono uppercase tracking-wider text-gray-500 cursor-pointer hover:text-white transition-colors select-none text-${align}`}
    >
      <span className={`inline-flex items-center gap-1 ${align === 'right' ? 'flex-row-reverse' : ''}`}>
        {label}
        <ArrowUpDown className={`w-3 h-3 ${sort.key === key ? 'text-rose-400' : 'text-gray-700'}`} />
      </span>
    </th>
  );

  return (
    <div className="glass-panel p-6 rounded-2xl border border-white/[0.06] space-y-4 shadow-2xl">
      <div className="flex items-center gap-2.5 border-b border-white/5 pb-4">
        <div className="p-2 bg-white/5 rounded-lg text-gray-300">
          <Table2 className="w-4 h-4" />
        </div>
        <div className="text-left">
          <h3 className="font-extrabold text-white text-sm font-sans tracking-tight">類別明細</h3>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[520px]">
          <thead>
            <tr className="border-b border-white/5">
              {header('id', 'ID')}
              {header('name', '類別名稱')}
              {splitNames.map((split) => (
                <th
                  key={split}
                  className="px-3 py-2 text-[10px] font-mono uppercase tracking-wider text-gray-500 text-right"
                >
                  {split}
                </th>
              ))}
              {header('count', '總計', 'right')}
              <th className="px-3 py-2 text-[10px] font-mono uppercase tracking-wider text-gray-500 text-right">
                佔比
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((cls) => (
              <tr
                key={`${cls.id}-${cls.name}`}
                className="border-b border-white/[0.03] hover:bg-white/[0.02] transition-colors"
              >
                <td className="px-3 py-2.5 text-[11px] text-gray-500 font-mono">{cls.id}</td>
                <td className="px-3 py-2.5">
                  <span className="flex items-center gap-2">
                    <span
                      className="w-2.5 h-2.5 rounded-sm flex-shrink-0"
                      style={{ backgroundColor: colorByName.get(cls.name) }}
                    />
                    <span className="text-[11px] text-white font-sans font-semibold break-all">
                      {cls.name}
                    </span>
                  </span>
                </td>
                {splitNames.map((split) => (
                  <td key={split} className="px-3 py-2.5 text-[11px] text-gray-400 font-mono text-right">
                    {formatNumber(cls.per_split?.[split] ?? 0)}
                  </td>
                ))}
                <td className="px-3 py-2.5 text-[11px] text-white font-mono font-bold text-right">
                  {formatNumber(cls.count)}
                </td>
                <td className="px-3 py-2.5 text-[11px] font-mono text-right">
                  <span className={cls.count === 0 ? 'text-sky-400' : 'text-gray-400'}>
                    {formatPct(cls.pct)}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default ClassStatsTable;
