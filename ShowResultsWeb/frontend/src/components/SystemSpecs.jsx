import React, { useState, useEffect } from 'react';
import { useDropzone } from 'react-dropzone';
import { apiUpload, errorMessage } from '../api/client';
import { useExperiment } from '../context/ExperimentContext';
import LocalLibraryPanel from './system-specs/LocalLibraryPanel';
import ModelRow from './system-specs/ModelRow';
import SettingsDrawer from './system-specs/SettingsDrawer';
import { Archive, Cpu, AlertCircle, RefreshCw, Server, Monitor, Settings2, Check } from 'lucide-react';

// 「模型與裝置」分頁。
//
// 版面依採用決策走 1a：**單欄主軸 ＋ 設定抽屜**。設定（推論裝置、本機資料夾、
// 上傳）在一次使用裡通常只做一次，卻原本常駐左欄佔掉三分之一版面；收進抽屜後
// 主畫面只剩「你手上有哪些模型」。模型清單是可展開的列而不是可排序的表——後者
// 會與權重登錄簿的 WeightTable 重複，而 MAX_SESSIONS 只有 3。
// 完整脈絡見 docs/ui_redesign/adoption-notes.md 的 B2。
const SystemSpecs = () => {
  const {
    sessions,
    sessionCount,
    setSessions,
    updateSessionName,
    deleteSession,
    availableDevices,
    currentDevice,
    currentDeviceLabel,
    deviceLoading,
    switchDevice,
    // 抽屜關著時也要讓使用者知道裡面有事情在發生／等著處理
    isScanning,
    isRegistering,
    selectedIds,
  } = useExperiment();

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  // 本地暫存的自訂名稱，解決輸入時畫面重新渲染的卡頓問題
  const [localNames, setLocalNames] = useState({});

  // 監聽 sessions 變更，同步本地自訂名稱
  useEffect(() => {
    const names = {};
    Object.keys(sessions).forEach(id => {
      names[id] = sessions[id].custom_name;
    });
    setLocalNames(names);
  }, [sessions]);

  const handleNameChange = (id, val) => {
    setLocalNames(prev => ({
      ...prev,
      [id]: val
    }));
  };

  const handleNameBlur = async (id) => {
    const currentVal = localNames[id];
    if (currentVal && currentVal.trim() !== '') {
      await updateSessionName(id, currentVal.trim());
    }
  };

  // 支援的模型檔案格式
  const SUPPORTED_EXTENSIONS = ['.zip', '.pt', '.pth', '.onnx', '.tflite', '.engine', '.torchscript'];

  // 處理模型上傳 (支援 ZIP 與單一權重檔案)
  const onDrop = async (acceptedFiles) => {
    if (acceptedFiles.length === 0) return;

    const modelFiles = acceptedFiles.filter(file => {
      const ext = '.' + file.name.split('.').pop().toLowerCase();
      return SUPPORTED_EXTENSIONS.includes(ext);
    });
    if (modelFiles.length === 0) {
      setError(`不支援的檔案格式。支援格式：${SUPPORTED_EXTENSIONS.join(', ')}`);
      return;
    }

    setLoading(true);
    setError(null);

    let currentSessions = { ...sessions };
    let successCount = 0;

    for (let i = 0; i < modelFiles.length; i++) {
      const file = modelFiles[i];
      const currentCount = Object.keys(currentSessions).length;
      if (currentCount >= 3) {
        setError(prev => prev ? `${prev} | 已達模型載入上限 (3/3)` : '已達模型載入上限 (3/3)');
        break;
      }

      const formData = new FormData();
      formData.append('file', file);

      try {
        const data = await apiUpload('/upload-model', formData);
        currentSessions = data.sessions;
        setSessions(currentSessions);
        successCount++;
      } catch (err) {
        console.error(err);
        const detail = `檔案 ${file.name} 載入失敗: ${errorMessage(err)}`;
        setError(prev => prev ? `${prev} | ${detail}` : detail);
      }
    }

    setLoading(false);
  };

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    multiple: true,
    disabled: loading || sessionCount >= 3 || deviceLoading
  });

  // 抽屜關著時，掃描進行中或有勾選待載入的項目都要在觸發按鈕上留一個記號，
  // 否則使用者按下掃描、關掉抽屜之後就再也看不到結果。
  const settingsPending = isScanning || isRegistering || (selectedIds?.length ?? 0) > 0;

  const deviceOptions = [
    ...availableDevices.map((dev) => ({
      id: dev.id,
      label: dev.label,
      icon: dev.type === 'cuda' ? Server : Cpu,
      details: dev.details,
    })),
    { id: 'auto', label: '自動調配最佳設備', icon: Monitor, details: null },
  ];

  // 選取狀態只反映「使用者選了什麼」，auto 與實體裝置互斥。
  //
  // 舊版把「auto 時第一個實體裝置也算 selected」寫進同一個判斷式，於是 auto 之下
  // 會有兩個項目同時亮起。舊版面把 auto 拆成獨立按鈕所以不明顯，收進同一個清單後
  // 就變成兩個打勾。實際跑在哪個裝置上改用下面的 autoResolvedId 標成提示，
  // 那是資訊，不是選取狀態。
  const isDeviceSelected = (id) =>
    id === 'auto' ? currentDevice === 'auto' : id === currentDevice;

  // auto 實際會落在清單第一個裝置上——後端沒有回一個明確的 auto 項目時才成立
  const autoResolvedId =
    currentDevice === 'auto' && !availableDevices.find((d) => d.id === 'auto')
      ? availableDevices[0]?.id
      : null;

  return (
    <div className="max-w-5xl mx-auto px-6 py-8 text-left">
      <header className="flex items-end justify-between gap-4 flex-wrap mb-6">
        <div>
          <h2 className="text-lg font-medium text-ink">已載入的模型</h2>
          <p className="text-sm text-ds-neutral-500 mt-1 tabular-nums">
            {sessionCount}／3 個插槽
          </p>
        </div>

        <button
          onClick={() => setDrawerOpen(true)}
          className="relative flex items-center gap-2 px-4 py-2 rounded-ds border border-accent text-accent text-sm hover:bg-accent/10 active:bg-accent/20 transition-colors cursor-pointer focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2"
        >
          <Settings2 className="w-4 h-4" />
          設定
          {settingsPending && (
            <span
              className="absolute -top-1 -right-1 w-2 h-2 rounded-full bg-accent"
              aria-label="設定中有待處理的項目"
            />
          )}
        </button>
      </header>

      {error && (
        <div className="mb-5 flex items-start gap-2 px-4 py-3 rounded-ds border border-danger-700 bg-danger-900/40 text-danger-300 text-sm">
          <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {sessionCount === 0 ? (
        <div className="border border-dashed border-ds-neutral-800 rounded-ds px-6 py-16 text-center">
          <Archive className="w-8 h-8 text-ds-neutral-700 mx-auto mb-4" />
          <p className="text-sm text-ink">還沒有載入任何模型</p>
          <p className="text-sm text-ds-neutral-500 mt-1.5 max-w-sm mx-auto leading-relaxed">
            從「設定」裡掃描本機資料夾，或直接拖入權重檔與 ZIP 訓練成果。
          </p>
          <button
            onClick={() => setDrawerOpen(true)}
            className="mt-5 px-4 py-2 rounded-ds border border-accent text-accent text-sm hover:bg-accent/10 transition-colors cursor-pointer focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2"
          >
            開啟設定
          </button>
        </div>
      ) : (
        <div className="space-y-2">
          {Object.keys(sessions).map((id) => (
            <ModelRow
              key={id}
              session={sessions[id]}
              name={localNames[id]}
              onNameChange={(val) => handleNameChange(id, val)}
              onNameCommit={() => handleNameBlur(id)}
              onDelete={() => deleteSession(id)}
            />
          ))}
        </div>
      )}

      <SettingsDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)}>
        {/* --- 上傳權重 --- */}
        <section>
          <h3 className="text-sm font-medium text-ink mb-1">上傳權重</h3>
          <p className="text-xs text-ds-neutral-500 mb-3 leading-relaxed">
            支援 .pt (YOLO)、.pth (SSDLite)、.onnx 與 ZIP 訓練成果。
            檔名含 small 視為 SSDLite-Small 架構。
          </p>

          {sessionCount < 3 ? (
            <div
              {...getRootProps()}
              className={`px-4 py-8 rounded-ds border border-dashed text-center cursor-pointer transition-colors ${
                isDragActive
                  ? 'border-accent bg-accent/10'
                  : 'border-ds-neutral-700 hover:border-accent/60'
              }`}
            >
              <input {...getInputProps()} />
              {loading ? (
                <div className="flex flex-col items-center gap-2">
                  <RefreshCw className="w-5 h-5 text-accent animate-spin" />
                  <p className="text-sm text-ink">正在解析訓練包規格…</p>
                </div>
              ) : (
                <div className="flex flex-col items-center gap-2">
                  <Archive className="w-5 h-5 text-ds-neutral-500" />
                  <p className="text-sm text-ink">拖放檔案，或點擊選擇</p>
                </div>
              )}
            </div>
          ) : (
            <div className="px-4 py-6 rounded-ds border border-ds-neutral-800 text-center text-sm text-ds-neutral-500 leading-relaxed">
              已達載入上限（3／3）。
              <br />
              請先移除既有模型再載入新權重。
            </div>
          )}
        </section>

        {/* --- 本機資料夾 --- */}
        <LocalLibraryPanel />

        {/* --- 推論裝置 --- */}
        <section>
          <div className="flex items-baseline justify-between gap-3 mb-3">
            <h3 className="text-sm font-medium text-ink">推論裝置</h3>
            <span className="text-xs text-ds-neutral-500">{currentDeviceLabel}</span>
          </div>

          <div className="space-y-1.5">
            {deviceOptions.map((dev) => {
              const selected = isDeviceSelected(dev.id);
              const Icon = dev.icon;
              return (
                <button
                  key={dev.id}
                  onClick={() => !selected && !deviceLoading && switchDevice(dev.id)}
                  disabled={deviceLoading}
                  className={`w-full text-left px-3 py-2.5 rounded-ds border transition-colors disabled:opacity-45 disabled:cursor-not-allowed focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2 ${
                    selected
                      ? 'border-accent bg-accent/10 cursor-default'
                      : 'border-ds-neutral-800 hover:border-ds-neutral-700 cursor-pointer'
                  }`}
                >
                  <span className="flex items-center justify-between gap-2">
                    <span className="flex items-center gap-2.5 min-w-0">
                      <Icon
                        className={`w-4 h-4 flex-shrink-0 ${
                          selected ? 'text-accent' : 'text-ds-neutral-500'
                        }`}
                      />
                      <span className={`text-sm truncate ${selected ? 'text-ink' : 'text-ds-neutral-400'}`}>
                        {dev.label}
                      </span>
                    </span>
                    <span className="flex items-center gap-2 flex-shrink-0">
                      {autoResolvedId === dev.id && (
                        <span className="text-[10px] text-ds-neutral-600">自動選用</span>
                      )}
                      {selected && <Check className="w-4 h-4 text-accent" />}
                    </span>
                  </span>

                  {dev.details && Object.keys(dev.details).length > 0 && (
                    <span className="flex flex-wrap gap-x-4 gap-y-0.5 mt-1.5 pl-6 text-xs text-ds-neutral-600 tabular-nums">
                      {dev.details.vram_total_gb && (
                        <span>VRAM {dev.details.vram_allocated_gb} / {dev.details.vram_total_gb} GB</span>
                      )}
                      {dev.details.compute_capability && (
                        <span>Compute {dev.details.compute_capability}</span>
                      )}
                      {dev.details.ram_total_gb && (
                        <span>RAM {dev.details.ram_used_gb} / {dev.details.ram_total_gb} GB</span>
                      )}
                    </span>
                  )}
                </button>
              );
            })}
          </div>

          {deviceLoading && (
            <p className="flex items-center gap-2 mt-3 text-xs text-accent-300">
              <RefreshCw className="w-3.5 h-3.5 animate-spin flex-shrink-0" />
              切換設備中，系統重載約需 5–15 秒…
            </p>
          )}
        </section>
      </SettingsDrawer>
    </div>
  );
};

export default SystemSpecs;
