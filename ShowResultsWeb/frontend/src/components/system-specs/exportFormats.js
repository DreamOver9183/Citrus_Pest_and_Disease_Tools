// 匯出 UI 的靜態樣式查表。
//
// Tailwind JIT 只掃得到完整的靜態 class 字串，`bg-${x}-500` 這種樣板組字串在
// production build 會整個消失。因此所有依格式/狀態變動的樣式都用查表，
// 與 metric-dashboard/ModelMetricCard.jsx 的 ACCENT_STYLES 同一慣例。

// 與 SystemSpecs 卡片上既有的格式徽章配色一致
export const FORMAT_BADGE = {
  onnx: 'bg-blue-500/15 text-blue-400 border-blue-500/25',
  litert: 'bg-green-500/15 text-green-400 border-green-500/25',
};

export const formatBadgeClass = (fmt) =>
  FORMAT_BADGE[fmt] || 'bg-gray-500/15 text-gray-400 border-gray-500/25';

// job 狀態 -> 呈現樣式
export const STATE_STYLES = {
  queued: {
    chip: 'bg-white/5 text-gray-400 border-white/10',
    label: '排隊中',
  },
  running: {
    chip: 'bg-orange-500/10 text-orange-400 border-orange-500/25',
    label: '進行中',
  },
  done: {
    chip: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30',
    label: '已完成',
  },
  failed: {
    chip: 'bg-red-500/10 text-red-400 border-red-500/30',
    label: '失敗',
  },
};

export const stateStyle = (state) => STATE_STYLES[state] || STATE_STYLES.queued;

// 不可用原因的類型 -> 使用者該採取的下一步
export const REASON_HINT = {
  platform: '此格式在目前的作業系統無法轉換，請改用 Docker 容器執行。',
  dependency: '此格式所需的套件未安裝於目前環境。',
};

export const formatBytesLabel = (mb) => {
  if (mb === null || mb === undefined) return '—';
  const n = Number(mb);
  return n >= 1024 ? `${(n / 1024).toFixed(2)} GB` : `${n.toFixed(2)} MB`;
};

export const formatElapsed = (seconds) => {
  if (seconds === null || seconds === undefined) return '';
  const n = Number(seconds);
  if (n < 60) return `${n.toFixed(0)} 秒`;
  const m = Math.floor(n / 60);
  const s = Math.floor(n % 60);
  return `${m} 分 ${s} 秒`;
};

// 進行中的階段是否應顯示不定量動畫。
// exporting 佔了整個匯出約九成的時間卻沒有任何中間進度可回報（ultralytics 只有
// on_export_start / on_export_end 兩個 callback），顯示一個停在 25% 不動的進度條
// 會讓人以為卡住了，所以這個階段改走脈動動畫。
export const isIndeterminateStage = (stage) => stage === 'exporting';
