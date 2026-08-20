import React from 'react';
import {
  BarChart, Bar, Cell, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ReferenceLine, ResponsiveContainer,
} from 'recharts';
import { BarChart3, Layers } from 'lucide-react';
import GlassTooltip from './GlassTooltip';
import { seriesColor, splitColor, AXIS, GRID_STROKE, CURSOR_FILL, REFERENCE_STROKE } from './chartTheme';
import { meanCount, imbalanceRatio, formatNumber } from './datasetFormat';

// 每類別標註數。
// 用水平長條（layout="vertical"）：類別名稱動輒是 Citrus_Leaf_Miner 這種長字串，
// 放在垂直 X 軸上會被截斷或旋轉到無法閱讀。
const ClassDistributionChart = ({ stats, showSplitBreakdown, onToggleBreakdown }) => {
  const classes = stats.classes || [];
  const splitNames = (stats.splits || []).map((s) => s.name);

  if (classes.length === 0) {
    return (
      <div className="glass-panel p-16 text-center rounded-2xl border border-white/[0.06] shadow-xl flex flex-col items-center justify-center gap-3">
        <BarChart3 className="w-12 h-12 text-gray-600 animate-pulse" />
        <p className="text-gray-400 text-xs">此資料集沒有可統計的類別</p>
      </div>
    );
  }

  const data = classes.map((c) => ({
    name: c.name,
    total: c.count,
    ...(c.per_split || {}),
  }));

  const mean = meanCount(classes);
  const ratio = imbalanceRatio(classes);
  const chartHeight = Math.max(240, classes.length * 34 + 60);

  return (
    <div className="glass-panel p-6 rounded-2xl border border-white/[0.06] space-y-6 shadow-2xl relative overflow-hidden">
      <div className="absolute top-[-20%] right-[-10%] w-[150px] h-[150px] rounded-full bg-rose-500/5 blur-[50px] pointer-events-none"></div>

      <div className="flex items-center justify-between border-b border-white/5 pb-4 gap-3 flex-wrap">
        <div className="flex items-center gap-2.5">
          <div className="p-2 bg-rose-500/10 rounded-lg text-rose-400">
            <BarChart3 className="w-4 h-4" />
          </div>
          <div className="text-left">
            <h3 className="font-extrabold text-white text-sm font-sans tracking-tight">
              類別標註分佈
            </h3>
            <p className="text-[10px] text-gray-400 font-mono mt-0.5">
              Per-Class Annotation Distribution
              {ratio ? ` · imbalance ${ratio.toFixed(1)}:1` : ''}
            </p>
          </div>
        </div>

        {splitNames.length > 1 && (
          <button
            onClick={onToggleBreakdown}
            className={`text-[9px] px-2.5 py-1.5 border rounded-md transition-all cursor-pointer font-bold font-sans flex items-center gap-1.5 ${
              showSplitBreakdown
                ? 'bg-rose-500/15 border-rose-500/40 text-rose-300'
                : 'bg-white/5 border-white/10 text-gray-400 hover:bg-rose-500 hover:text-white'
            }`}
            title="切換各資料分割的堆疊顯示"
          >
            <Layers className="w-3 h-3" />
            {showSplitBreakdown ? '合併顯示' : '依分割拆解'}
          </button>
        )}
      </div>

      <ResponsiveContainer width="100%" height={chartHeight}>
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 24, bottom: 4, left: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} horizontal={false} />
          <XAxis
            type="number"
            stroke={AXIS.stroke}
            tick={{ fontSize: AXIS.fontSize, fill: AXIS.stroke }}
            tickFormatter={formatNumber}
          />
          <YAxis
            type="category"
            dataKey="name"
            width={140}
            stroke={AXIS.stroke}
            tick={{ fontSize: AXIS.fontSize, fill: '#cbd5e1' }}
            interval={0}
          />
          <Tooltip content={<GlassTooltip />} cursor={{ fill: CURSOR_FILL }} />

          {showSplitBreakdown ? (
            <>
              <Legend wrapperStyle={{ fontSize: 10, color: AXIS.stroke }} />
              {splitNames.map((split, index) => (
                <Bar
                  key={split}
                  dataKey={split}
                  name={split}
                  stackId="splits"
                  fill={splitColor(split, index)}
                  radius={index === splitNames.length - 1 ? [0, 4, 4, 0] : 0}
                />
              ))}
            </>
          ) : (
            <>
              <ReferenceLine
                x={mean}
                stroke={REFERENCE_STROKE}
                strokeDasharray="4 4"
                label={{
                  value: `平均 ${Math.round(mean)}`,
                  position: 'top',
                  fill: AXIS.stroke,
                  fontSize: 9,
                }}
              />
              <Bar dataKey="total" name="標註數" radius={[0, 4, 4, 0]}>
                {data.map((entry, index) => (
                  <Cell key={entry.name} fill={seriesColor(index)} />
                ))}
              </Bar>
            </>
          )}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
};

export default ClassDistributionChart;
