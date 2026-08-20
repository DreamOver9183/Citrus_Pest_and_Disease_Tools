import React from 'react';
import { PieChart, Pie, Cell, Tooltip, Legend, ResponsiveContainer, Label } from 'recharts';
import { PieChart as PieIcon } from 'lucide-react';
import GlassTooltip from './GlassTooltip';
import { splitColor } from './chartTheme';
import { formatNumber } from './datasetFormat';

// 資料分割的影像佔比。甜甜圈中心放總數，等於順帶當一個 KPI。
//
// 關閉進場動畫（isAnimationActive={false}）：Pie 的動畫從角度 0 開始，完全依賴
// requestAnimationFrame。在分頁被瀏覽器背景化（document.visibilityState === 'hidden'）
// 時 rAF 會被節流到 0 fps，扇形永遠停在角度 0 而不產生任何 path，中心的總數卻照樣
// 顯示，看起來就像圖表壞掉。長條圖沒有這個問題（path 會先以初始幾何渲染出來）。
// 對數據看板而言即時渲染本來就比進場動畫重要，因此直接關閉。
const SplitCompositionChart = ({ stats }) => {
  const splits = stats.splits || [];
  const data = splits
    .filter((s) => s.images > 0)
    .map((s) => ({ name: s.name, value: s.images }));

  if (data.length === 0) return null;

  const total = data.reduce((sum, d) => sum + d.value, 0);

  return (
    <div className="glass-panel p-6 rounded-2xl border border-white/[0.06] space-y-6 shadow-2xl relative overflow-hidden">
      <div className="absolute top-[-20%] right-[-10%] w-[150px] h-[150px] rounded-full bg-indigo-500/5 blur-[50px] pointer-events-none"></div>

      <div className="flex items-center gap-2.5 border-b border-white/5 pb-4">
        <div className="p-2 bg-indigo-500/10 rounded-lg text-indigo-400">
          <PieIcon className="w-4 h-4" />
        </div>
        <div className="text-left">
          <h3 className="font-extrabold text-white text-sm font-sans tracking-tight">
            資料分割組成
          </h3>
          <p className="text-[10px] text-gray-400 font-mono mt-0.5">
            Train / Valid / Test Composition
          </p>
        </div>
      </div>

      <ResponsiveContainer width="100%" height={260}>
        <PieChart>
          <Pie
            data={data}
            dataKey="value"
            nameKey="name"
            innerRadius={58}
            outerRadius={92}
            paddingAngle={2}
            stroke="rgba(2,5,16,0.85)"
            strokeWidth={2}
            isAnimationActive={false}
          >
            {data.map((entry, index) => (
              <Cell key={entry.name} fill={splitColor(entry.name, index)} />
            ))}
            <Label
              position="center"
              content={({ viewBox }) => {
                const { cx, cy } = viewBox || {};
                return (
                  <g>
                    <text
                      x={cx}
                      y={cy - 6}
                      textAnchor="middle"
                      fill="#ffffff"
                      style={{ fontSize: 20, fontWeight: 800 }}
                    >
                      {formatNumber(total)}
                    </text>
                    <text
                      x={cx}
                      y={cy + 13}
                      textAnchor="middle"
                      fill="#64748b"
                      style={{ fontSize: 10 }}
                    >
                      images
                    </text>
                  </g>
                );
              }}
            />
          </Pie>
          <Tooltip content={<GlassTooltip valueSuffix=" 張" />} />
          <Legend wrapperStyle={{ fontSize: 10, color: '#64748b' }} />
        </PieChart>
      </ResponsiveContainer>

      <div className="grid grid-cols-3 gap-2 pt-1">
        {data.map((entry, index) => (
          <div key={entry.name} className="bg-slate-950/40 rounded-xl p-2.5 border border-white/5 text-center">
            <div className="flex items-center justify-center gap-1.5">
              <span
                className="w-2 h-2 rounded-full"
                style={{ backgroundColor: splitColor(entry.name, index) }}
              />
              <span className="text-[10px] text-gray-400 font-mono uppercase">{entry.name}</span>
            </div>
            <p className="text-sm font-extrabold text-white mt-1 font-sans">
              {((100 * entry.value) / total).toFixed(1)}%
            </p>
          </div>
        ))}
      </div>
    </div>
  );
};

export default SplitCompositionChart;
