/**
 * 權重登錄簿的格式化工具與樣式查表。
 *
 * **Tailwind class 一律是完整的靜態字串**（CLAUDE.md 硬規則 3）：Tailwind 是靜態掃描
 * 原始碼，`bg-${color}-500` 這種拼接在 JIT 模式下會被裁掉，執行期才會發現顏色沒了。
 * 需要依變數選色時就用下面這種完整字串的查表物件。
 */

/** 指標欄位的顯示定義。key 同時是後端的排序欄位名。 */
export const METRIC_COLUMNS = [
  { key: 'map50', label: 'mAP@50', hint: '門檻無關' },
  { key: 'map50_95', label: 'mAP@50-95', hint: '門檻無關' },
  { key: 'precision', label: 'Precision', hint: 'TP/(TP+FP)' },
  { key: 'recall', label: 'Recall', hint: 'TP/(TP+FN)' },
  { key: 'f1', label: 'F1', hint: '2PR/(P+R)' },
  { key: 'micro_accuracy', label: 'Micro-Acc', hint: 'TP/(TP+FP+FN)，門檻相依' },
];

export const ARCH_STYLES = {
  yolo: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30',
  ssdlite_mobilenet_v3_large: 'bg-sky-500/10 text-sky-300 border-sky-500/30',
  ssdlite_mobilenet_v3_small: 'bg-sky-500/10 text-sky-300 border-sky-500/30',
  unknown: 'bg-slate-500/10 text-slate-300 border-slate-500/30',
};

export const SOURCE_STYLES = {
  zip: 'bg-violet-500/10 text-violet-300 border-violet-500/30',
  single_weight: 'bg-amber-500/10 text-amber-300 border-amber-500/30',
  local_library: 'bg-cyan-500/10 text-cyan-300 border-cyan-500/30',
  unknown: 'bg-slate-500/10 text-slate-300 border-slate-500/30',
};

export const SOURCE_LABELS = {
  zip: 'ZIP 訓練成果',
  single_weight: '單一權重檔',
  local_library: '本機資料夾',
};

export const archStyle = (arch) => ARCH_STYLES[arch] || ARCH_STYLES.unknown;
export const sourceStyle = (source) => SOURCE_STYLES[source] || SOURCE_STYLES.unknown;
export const sourceLabel = (source) => SOURCE_LABELS[source] || source || '未知來源';

/** 指標一律四位小數；`null` 顯示破折號而不是 0——「沒測過」與「測出來是零」不同。 */
export const fmtMetric = (value) =>
  value === null || value === undefined ? '—' : Number(value).toFixed(4);

export const fmtInt = (value) =>
  value === null || value === undefined ? '—' : Number(value).toLocaleString();

export const fmtSize = (mb) =>
  mb === null || mb === undefined ? '—' : `${Number(mb).toFixed(2)} MB`;

export const fmtSeconds = (s) => {
  if (s === null || s === undefined) return '—';
  const total = Math.round(Number(s));
  const m = Math.floor(total / 60);
  return m > 0 ? `${m} 分 ${total % 60} 秒` : `${total} 秒`;
};

export const fmtDateTime = (iso) => {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  return d.toLocaleString('zh-TW', { hour12: false });
};

export const shortSha = (sha) => (sha ? sha.slice(0, 12) : '—');

/** 排序指示箭頭。未排序此欄時回空字串，避免每欄都掛一個誤導的箭頭。 */
export const sortArrow = (sort, field) =>
  sort.order_by === field ? (sort.order === 'desc' ? ' ▼' : ' ▲') : '';
