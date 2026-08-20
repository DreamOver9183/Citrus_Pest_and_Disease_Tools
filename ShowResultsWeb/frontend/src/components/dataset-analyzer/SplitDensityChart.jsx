import React from 'react';
import {
  ComposedChart, Bar, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer, Cell,
} from 'recharts';
import { TrendingUp } from 'lucide-react';
import GlassTooltip from './GlassTooltip';
import { splitColor, AXIS, GRID_STROKE, CURSOR_FILL } from './chartTheme';
import { formatNumber } from './datasetFormat';

// 影像數（長條，左軸）對比每張影像的平均標註數（折線，右軸）。
// 這組對比能一眼看出「訓練集經過增強、驗證/測試集維持原樣」造成的密度落差。
const SplitDensityChart = ({ stats }) => {
  const splits = stats.splits || [];
  if (splits.length === 0) return null;

  const data = splits.map((s) => ({
    name: s.name,
    images: s.images,
    density: s.annotations_per_image,
    background: s.background_images,
  }));

  return (
    <div className="glass-panel p-6 rounded-2xl border border-white/[0.06] space-y-6 shadow-2xl relative overflow-hidden">
      <div className="absolute top-[-20%] right-[-10%] w-[150px] h-[150px] rounded-full bg-orange-500/5 blur-[50px] pointer-events-none"></div>

      <div className="flex items-center gap-2.5 border-b border-white/5 pb-4">
        <div className="p-2 bg-orange-500/10 rounded-lg text-orange-400">
          <TrendingUp className="w-4 h-4" />
        </div>
        <div className="text-left">
          <h3 className="font-extrabold text-white text-sm font-sans tracking-tight">
            分割規模與標註密度
          </h3>
          <p className="text-[10px] text-gray-400 font-mono mt-0.5">
            Split Size vs Annotation Density
          </p>
        </div>
      </div>

      <ResponsiveContainer width="100%" height={260}>
        <ComposedChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} vertical={false} />
          <XAxis
            dataKey="name"
            stroke={AXIS.stroke}
            tick={{ fontSize: AXIS.fontSize, fill: '#cbd5e1' }}
          />
          <YAxis
            yAxisId="left"
            stroke={AXIS.stroke}
            tick={{ fontSize: AXIS.fontSize, fill: AXIS.stroke }}
            tickFormatter={formatNumber}
          />
          <YAxis
            yAxisId="right"
            orientation="right"
            stroke="#a855f7"
            tick={{ fontSize: AXIS.fontSize, fill: '#a855f7' }}
          />
          <Tooltip content={<GlassTooltip />} cursor={{ fill: CURSOR_FILL }} />
          <Legend wrapperStyle={{ fontSize: 10, color: AXIS.stroke }} />
          <Bar yAxisId="left" dataKey="images" name="影像數" radius={[4, 4, 0, 0]}>
            {data.map((entry, index) => (
              <Cell key={entry.name} fill={splitColor(entry.name, index)} />
            ))}
          </Bar>
          <Line
            yAxisId="right"
            type="monotone"
            dataKey="density"
            name="每張平均標註數"
            stroke="#a855f7"
            strokeWidth={2}
            dot={{ r: 4, fill: '#a855f7' }}
            activeDot={{ r: 6 }}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
};

export default SplitDensityChart;
