// 匯出 UI 的靜態樣式查表。
//
// Tailwind JIT 只掃得到完整的靜態 class 字串，`bg-${x}-500` 這種樣板組字串在
// production build 會整個消失。因此所有依格式/狀態變動的樣式都用查表，
// 與 metric-dashboard/ModelMetricCard.jsx 的 ACCENT_STYLES 同一慣例。

// 格式徽章。走中性外框而不是各給一個色相：Nocturne 的原則是 accent 之外保持低彩度，
// 而「onnx 還是 litert」文字本身就講完了，不需要再用顏色講一次。
// 彩度留給真正帶語意的資料，見 docs/ui_redesign/adoption-notes.md 的 B1。
export const FORMAT_BADGE = {
  onnx: 'border-ds-neutral-700 text-ds-neutral-400',
  litert: 'border-ds-neutral-700 text-ds-neutral-400',
};

export const formatBadgeClass = (fmt) =>
  FORMAT_BADGE[fmt] || 'border-ds-neutral-800 text-ds-neutral-500';

// job 狀態 -> 呈現樣式。對照 adoption-notes.md 的 B1：
// queued 中性、running 用 accent（正在發生的事就是畫面上唯一的 accent，
// 所以刻意不另設 info 角色）、done 走 success、failed 走 danger。
export const STATE_STYLES = {
  queued: {
    chip: 'border-ds-neutral-700 text-ds-neutral-400',
    label: '排隊中',
  },
  running: {
    chip: 'border-accent text-accent',
    label: '進行中',
  },
  done: {
    chip: 'border-success-700 text-success-300',
    label: '已完成',
  },
  failed: {
    chip: 'border-danger-700 text-danger-300',
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
