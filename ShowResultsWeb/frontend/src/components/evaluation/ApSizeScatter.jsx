import React, { useMemo } from 'react';
import {
  ScatterChart, Scatter, XAxis, YAxis, CartesianGrid, ResponsiveContainer,
  Tooltip, LabelList, ReferenceLine,
} from 'recharts';
import { CHART_COLORS, WEAK_AP_THRESHOLD } from './evalTheme';

// 每類別的 AP@50 對中位標註框面積。
//
// X 軸用對數刻度：實測這個資料集的中位框面積從 0.19%（潰瘍病）到 52%（煤煙病），
// 跨越近三個數量級，線性軸會把所有小物件類別擠成左邊一團而看不出任何結構。
//
// 若低 AP 集中在左側，代表瓶頸在小尺度特徵擷取——這正是高解析度 P2 檢測層要解決的
// 問題，也是這張圖存在的理由。
const ApSizeScatter = ({ perClass, sizeProfile }) => {
  const points = useMemo(() => {
    const sizeById = new Map((sizeProfile || []).map((s) => [s.class_id, s]));
    return (perClass || [])
      .map((entry) => {
        const size = sizeById.get(entry.class_id);
        if (!size || !size.median_area_pct) return null;
        return {
          name: entry.name,
          area: size.median_area_pct,
          ap50: entry.ap50,
          boxes: size.boxes,
          tiny: size.tiny_pct,
        };
      })
      .filter(Boolean);
  }, [perClass, sizeProfile]);

  if (points.length < 2) return null;

  const strong = points.filter((p) => p.ap50 >= WEAK_AP_THRESHOLD);
  const weak = points.filter((p) => p.ap50 < WEAK_AP_THRESHOLD);

  // 散點的每個點代表一個類別、要顯示四個不同單位的欄位，與 dataset-analyzer 的
  // GlassTooltip（逐 series 列出同一個量）形狀不同，因此另寫一份但沿用同樣的視覺語彙。
  const renderTooltip = ({ active, payload }) => {
    if (!active || !payload?.length) return null;
    const p = payload[0].payload;
    const rows = [
      ['AP@50', p.ap50.toFixed(4)],
      ['中位框面積', `${p.area.toFixed(3)}%`],
      ['標註框數', p.boxes?.toLocaleString() ?? '—'],
      ['極小框佔比', p.tiny === null || p.tiny === undefined ? '—' : `${p.tiny.toFixed(1)}%`],
    ];
    return (
      <div className="bg-slate-950/95 border border-white/10 rounded-xl px-3 py-2.5 shadow-2xl backdrop-blur-md min-w-[160px]">
        <div className="text-[11px] font-bold text-white mb-1.5 font-sans">{p.name}</div>
        <div className="space-y-1">
          {rows.map(([label, value]) => (
            <div key={label} className="flex items-center justify-between gap-3">
              <span className="text-[10px] text-gray-400 font-sans">{label}</span>
              <span className="text-[11px] text-white font-mono font-bold">{value}</span>
            </div>
          ))}
        </div>
      </div>
    );
  };

  return (
    <div className="h-[340px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <ScatterChart margin={{ top: 16, right: 28, bottom: 40, left: 8 }}>
          <CartesianGrid stroke={CHART_COLORS.grid} />
          <XAxis
            type="number"
            dataKey="area"
            scale="log"
            domain={['auto', 'auto']}
            allowDataOverflow={false}
            tick={{ fill: CHART_COLORS.axis, fontSize: 10 }}
            tickFormatter={(v) => `${v}%`}
            label={{
              value: '中位標註框面積（佔整張影像，對數刻度）',
              position: 'insideBottom', offset: -22,
              fill: CHART_COLORS.label, fontSize: 11,
            }}
          />
          <YAxis
            type="number"
            dataKey="ap50"
            domain={[0, 1]}
            tick={{ fill: CHART_COLORS.axis, fontSize: 10 }}
            label={{
              value: 'AP@50', angle: -90, position: 'insideLeft',
              fill: CHART_COLORS.label, fontSize: 11,
            }}
          />
          <ReferenceLine
            y={WEAK_AP_THRESHOLD}
            stroke={CHART_COLORS.weak}
            strokeDasharray="4 4"
            strokeOpacity={0.5}
          />
          <Tooltip content={renderTooltip} cursor={{ strokeDasharray: '3 3' }} />
          {/* 隱藏分頁時 rAF 被節流到 0 fps，動畫永遠跑不完、圖表會停在 0 個點 */}
          <Scatter data={strong} fill={CHART_COLORS.strong} isAnimationActive={false}>
            <LabelList dataKey="name" position="right" fill={CHART_COLORS.label} fontSize={10} />
          </Scatter>
          <Scatter data={weak} fill={CHART_COLORS.weak} isAnimationActive={false}>
            <LabelList dataKey="name" position="right" fill={CHART_COLORS.weak} fontSize={10} />
          </Scatter>
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
};

export default ApSizeScatter;
