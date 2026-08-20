import React, { useState } from 'react';
import { FileCode, Check, Copy, ChevronDown, ChevronRight } from 'lucide-react';

const KIND_LABEL = { yaml: 'data.yaml', json: 'COCO JSON', xml: 'VOC XML' };

// 原始定義檔內容（yaml / json / xml）。
const DefinitionViewer = ({ definition, expanded, onToggle }) => {
  const [copied, setCopied] = useState(false);

  if (!definition) return null;

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(definition.text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      // 剪貼簿在非安全來源(http)下不可用，靜默忽略即可
    }
  };

  return (
    <div className="glass-panel p-6 rounded-2xl border border-white/[0.06] space-y-4 shadow-2xl">
      <div className="flex items-center justify-between border-b border-white/5 pb-4 gap-3">
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="p-2 bg-emerald-500/10 rounded-lg text-emerald-400 flex-shrink-0">
            <FileCode className="w-4 h-4" />
          </div>
          <div className="text-left min-w-0">
            <h3 className="font-extrabold text-white text-sm font-sans tracking-tight truncate">
              資料集定義檔
            </h3>
            <p className="text-[10px] text-gray-400 font-mono mt-0.5 truncate">
              {KIND_LABEL[definition.kind] || definition.kind} · {definition.filename}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-1.5 flex-shrink-0">
          <button
            onClick={handleCopy}
            className="text-[9px] px-2 py-1 bg-white/5 hover:bg-emerald-500 hover:text-white border border-white/10 rounded-md transition-all cursor-pointer font-bold font-sans flex items-center gap-1"
            title="複製內容"
          >
            {copied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
            {copied ? '已複製' : '複製'}
          </button>
          <button
            onClick={onToggle}
            className="text-gray-500 hover:text-white transition-colors"
            title={expanded ? '收合' : '展開'}
          >
            {expanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
          </button>
        </div>
      </div>

      {expanded ? (
        <div className="bg-slate-950/70 rounded-xl border border-white/5 overflow-hidden">
          <pre className="text-[10px] text-gray-300 font-mono leading-relaxed p-4 overflow-x-auto max-h-[400px] whitespace-pre">
            {definition.text}
          </pre>
          {definition.truncated && (
            <p className="text-[9px] text-amber-400 font-mono px-4 py-2 border-t border-white/5 bg-amber-500/5">
              內容過長，僅顯示前段
            </p>
          )}
        </div>
      ) : (
        <p className="text-[11px] text-gray-500 font-sans">已收合，點擊右上箭頭展開原始內容</p>
      )}
    </div>
  );
};

export default DefinitionViewer;
