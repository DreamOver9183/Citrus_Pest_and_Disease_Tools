import { CLASS_MAP } from '../live-demo/classMap';

// 逐張檢視的靜態樣式查表。
//
// 框的顏色走 SVG 屬性直接吃 CSS 變數：Tailwind JIT 的限制（CLAUDE.md 硬規則 3）只作用
// 在 class 字串，stroke="var(--color-…)" 不受影響，也不需要 -rgb 通道版本。
//
// 顏色與線型刻意雙重編碼：**實線 = 預測、虛線 = 標註**，顏色表示配對結果，標籤文字再講
// 一次。只靠顏色的話，色覺辨識困難的使用者分不出正確與誤報。
//
// 類別錯不用建議書的橘色：Nocturne 的 warning 落在琥珀橘，而漏抓用的正是 warning，
// 兩者只差線型太容易混。改用與綠／紅／琥珀、以及 accent 都拉得開的青色類別色。
export const BOX_STYLES = {
  tp: { stroke: 'var(--color-success-500)', label: '正確' },
  fp: { stroke: 'var(--color-danger-500)', label: '誤報' },
  fn: { stroke: 'var(--color-warning-500)', label: '漏抓' },
  wrong: { stroke: 'var(--color-cat-12-500)', label: '類別錯' },
};

export const GT_DASH = '6 4';

export const LEGEND = [
  { status: 'tp', dashed: false, label: '正確' },
  { status: 'fp', dashed: false, label: '誤報' },
  { status: 'wrong', dashed: false, label: '類別錯' },
  { status: 'fn', dashed: true, label: '漏抓' },
];

export const STATUS_OPTIONS = [
  { value: 'all', label: '全部' },
  { value: 'errors', label: '有錯誤' },
  { value: 'fn', label: '有漏抓' },
  { value: 'fp', label: '有誤報' },
  { value: 'wrong', label: '有類別錯' },
  { value: 'clean', label: '全對' },
];

export const statusCount = (value, summary) => {
  if (!summary) return null;
  switch (value) {
    case 'all': return summary.images;
    case 'errors': return summary.images - summary.clean;
    case 'clean': return summary.clean;
    case 'fn': return summary.with_fn;
    case 'fp': return summary.with_fp;
    case 'wrong': return summary.with_wrong;
    default: return null;
  }
};

export const SORT_OPTIONS = [
  { value: 'errors', label: '錯誤數多的在前' },
  { value: 'name', label: '檔名' },
];

export const LAYER_OPTIONS = [
  { value: 'both', label: '兩者' },
  { value: 'gt', label: '只看標註' },
  { value: 'pred', label: '只看預測' },
];

// 可切換的選項（split、狀態、類別、圖層）共用的外框樣式
export const CHIP = {
  on: 'border-accent bg-accent/10 text-ink',
  off: 'border-ds-neutral-700 text-ds-neutral-400 hover:border-ds-neutral-600 hover:text-ink',
};

// 卡片上的逐張計數徽章
export const COUNT_BADGE = {
  fn: 'border-warning-700 text-warning-300',
  fp: 'border-danger-700 text-danger-300',
  wrong: 'border-cat-12-500/60 text-cat-12-400',
  clean: 'border-success-700 text-success-300',
};

// 類別色點，對應 adoption-notes.md B1 的刻意指派（Sooty_Mold 為中性灰的例外）
export const CLASS_DOT = {
  Oily_Spot: 'bg-cat-1-500',
  Canker: 'bg-cat-2-500',
  Black_Spot: 'bg-cat-3-500',
  Scale_Insect: 'bg-cat-4-500',
  Citrus_Leaf_Miner: 'bg-cat-5-500',
  Thrips: 'bg-cat-6-500',
  Aphid: 'bg-cat-7-500',
  Thrips_Damage: 'bg-cat-8-500',
  Sooty_Mold: 'bg-ds-neutral-500',
};

export const classDot = (name) => CLASS_DOT[name] || 'bg-ds-neutral-600';

// 「介殼蟲 (Scale Insect)」→「介殼蟲」：框上的標籤要短，查不到就用原名
export const shortClassName = (raw) =>
  (CLASS_MAP[raw]?.name || raw || '').replace(/\s*\(.*\)\s*$/, '');

// 上傳的 TFLite session 名稱本身就帶「(TFLite)」，名稱裡已經有就不再補一次
export const tfliteSuffix = (name, format, text = ' · TFLite') =>
  format === 'tflite' && !/tflite/i.test(name || '') ? text : '';

export const formatElapsed = (seconds) => {
  if (seconds === null || seconds === undefined) return '';
  const n = Number(seconds);
  if (n < 60) return `${n.toFixed(0)} 秒`;
  return `${Math.floor(n / 60)} 分 ${Math.floor(n % 60)} 秒`;
};
