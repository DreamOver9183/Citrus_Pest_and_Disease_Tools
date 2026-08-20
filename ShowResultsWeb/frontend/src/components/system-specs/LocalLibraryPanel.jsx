import React, { useState } from 'react';
import {
  FolderSearch, RefreshCw, Copy, Check, AlertCircle, CheckCircle2,
  Box, Database, Download, FileArchive, Folder, FileBox,
} from 'lucide-react';
import { useExperiment } from '../../context/ExperimentContext';

// 來源形態的視覺標示。Tailwind 需要完整靜態 class 字串，不能用拼接。
const SOURCE_META = {
  run_dir: { label: '資料夾', Icon: Folder, tone: 'text-teal-400' },
  weight_file: { label: '權重檔', Icon: FileBox, tone: 'text-sky-400' },
  zip_run: { label: 'ZIP', Icon: FileArchive, tone: 'text-amber-400' },
  dataset_dir: { label: '資料夾', Icon: Folder, tone: 'text-teal-400' },
  dataset_zip: { label: 'ZIP', Icon: FileArchive, tone: 'text-amber-400' },
};

const CandidateRow = ({ candidate, checked, onToggle }) => {
  const meta = SOURCE_META[candidate.source_kind] || SOURCE_META.run_dir;
  const { Icon } = meta;
  const disabled = candidate.already_registered;

  return (
    <label
      className={`flex items-start gap-2.5 p-2.5 rounded-lg border transition-all ${
        disabled
          ? 'bg-white/[0.02] border-white/5 opacity-50 cursor-default'
          : checked
            ? 'bg-teal-500/10 border-teal-500/40 cursor-pointer'
            : 'bg-slate-950/40 border-white/5 hover:border-white/15 cursor-pointer'
      }`}
    >
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={() => onToggle(candidate.candidate_id)}
        className="mt-0.5 w-3.5 h-3.5 flex-shrink-0 accent-teal-500 cursor-pointer disabled:cursor-default"
      />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <Icon className={`w-3 h-3 flex-shrink-0 ${meta.tone}`} />
          <span className="text-[11px] font-bold text-white truncate" title={candidate.name}>
            {candidate.name}
          </span>
          {disabled && (
            <span className="text-[8px] px-1.5 py-0.5 bg-white/10 text-gray-400 rounded font-bold flex-shrink-0">
              已載入
            </span>
          )}
        </div>
        <p className="text-[9px] text-gray-500 font-mono truncate mt-0.5" title={candidate.rel_path}>
          {candidate.rel_path}
        </p>
        <p className="text-[9px] text-gray-400 mt-0.5">
          {candidate.detail}
          {candidate.size_mb ? ` · ${candidate.size_mb} MB` : ''}
        </p>
      </div>
    </label>
  );
};

const CandidateGroup = ({ title, Icon, items, selectedIds, onToggle, onToggleAll }) => {
  if (items.length === 0) return null;
  const selectable = items.filter((c) => !c.already_registered);
  const allSelected =
    selectable.length > 0 && selectable.every((c) => selectedIds.includes(c.candidate_id));

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-bold text-gray-400 uppercase tracking-wider flex items-center gap-1.5">
          <Icon className="w-3 h-3" />
          {title}
          <span className="text-gray-600 font-mono">({items.length})</span>
        </span>
        {selectable.length > 0 && (
          <button
            onClick={() => onToggleAll(!allSelected)}
            className="text-[9px] text-teal-400 hover:text-teal-300 font-bold cursor-pointer font-sans"
          >
            {allSelected ? '取消全選' : '全選'}
          </button>
        )}
      </div>
      <div className="space-y-1.5">
        {items.map((c) => (
          <CandidateRow
            key={c.candidate_id}
            candidate={c}
            checked={selectedIds.includes(c.candidate_id)}
            onToggle={onToggle}
          />
        ))}
      </div>
    </div>
  );
};

