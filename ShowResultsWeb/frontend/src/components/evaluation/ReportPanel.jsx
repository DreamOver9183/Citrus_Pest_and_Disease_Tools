import React, { useState } from 'react';
import { FileText, Download, ExternalLink, Trash2, RefreshCw, Printer } from 'lucide-react';
import { useExperiment } from '../../context/ExperimentContext';

// 成果報告面板。
//
// 產出是單一自足的 HTML（圖表以 base64 內嵌），因此可離線開啟、可直接寄出。
// PDF 走瀏覽器列印——這件事必須在介面上講清楚，否則使用者會一直找一顆不存在的
// 「匯出 PDF」按鈕。
const ReportPanel = ({ selectedIds, comparableHint }) => {
  const {
    evalReports,
    generateReport,
    deleteReport,
    isGeneratingReport,
  } = useExperiment();

  const [title, setTitle] = useState('');

  const handleGenerate = async () => {
    const report = await generateReport(selectedIds, title.trim() || null);
    if (report) setTitle('');
  };

  return (
    <div className="glass-panel p-6 rounded-2xl border border-white/[0.06] shadow-xl space-y-4">
      <h3 className="text-xs font-bold text-white tracking-widest uppercase flex items-center gap-2">
        <FileText className="w-4 h-4 text-violet-400" />
        成果報告
      </h3>

      <div className="space-y-2">
        <input
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="報告標題（可留空自動命名）"
          className="w-full bg-slate-950/60 border border-white/10 rounded-lg px-3 py-2 text-xs text-white placeholder-gray-600 focus:outline-none focus:border-violet-500/50"
        />

        <p className="text-[10px] text-gray-500 leading-relaxed">
          已選取 <b className="text-violet-300">{selectedIds.length}</b> 筆評估結果。
          {selectedIds.length > 1 && comparableHint}
        </p>

        <button
          onClick={handleGenerate}
          disabled={selectedIds.length === 0 || isGeneratingReport}
          className={`w-full py-2.5 text-white font-extrabold text-xs rounded-xl transition-all shadow-lg flex items-center justify-center gap-2 ${
            selectedIds.length === 0 || isGeneratingReport
              ? 'bg-white/5 text-gray-500 cursor-not-allowed opacity-50'
              : 'bg-gradient-to-r from-violet-500 to-purple-600 hover:from-violet-600 hover:to-purple-700 hover:shadow-violet-500/20 cursor-pointer'
          }`}
        >
          {isGeneratingReport ? (
            <>
              <RefreshCw className="w-3.5 h-3.5 animate-spin" /> 產生中...
            </>
          ) : (
            <>
              <FileText className="w-3.5 h-3.5" /> 產生報告
            </>
          )}
        </button>

        <p className="text-[9px] text-gray-600 leading-relaxed flex items-start gap-1.5">
          <Printer className="w-3 h-3 flex-shrink-0 mt-0.5" />
          報告是單一自足的 HTML，離線可讀。需要 PDF 時在瀏覽器開啟後按 Ctrl+P 另存即可。
        </p>
      </div>

      {evalReports.length > 0 && (
        <div className="space-y-2 pt-1">
          <p className="text-[10px] text-gray-500 uppercase font-mono tracking-wider">已產生的報告</p>
          {evalReports.map((report) => (
            <div
              key={report.report_id}
              className="bg-slate-950/50 rounded-xl p-3 border border-white/5 space-y-1.5"
            >
              <p className="text-[11px] font-bold text-white break-words">{report.title}</p>
              <p className="text-[9px] text-gray-500 font-mono">
                {report.created_at?.slice(0, 19).replace('T', ' ')} · {report.size_kb} KB ·
                {' '}{report.job_ids?.length} 筆評估
              </p>
              <div className="flex items-center gap-1.5 pt-0.5">
                <a
                  href={`/api/reports/${report.report_id}/view`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[9px] px-2 py-1 bg-white/5 hover:bg-violet-500 hover:text-white border border-white/10 rounded-md transition-all cursor-pointer font-bold flex items-center gap-1"
                >
                  <ExternalLink className="w-3 h-3" /> 開啟
                </a>
                <a
                  href={report.download_url}
                  className="text-[9px] px-2 py-1 bg-white/5 hover:bg-violet-500 hover:text-white border border-white/10 rounded-md transition-all cursor-pointer font-bold flex items-center gap-1"
                >
                  <Download className="w-3 h-3" /> 下載
                </a>
                <button
                  onClick={() => deleteReport(report.report_id)}
                  className="ml-auto text-gray-600 hover:text-red-400 transition-colors cursor-pointer"
                  title="刪除報告"
                >
                  <Trash2 className="w-3 h-3" />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default ReportPanel;
