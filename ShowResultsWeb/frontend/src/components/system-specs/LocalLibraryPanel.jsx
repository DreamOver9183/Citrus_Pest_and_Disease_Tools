import React, { useState } from 'react';
import {
  FolderSearch, RefreshCw, Copy, Check, AlertCircle, CheckCircle2,
  Box, Database, Download, FileArchive, Folder, FileBox,
} from 'lucide-react';
import { useExperiment } from '../../context/ExperimentContext';

// 來源形態的視覺標示。Tailwind 需要完整靜態 class 字串，不能用拼接。
//
// 圖示一律走中性色：Nocturne 的原則是 accent 之外保持低彩度，而「這是資料夾還是
// ZIP」由圖示形狀就分得出來，不需要再用色相講一次。彩度留給真正帶語意的資料
// （偵測類別、圖表序列），見 docs/ui_redesign/adoption-notes.md 的 B1。
const SOURCE_META = {
  run_dir: { label: '資料夾', Icon: Folder },
  weight_file: { label: '權重檔', Icon: FileBox },
  zip_run: { label: 'ZIP', Icon: FileArchive },
  dataset_dir: { label: '資料夾', Icon: Folder },
  dataset_zip: { label: 'ZIP', Icon: FileArchive },
};

const CandidateRow = ({ candidate, checked, onToggle }) => {
  const meta = SOURCE_META[candidate.source_kind] || SOURCE_META.run_dir;
  const { Icon } = meta;
  const disabled = candidate.already_registered;

  return (
    <label
      className={`flex items-start gap-2.5 px-3 py-2 rounded-ds border transition-colors ${
        disabled
          ? 'border-ds-neutral-800 opacity-45 cursor-default'
          : checked
            ? 'border-accent bg-accent/10 cursor-pointer'
            : 'border-ds-neutral-800 hover:border-ds-neutral-700 cursor-pointer'
      }`}
    >
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={() => onToggle(candidate.candidate_id)}
        className="mt-0.5 w-3.5 h-3.5 flex-shrink-0 [accent-color:var(--color-accent)] cursor-pointer disabled:cursor-default"
      />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <Icon className="w-3 h-3 flex-shrink-0 text-ds-neutral-500" />
          <span className="text-sm text-ink truncate" title={candidate.name}>
            {candidate.name}
          </span>
          {disabled && (
            <span className="text-[10px] px-1.5 py-0.5 rounded-ds-sm border border-ds-neutral-700 text-ds-neutral-500 flex-shrink-0">
              已載入
            </span>
          )}
        </div>
        <p className="text-xs text-ds-neutral-600 truncate mt-0.5" title={candidate.rel_path}>
          {candidate.rel_path}
        </p>
        <p className="text-xs text-ds-neutral-500 mt-0.5 tabular-nums">
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
        <span className="text-xs text-ds-neutral-500 flex items-center gap-1.5">
          <Icon className="w-3 h-3" />
          {title}
          <span className="text-ds-neutral-600 tabular-nums">({items.length})</span>
        </span>
        {selectable.length > 0 && (
          <button
            onClick={() => onToggleAll(!allSelected)}
            className="text-xs text-accent hover:text-accent-300 cursor-pointer focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2 rounded-ds-sm"
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
//
// 這個元件現在住在設定抽屜裡，因此不自帶面板外框——外框由抽屜負責，
// 它只提供一個 section。
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
    <section>
      <h3 className="text-sm font-medium text-ink mb-1">本機資料夾</h3>
      <p className="text-xs text-ds-neutral-500 mb-3 leading-relaxed">
        把訓練成果（含 weights/best.pt 與 args.yaml）、權重檔或資料集放進下方路徑，
        資料夾或 ZIP 皆可。掃描只列出找到什麼，勾選後才會載入；結果保留至後端關閉為止。
      </p>

      {/* 路徑 */}
      <div className="rounded-ds border border-ds-neutral-800 px-3 py-2.5 mb-3">
        <div className="flex items-center justify-between gap-2 mb-1">
          <span className="text-[10px] text-ds-neutral-600">掃描目標路徑</span>
          {libraryPath && (
            <button
              onClick={handleCopy}
              className="flex items-center gap-1 text-xs text-ds-neutral-500 hover:text-accent transition-colors cursor-pointer flex-shrink-0 rounded-ds-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2"
              title="複製路徑"
            >
              {copied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
              {copied ? '已複製' : '複製'}
            </button>
          )}
        </div>
        <p className="text-xs text-ds-neutral-400 font-mono break-all leading-relaxed" title={libraryPath}>
          {pathLoading ? '讀取中…' : libraryPath || '（無法取得路徑）'}
        </p>
        {!pathLoading && !libraryExists && (
          <p className="text-xs text-warning-300 mt-1.5">
            此資料夾尚未建立，啟動後端時會自動建立
          </p>
        )}
      </div>

      <button
        onClick={scanLocalLibrary}
        disabled={busy || pathLoading}
        className="w-full flex items-center justify-center gap-2 py-2 rounded-ds border border-accent text-accent text-sm hover:bg-accent/10 active:bg-accent/20 transition-colors cursor-pointer disabled:opacity-45 disabled:cursor-not-allowed disabled:hover:bg-transparent focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2"
      >
        {isScanning ? (
          <>
            <RefreshCw className="w-3.5 h-3.5 animate-spin" />
            掃描中…
          </>
        ) : (
          <>
            <FolderSearch className="w-3.5 h-3.5" />
            {candidates.length > 0 ? '重新掃描' : '掃描本機資料夾'}
          </>
        )}
      </button>

      {lastScanMessage && !scanError && (
        <p className="flex items-start gap-2 mt-3 text-xs text-success-300">
          <CheckCircle2 className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
          <span className="break-words">{lastScanMessage}</span>
        </p>
      )}

      {candidates.length > 0 && (
        <div className="space-y-4 mt-4 max-h-[360px] overflow-y-auto pr-1">
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

      {candidates.length > 0 && (
        <button
          onClick={registerLocalLibrarySelection}
          disabled={busy || selectedIds.length === 0}
          className="w-full flex items-center justify-center gap-2 mt-3 py-2 rounded-ds border border-accent text-accent text-sm hover:bg-accent/10 active:bg-accent/20 transition-colors cursor-pointer disabled:opacity-45 disabled:cursor-not-allowed disabled:hover:bg-transparent focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2"
        >
          {isRegistering ? (
            <>
              <RefreshCw className="w-3.5 h-3.5 animate-spin" />
              載入中…
            </>
          ) : (
            <>
              <Download className="w-3.5 h-3.5" />
              載入選取項目（{selectedIds.length}）
            </>
          )}
        </button>
      )}

      {lastRegisterMessage && !scanError && (
        <p className="flex items-start gap-2 mt-3 text-xs text-success-300">
          <CheckCircle2 className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
          <span className="break-words">{lastRegisterMessage}</span>
        </p>
      )}

      {scanError && (
        <p className="flex items-start gap-2 mt-3 text-xs text-danger-300">
          <AlertCircle className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
          <span className="break-words">{scanError}</span>
        </p>
      )}
    </section>
  );
};

export default LocalLibraryPanel;