// 本機資料夾掃描面板。
//
// 使用者用作業系統的檔案總管把訓練成果／資料集放進畫面上顯示的資料夾，再按下掃描。
// 刻意不做「選擇資料夾」的檔案對話框：瀏覽器基於安全機制永遠不會把使用者選取的
// 資料夾轉成後端可用的絕對路徑，固定目錄讓路徑完全不需要經過瀏覽器。
//
// 掃描只列出找到什麼、不載入任何東西；使用者勾選後按「載入選取項目」才會真正註冊。
const LocalLibraryPanel = () => {
  const {
    libraryPath,
    libraryExists,
    pathLoading,
    isScanning,
    isRegistering,
    candidates,
    selectedIds,
    lastScanMessage,
    lastRegisterMessage,
    scanError,
    scanLocalLibrary,
    toggleCandidate,
    setSelectionForKind,
    registerLocalLibrarySelection,
  } = useExperiment();

  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(libraryPath);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // 剪貼簿在非安全來源(http)下不可用，靜默忽略即可
    }
  };

  const models = candidates.filter((c) => c.kind === 'model');
  const datasets = candidates.filter((c) => c.kind === 'dataset');
  const busy = isScanning || isRegistering;

  return (
    <div className="glass-panel p-6 rounded-2xl border border-white/[0.06] shadow-xl space-y-5 relative overflow-hidden">
      <div className="absolute top-[-25%] right-[-15%] w-[120px] h-[120px] rounded-full bg-teal-500/5 blur-[40px] pointer-events-none"></div>

      <div className="flex items-center justify-between">
        <h3 className="text-xs font-bold text-white tracking-widest uppercase flex items-center gap-2">
          <FolderSearch className="w-4 h-4 text-teal-400" />
          本機資料夾
          <div className="relative group inline-block ml-1">
            <button
              className="cursor-help w-4 h-4 rounded-full bg-white/10 hover:bg-teal-500 hover:text-white text-[10px] text-gray-400 font-bold transition-all flex items-center justify-center border border-white/10 shadow-lg"
              aria-label="說明"
            >
              ?
            </button>
            <div className="absolute left-1/2 -translate-x-1/2 bottom-full mb-2 w-72 p-4 bg-slate-950/95 border border-white/10 rounded-2xl text-xs text-gray-300 shadow-2xl opacity-0 group-hover:opacity-100 pointer-events-none transition-all duration-300 z-50 leading-relaxed font-sans font-normal backdrop-blur-md text-left">
              把訓練成果（含 <span className="font-mono text-teal-400">weights/best.pt</span> 與{' '}
              <span className="font-mono text-teal-400">args.yaml</span>）、權重檔或資料集放進下方路徑，
              <span className="text-teal-400 font-bold">資料夾或 ZIP 皆可</span>。
              掃描後勾選要載入的項目即可使用，掃描結果保留至後端關閉為止。
            </div>
          </div>
        </h3>
        <span className="text-[10px] text-teal-400 font-mono font-bold bg-teal-500/10 px-2 py-0.5 rounded-md">
          No Upload
        </span>
      </div>

      {/* 路徑顯示 */}
      <div className="bg-slate-950/50 rounded-xl p-3.5 border border-white/5 space-y-2">
        <div className="flex items-center justify-between gap-2">
          <span className="text-gray-500 text-[10px] uppercase font-mono tracking-wider">
            掃描目標路徑
          </span>
          {libraryPath && (
            <button
              onClick={handleCopy}
              className="text-[9px] px-2 py-1 bg-white/5 hover:bg-teal-500 hover:text-white border border-white/10 rounded-md transition-all cursor-pointer font-bold font-sans flex items-center gap-1 flex-shrink-0"
              title="複製路徑"
            >
              {copied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
              {copied ? '已複製' : '複製'}
            </button>
          )}
        </div>
        <p
          className="text-[10px] text-gray-300 font-mono break-all leading-relaxed"
          title={libraryPath}
        >
          {pathLoading ? '讀取中...' : libraryPath || '（無法取得路徑）'}
        </p>
        {!pathLoading && !libraryExists && (
          <p className="text-[9px] text-amber-400 font-sans">
            此資料夾尚未建立，啟動後端時會自動建立
          </p>
        )}
      </div>

      {/* 掃描按鈕 */}
      <button
        onClick={scanLocalLibrary}
        disabled={busy || pathLoading}
        className={`w-full py-2.5 text-white font-extrabold text-xs rounded-xl transition-all shadow-lg flex items-center justify-center gap-2 font-sans ${
          busy || pathLoading
            ? 'bg-white/5 text-gray-500 cursor-not-allowed opacity-50'
            : 'bg-gradient-to-r from-teal-500 to-emerald-600 hover:from-teal-600 hover:to-emerald-700 hover:shadow-teal-500/20 cursor-pointer'
        }`}
      >
        {isScanning ? (
          <>
            <RefreshCw className="w-3.5 h-3.5 animate-spin" />
            掃描中...
          </>
        ) : (
          <>
            <FolderSearch className="w-3.5 h-3.5" />
            {candidates.length > 0 ? '重新掃描' : '掃描本機資料夾'}
          </>
        )}
      </button>

      {/* 掃描摘要 */}
      {lastScanMessage && !scanError && (
        <div className="p-3 bg-teal-500/10 border border-teal-500/30 text-teal-300 rounded-xl text-[11px] flex items-start gap-2">
          <CheckCircle2 className="w-4 h-4 flex-shrink-0 mt-0.5" />
          <span className="break-words">{lastScanMessage}</span>
        </div>
      )}

      {/* 候選清單 */}
      {candidates.length > 0 && (
        <div className="space-y-4 max-h-[420px] overflow-y-auto pr-1">
          <CandidateGroup
            title="權重列表"
            Icon={Box}
            items={models}
            selectedIds={selectedIds}
            onToggle={toggleCandidate}
            onToggleAll={(checked) => setSelectionForKind('model', checked)}
          />
          <CandidateGroup
            title="資料集列表"
            Icon={Database}
            items={datasets}
            selectedIds={selectedIds}
            onToggle={toggleCandidate}
            onToggleAll={(checked) => setSelectionForKind('dataset', checked)}
          />
        </div>
      )}

      {/* 載入按鈕 */}
      {candidates.length > 0 && (
        <button
          onClick={registerLocalLibrarySelection}
          disabled={busy || selectedIds.length === 0}
          className={`w-full py-2.5 text-white font-extrabold text-xs rounded-xl transition-all shadow-lg flex items-center justify-center gap-2 font-sans ${
            busy || selectedIds.length === 0
              ? 'bg-white/5 text-gray-500 cursor-not-allowed opacity-50'
              : 'bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700 hover:shadow-indigo-500/20 cursor-pointer'
          }`}
        >
          {isRegistering ? (
            <>
              <RefreshCw className="w-3.5 h-3.5 animate-spin" />
              載入中...
            </>
          ) : (
            <>
              <Download className="w-3.5 h-3.5" />
              載入選取項目（{selectedIds.length}）
            </>
          )}
        </button>
      )}

      {/* 載入結果 */}
      {lastRegisterMessage && !scanError && (
        <div className="p-3 bg-indigo-500/10 border border-indigo-500/30 text-indigo-300 rounded-xl text-[11px] flex items-start gap-2">
          <CheckCircle2 className="w-4 h-4 flex-shrink-0 mt-0.5" />
          <span className="break-words">{lastRegisterMessage}</span>
        </div>
      )}

      {scanError && (
        <div className="p-3 bg-red-500/10 border border-red-500/30 text-red-400 rounded-xl text-[11px] flex items-start gap-2">
          <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
          <span className="break-words">{scanError}</span>
        </div>
      )}
    </div>
  );
};

export default LocalLibraryPanel;
