import React from 'react';
import { ShieldCheck, ChevronDown, ChevronRight } from 'lucide-react';
import { LEVEL_STYLES } from './chartTheme';
import { sortIssues, countByLevel } from './datasetFormat';

// 資料集健檢結果。刻意把 error / warning / info 視覺上分明：
// 空標註檔、零實例類別這類「看起來像問題但其實正常」的情況一律是 info，
// 若誤標成 error 會讓使用者以為資料集壞了。
const ValidationIssueList = ({ issues = [], expanded, onToggle }) => {
  const sorted = sortIssues(issues);
  const counts = countByLevel(issues);

  return (
    <div className="glass-panel p-6 rounded-2xl border border-white/[0.06] space-y-4 shadow-2xl">
      <div className="flex items-center justify-between border-b border-white/5 pb-4 gap-3">
        <div className="flex items-center gap-2.5">
          <div
            className={`p-2 rounded-lg ${
              counts.error ? 'bg-red-500/10 text-red-400' : 'bg-emerald-500/10 text-emerald-400'
            }`}
          >
            <ShieldCheck className="w-4 h-4" />
          </div>
          <div className="text-left">
            <h3 className="font-extrabold text-white text-sm font-sans tracking-tight">
              資料集健檢
            </h3>
            <p className="text-[10px] text-gray-400 font-mono mt-0.5">Validation Report</p>
          </div>
        </div>

        <div className="flex items-center gap-1.5 flex-wrap justify-end">
          {['error', 'warning', 'info'].map((level) =>
            counts[level] ? (
              <span
                key={level}
                className={`text-[9px] px-2 py-0.5 rounded-md border font-mono font-bold ${LEVEL_STYLES[level].chip}`}
              >
                {LEVEL_STYLES[level].label} {counts[level]}
              </span>
            ) : null
          )}
          {sorted.length > 0 && (
            <button
              onClick={onToggle}
              className="text-gray-500 hover:text-white transition-colors ml-1"
              title={expanded ? '收合' : '展開'}
            >
              {expanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
            </button>
          )}
        </div>
      </div>

      {sorted.length === 0 ? (
        <div className="flex items-center gap-2 text-emerald-400 text-xs font-sans font-bold py-2">
          <ShieldCheck className="w-4 h-4" />
          未發現任何結構或標註問題
        </div>
      ) : !expanded ? (
        <p className="text-[11px] text-gray-500 font-sans">已收合 {sorted.length} 則檢查結果</p>
      ) : (
        <div className="space-y-2">
          {sorted.map((issue, index) => {
            const style = LEVEL_STYLES[issue.level] || LEVEL_STYLES.info;
            return (
              <div
                key={`${issue.code}-${index}`}
                className="bg-slate-950/40 rounded-xl p-3.5 border border-white/5 space-y-1.5"
              >
                <div className="flex items-start gap-2.5">
                  <span className={`w-2 h-2 rounded-full flex-shrink-0 mt-1.5 ${style.dot}`} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-[11px] text-white font-bold font-sans">
                        {issue.message}
                      </span>
                      <span className="text-[8px] text-gray-600 font-mono uppercase tracking-wider">
                        {issue.code}
                      </span>
                    </div>
                    {issue.detail && (
                      <p className="text-[10px] text-gray-400 mt-1 leading-relaxed font-sans break-words">
                        {issue.detail}
                      </p>
                    )}
                    {issue.samples && issue.samples.length > 0 && (
                      <div className="mt-2 p-2 bg-slate-950/70 rounded-lg border border-white/5 space-y-0.5 max-h-32 overflow-y-auto">
                        {issue.samples.map((sample, i) => (
                          <p
                            key={i}
                            className="text-[9px] text-gray-500 font-mono break-all leading-relaxed"
                          >
                            {sample}
                          </p>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default ValidationIssueList;
