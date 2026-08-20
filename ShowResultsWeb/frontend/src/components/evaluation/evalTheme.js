// Tailwind 的 JIT 是靜態掃描原始碼字串，`bg-${x}-500` 這種拼接會被裁掉。
// 需要依變數選色時一律用完整字串的查表物件（與 exportFormats.js / classMap.js 同樣的手法）。

export const STATE_STYLES = {
  queued: {
    label: '等待中',
    chip: 'bg-white/10 text-gray-300 border-white/20',
    bar: 'bg-gray-500',
  },
  running: {
    label: '進行中',
    chip: 'bg-indigo-500/15 text-indigo-300 border-indigo-500/30',
    bar: 'bg-indigo-500',
  },
  done: {
    label: '完成',
    chip: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
    bar: 'bg-emerald-500',
  },
  failed: {
    label: '失敗',
    chip: 'bg-red-500/15 text-red-400 border-red-500/30',
    bar: 'bg-red-500',
  },
};

export const VOCAB_STYLES = {
  match: {
    label: '類別一致',
    chip: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
  },
  name_drift: {
    label: '名稱不一致',
    chip: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
  },
  mismatch: {
    label: '類別數不符',
    chip: 'bg-red-500/15 text-red-400 border-red-500/30',
  },
};

// AP@50 低於此值在表格中標為需要注意，與後端報告的門檻一致
export const WEAK_AP_THRESHOLD = 0.5;

export const CHART_COLORS = {
  strong: '#2dd4bf',
  weak: '#f87171',
  grid: 'rgba(255,255,255,0.08)',
  axis: '#64748b',
  label: '#cbd5e1',
};

export const formatPct = (value) =>
  value === null || value === undefined ? '—' : `${value.toFixed(3)}%`;

export const formatMetric = (value) =>
  value === null || value === undefined ? '—' : value.toFixed(4);

export const formatElapsed = (seconds) => {
  if (seconds === null || seconds === undefined) return '—';
  if (seconds < 60) return `${Math.round(seconds)} 秒`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m} 分 ${s} 秒`;
};
