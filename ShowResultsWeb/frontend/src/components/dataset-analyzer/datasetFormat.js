// 純顯示用格式化工具，無 React 相依。

export const formatNumber = (value) => {
  if (value === null || value === undefined) return '—';
  return Number(value).toLocaleString('en-US');
};

export const formatCompact = (value) => {
  if (value === null || value === undefined) return '—';
  const n = Number(value);
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
};

export const formatPct = (value) => {
  if (value === null || value === undefined) return '—';
  return `${Number(value).toFixed(2)}%`;
};

export const formatMb = (value) => {
  if (!value) return '—';
  const n = Number(value);
  return n >= 1024 ? `${(n / 1024).toFixed(2)} GB` : `${n.toFixed(1)} MB`;
};

export const formatDuration = (ms) => {
  if (!ms && ms !== 0) return '—';
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${ms} ms`;
};

export const formatTimestamp = (iso) => {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString('zh-TW', { hour12: false });
};

export const FORMAT_LABELS = {
  yolo: 'YOLO',
  coco: 'COCO',
  voc: 'Pascal VOC',
};

export const formatLabel = (fmt) => FORMAT_LABELS[fmt] || String(fmt || '未知').toUpperCase();

// 依 level 排序（error → warning → info），同級維持原順序
const LEVEL_RANK = { error: 0, warning: 1, info: 2 };
export const sortIssues = (issues = []) =>
  [...issues].sort((a, b) => (LEVEL_RANK[a.level] ?? 9) - (LEVEL_RANK[b.level] ?? 9));

export const countByLevel = (issues = []) =>
  issues.reduce((acc, i) => {
    acc[i.level] = (acc[i.level] || 0) + 1;
    return acc;
  }, {});

// 類別表排序
export const sortClasses = (classes = [], key = 'count', dir = 'desc') => {
  const sorted = [...classes].sort((a, b) => {
    if (key === 'name') return String(a.name).localeCompare(String(b.name));
    if (key === 'id') return Number(a.id) - Number(b.id);
    return Number(a.count) - Number(b.count);
  });
  return dir === 'desc' ? sorted.reverse() : sorted;
};

// 不平衡比：最多的類別是最少（非零）類別的幾倍
export const imbalanceRatio = (classes = []) => {
  const counts = classes.map((c) => Number(c.count)).filter((n) => n > 0);
  if (counts.length < 2) return null;
  const max = Math.max(...counts);
  const min = Math.min(...counts);
  return min > 0 ? max / min : null;
};

export const meanCount = (classes = []) => {
  if (!classes.length) return 0;
  return classes.reduce((sum, c) => sum + Number(c.count || 0), 0) / classes.length;
};
