import React, { useState } from 'react';
import { ChevronRight, Trash2, FileCode } from 'lucide-react';
import ExportPanel from './ExportPanel';
import { sourceLabel } from '../registry/registryFormat';

// 已載入模型的一列，點擊展開明細。
//
// 為什麼是「可展開的列」而不是卡片牆：MAX_SESSIONS 只有 3，但每個模型要顯示的
// 細節不少（來源檔、優化器、模型設定、工作區路徑、匯出面板）。全部攤開會讓三個
// 模型佔滿整頁而難以互相比較；收起來之後，一眼就能橫向比對名稱、輪數、大小與兩個
// mAP，需要細節再展開那一列。
//
// 這也是採用決策 B2 的落點：**不做可排序的資料表**。那會與權重登錄簿的
// WeightTable 重複，而且為最多三列做排序沒有意義。見 docs/ui_redesign/adoption-notes.md。

// `metrics_summary` 的鍵是後端把 results.csv 的表頭原樣帶過來的（只去掉 `metrics/`
// 前綴與 `(B)` 後綴，見 utils/dir_handler.py），因此鍵名會隨 ultralytics 版本變動：
// mAP50 / mAP_50 / mAP@50 都出現過。後端的 registry_service.py 用一組別名表做比對，
// 這裡比照同一組別名，並忽略大小寫。
//
// 舊版這裡寫死讀 `metrics_summary.mAP` 與 `.mAP_50`，兩個鍵實際上都不存在——
// 模型卡上的「最佳 mAP / mAP@50」因此一直顯示 N/A。
const METRIC_ALIASES = {
  map50: ['map50', 'map_50', 'map@50'],
  map50_95: ['map50-95', 'map50_95', 'map_50_95', 'map@50-95'],
};

const pickMetric = (metrics, which) => {
  const lower = {};
  Object.keys(metrics || {}).forEach((k) => {
    lower[k.toLowerCase()] = metrics[k];
  });
  for (const alias of METRIC_ALIASES[which]) {
    const v = lower[alias];
    if (v !== undefined && v !== null && v !== '') return v;
  }
  return null;
};

const fmtValue = (v) => (v === null || v === undefined || v === '' ? '—' : v);

// 指標一律四位小數，與權重登錄簿的 fmtMetric 一致
const fmtMetric = (v) => {
  if (v === null || v === undefined || v === '') return '—';
  const n = Number(v);
  return Number.isFinite(n) ? n.toFixed(4) : String(v);
};

