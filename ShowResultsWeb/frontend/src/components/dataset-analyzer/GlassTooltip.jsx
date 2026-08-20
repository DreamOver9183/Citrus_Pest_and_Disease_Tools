import React from 'react';
import { formatNumber } from './datasetFormat';

// recharts 預設 tooltip 是白底淺框，在 #020510 深色背景上看起來像壞掉。
// 這個元件讓 tooltip 與 glass-panel 的視覺語彙一致。
const GlassTooltip = ({ active, payload, label, valueSuffix = '', labelFormatter }) => {
  if (!active || !payload || payload.length === 0) return null;

  const rows = payload.filter((p) => p.value !== null && p.value !== undefined);
  if (rows.length === 0) return null;

  return (
    <div className="bg-slate-950/95 border border-white/10 rounded-xl px-3 py-2.5 shadow-2xl backdrop-blur-md min-w-[140px]">
      <div className="text-[11px] font-bold text-white mb-1.5 font-sans break-words max-w-[220px]">
        {labelFormatter ? labelFormatter(label) : label}
      </div>
      <div className="space-y-1">
        {rows.map((row) => (
          <div key={row.dataKey ?? row.name} className="flex items-center justify-between gap-3">
            <span className="flex items-center gap-1.5 text-[10px] text-gray-400 font-sans">
              <span
                className="w-2 h-2 rounded-full flex-shrink-0"
                style={{ backgroundColor: row.color || row.fill }}
              />
              {row.name}
            </span>
            <span className="text-[11px] text-white font-mono font-bold">
              {formatNumber(row.value)}{valueSuffix}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
};

export default GlassTooltip;
