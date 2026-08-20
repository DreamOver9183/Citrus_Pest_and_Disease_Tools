// 圖表主題常數。
//
// recharts 的 fill / stroke 吃的是真實色值而非 class 名，因此這裡放 hex；
// 非圖表的徽章仍須使用完整靜態 Tailwind 字串（Tailwind JIT 掃不到樣板字串組出的
// class，production build 會整個消失），故另設 BADGE_STYLES 查表。

// 類別序列色。相鄰對比是重點，避免像 classMap.js 那樣同色重複出現。
// 超過長度時以取餘數循環。
export const CHART_SERIES = [
  '#f97316', // orange
  '#6366f1', // indigo
  '#10b981', // emerald
  '#f43f5e', // rose
  '#38bdf8', // sky
  '#a855f7', // purple
  '#eab308', // yellow
  '#14b8a6', // teal
  '#ec4899', // pink
  '#84cc16', // lime
  '#f59e0b', // amber
  '#8b5cf6', // violet
];

export const seriesColor = (index) => CHART_SERIES[index % CHART_SERIES.length];

// split 固定色，與三個既有分頁的主色語彙一致
export const SPLIT_COLORS = {
  train: '#f97316',
  valid: '#6366f1',
  val: '#6366f1',
  test: '#10b981',
  training: '#f97316',
  validation: '#6366f1',
};

export const splitColor = (name, index = 0) =>
  SPLIT_COLORS[String(name).toLowerCase()] || seriesColor(index);

export const AXIS = {
  stroke: '#64748b',
  fontSize: 10,
};

export const GRID_STROKE = 'rgba(255,255,255,0.06)';
export const CURSOR_FILL = 'rgba(255,255,255,0.04)';
export const REFERENCE_STROKE = 'rgba(255,255,255,0.28)';

// 問題等級的靜態 Tailwind 字串（供徽章與清單使用）
export const LEVEL_STYLES = {
  error: {
    chip: 'bg-red-500/10 text-red-400 border-red-500/30',
    dot: 'bg-red-500',
    label: '錯誤',
  },
  warning: {
    chip: 'bg-amber-500/10 text-amber-400 border-amber-500/30',
    dot: 'bg-amber-400',
    label: '警告',
  },
  info: {
    chip: 'bg-sky-500/10 text-sky-400 border-sky-500/30',
    dot: 'bg-sky-400',
    label: '資訊',
  },
};

// 格式徽章
export const FORMAT_STYLES = {
  yolo: 'bg-rose-500/10 text-rose-400 border-rose-500/30',
  coco: 'bg-indigo-500/10 text-indigo-300 border-indigo-500/30',
  voc: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30',
};