const ModelRow = ({
  session,
  name,
  onNameChange,
  onNameCommit,
  onDelete,
}) => {
  const [expanded, setExpanded] = useState(false);
  const map50 = pickMetric(session.metrics_summary, 'map50');
  const map5095 = pickMetric(session.metrics_summary, 'map50_95');

  return (
    <div className="border border-ds-neutral-800 rounded-ds bg-surface/40 overflow-hidden transition-colors hover:border-ds-neutral-700">
      {/* 收合狀態：一列可橫向比較的數字。
          按鈕內容是巢狀的 div 與 dl，可及性名稱算不出一個有意義的字串，
          所以用 aria-label 明講這顆按鈕在做什麼。 */}
      <button
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        aria-label={`${expanded ? '收合' : '展開'} ${name || '未命名模型'} 的明細`}
        className="w-full text-left px-4 py-3 flex items-center gap-4 cursor-pointer hover:bg-ds-neutral-800/30 transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-[-2px]"
      >
        <ChevronRight
          className={`w-4 h-4 flex-shrink-0 text-ds-neutral-500 transition-transform ${
            expanded ? 'rotate-90' : ''
          }`}
        />

        <div className="flex-1 min-w-0">
          <div className="text-sm text-ink truncate" title={name}>
            {name || '未命名模型'}
          </div>
          <div className="flex items-center gap-2 mt-1">
            <span className="text-[11px] px-1.5 py-0.5 rounded-ds-sm border border-ds-neutral-700 text-ds-neutral-400">
              {session.model_arch || 'yolo'}
            </span>
            <span className="text-[11px] px-1.5 py-0.5 rounded-ds-sm border border-ds-neutral-700 text-ds-neutral-400">
              {sourceLabel(session.source_type)}
            </span>
          </div>
        </div>

        {/* 數字右對齊、等寬，三個模型才對得起來 */}
        <dl className="hidden sm:flex items-center gap-6 text-right flex-shrink-0">
          <div>
            <dt className="text-[10px] text-ds-neutral-600 tracking-wide">EPOCHS</dt>
            <dd className="text-sm text-ink tabular-nums">{fmtValue(session.epochs)}</dd>
          </div>
          <div>
            <dt className="text-[10px] text-ds-neutral-600 tracking-wide">大小</dt>
            <dd className="text-sm text-ink tabular-nums">
              {fmtValue(session.weights_size_mb)}
              <span className="text-ds-neutral-600 ml-1 text-xs">MB</span>
            </dd>
          </div>
          <div>
            <dt className="text-[10px] text-ds-neutral-600 tracking-wide">mAP@50</dt>
            <dd className="text-sm text-ink tabular-nums">{fmtMetric(map50)}</dd>
          </div>
          <div>
            <dt className="text-[10px] text-ds-neutral-600 tracking-wide">mAP@50-95</dt>
            <dd className="text-sm text-ink tabular-nums">{fmtMetric(map5095)}</dd>
          </div>
        </dl>
      </button>

      {expanded && (
        <div className="px-4 pb-4 pt-1 border-t border-ds-neutral-800 space-y-5">
          {/* 窄螢幕看不到收合列的數字，這裡補上 */}
          <dl className="sm:hidden grid grid-cols-2 gap-3 pt-3 text-sm">
            <div>
              <dt className="text-[10px] text-ds-neutral-600">EPOCHS</dt>
              <dd className="text-ink tabular-nums">{fmtValue(session.epochs)}</dd>
            </div>
            <div>
              <dt className="text-[10px] text-ds-neutral-600">大小</dt>
              <dd className="text-ink tabular-nums">{fmtValue(session.weights_size_mb)} MB</dd>
            </div>
            <div>
              <dt className="text-[10px] text-ds-neutral-600">mAP@50</dt>
              <dd className="text-ink tabular-nums">{fmtMetric(map50)}</dd>
            </div>
            <div>
              <dt className="text-[10px] text-ds-neutral-600">mAP@50-95</dt>
              <dd className="text-ink tabular-nums">{fmtMetric(map5095)}</dd>
            </div>
          </dl>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-3 text-sm">
            <div>
              <div className="text-[10px] text-ds-neutral-600 mb-1">來源檔案</div>
              <div className="text-ink truncate" title={session.zip_name}>
                {session.zip_name || '—'}
              </div>
              {session.format_label && (
                <div className="text-xs text-ds-neutral-500 mt-0.5">{session.format_label}</div>
              )}
            </div>
            <div>
              <div className="text-[10px] text-ds-neutral-600 mb-1">優化器</div>
              <div className="text-ink">{session.optimizer || '—'}</div>
            </div>
            <div>
              <div className="text-[10px] text-ds-neutral-600 mb-1">模型設定</div>
              <div className="text-ink truncate" title={session.model_cfg}>
                {session.model_cfg || '—'}
              </div>
            </div>
          </div>

          <div>
            <label className="block text-[10px] text-ds-neutral-600 mb-1.5" htmlFor={`name-${session.session_id}`}>
              顯示名稱
            </label>
            <input
              id={`name-${session.session_id}`}
              type="text"
              value={name || ''}
              onChange={(e) => onNameChange(e.target.value)}
              onBlur={onNameCommit}
              onKeyDown={(e) => e.key === 'Enter' && onNameCommit()}
              placeholder="請輸入此模型的顯示名稱"
              className="w-full max-w-md bg-ground border border-ds-neutral-700 rounded-ds px-3 py-2 text-sm text-ink placeholder:text-ds-neutral-600 focus:border-accent focus:outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2 transition-colors"
            />
          </div>

          <ExportPanel session={session} />

          <div className="flex items-center justify-between gap-4 pt-1">
            <div className="flex items-center gap-1.5 text-xs text-ds-neutral-600 min-w-0">
              <FileCode className="w-3.5 h-3.5 flex-shrink-0" />
              <span className="truncate" title={session.dir_path}>
                {session.dir_path}
              </span>
            </div>
            <button
              onClick={onDelete}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-ds border border-ds-neutral-700 text-ds-neutral-400 text-xs hover:border-danger-500 hover:text-danger-300 transition-colors cursor-pointer flex-shrink-0 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2"
              title="移除模型"
            >
              <Trash2 className="w-3.5 h-3.5" />
              移除
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

export default ModelRow;
