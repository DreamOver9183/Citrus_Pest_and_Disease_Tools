import React, { useState, useEffect } from 'react';
import { useDropzone } from 'react-dropzone';
import axios from 'axios';
import { useExperiment } from '../context/ExperimentContext';
import ExportPanel from './system-specs/ExportPanel';
import { Archive, Cpu, CheckCircle2, AlertCircle, RefreshCw, Trash2, Edit2, Server, Monitor, Sparkles, Database, FileCode, HardDrive } from 'lucide-react';

const SystemSpecs = () => {
  const { 
    sessions, 
    sessionCount, 
    setSessions, 
    updateSessionName, 
    deleteSession, 
    loading: contextLoading,
    availableDevices,
    currentDevice,
    currentDeviceLabel,
    deviceLoading,
    switchDevice
  } = useExperiment();

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  
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
        const res = await axios.post('/api/upload-model', formData, {
          headers: { 'Content-Type': 'multipart/form-data' }
        });

        if (res.data.status === 'success') {
          currentSessions = res.data.sessions;
          setSessions(currentSessions);
          successCount++;
        } else {
          setError(prev => prev ? `${prev} | 檔案 ${file.name} 載入失敗: ${res.data.message}` : `檔案 ${file.name} 載入失敗: ${res.data.message}`);
        }
      } catch (err) {
        console.error(err);
        setError(prev => prev ? `${prev} | 連線後端 API 逾時，請檢查 FastAPI 服務` : `連線後端 API 逾時，請檢查 FastAPI 服務`);
      }
    }

    setLoading(false);
  };

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    multiple: true,
    disabled: loading || sessionCount >= 3 || deviceLoading
  });

  return (
    <div className="max-w-7xl mx-auto px-2 py-4 space-y-8 animate-fadeIn text-left">
      
      {/* 左右分欄版面 (Bento Grid) */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 items-start">
        
        {/* 左側：上傳模型與推論裝置設定 */}
        <div className="lg:col-span-1 space-y-6">
          
          {/* 上傳面板 */}
          <div className="glass-panel p-6 rounded-2xl border border-white/[0.06] shadow-xl space-y-5">
            <div className="flex items-center justify-between">
              <h3 className="text-xs font-bold text-white tracking-widest uppercase flex items-center gap-2">
                <HardDrive className="w-4 h-4 text-orange-400" />
                載入模型權重
                <div className="relative group inline-block ml-1">
                  <button className="cursor-help w-4 h-4 rounded-full bg-white/10 hover:bg-orange-500 hover:text-white text-[10px] text-gray-400 font-bold transition-all flex items-center justify-center border border-white/10 shadow-lg" aria-label="頁面說明">
                    ?
                  </button>
                  <div className="absolute left-1/2 -translate-x-1/2 bottom-full mb-2 w-72 p-4 bg-slate-950/95 border border-white/10 rounded-2xl text-xs text-gray-300 shadow-2xl opacity-0 group-hover:opacity-100 pointer-events-none transition-all duration-300 z-50 leading-relaxed font-sans font-normal backdrop-blur-md">
                    支援 YOLO (.pt/.zip) 與 SSDLite-MobileNetV3 (.pth) 兩種架構，上傳後系統將自動辨識並展示模型資訊。
                  </div>
                </div>
              </h3>
              <span className="text-[10px] text-orange-400 font-mono font-bold bg-orange-500/10 px-2 py-0.5 rounded-md">
                Slot Available
              </span>
            </div>

            {/* 上傳元件 */}
            {sessionCount < 3 ? (
              <div
                {...getRootProps()}
                className={`p-6 rounded-xl border-2 border-dashed text-center cursor-pointer transition-all duration-300 relative flex flex-col items-center justify-center min-h-[190px] ${
                  isDragActive
                    ? 'border-orange-500 bg-orange-500/5 shadow-[0_0_20px_rgba(249,115,22,0.15)]'
                    : 'border-white/10 hover:border-orange-500/40 hover:bg-orange-500/[0.01]'
                }`}
              >
                <input {...getInputProps()} />
                
                {loading ? (
                  <div className="space-y-3">
                    <div className="relative flex items-center justify-center">
                      <RefreshCw className="w-10 h-10 text-orange-400 animate-spin" />
                      <Sparkles className="absolute w-4 h-4 text-amber-300 animate-pulse" />
                    </div>
                    <p className="text-xs text-white font-bold animate-pulse">正在解析訓練包規格...</p>
                    <p className="text-[10px] text-gray-500 font-mono">Unzipping & Aligning Class Weights</p>
                  </div>
                ) : (
                  <div className="space-y-4">
                    <div className="p-3 bg-white/5 rounded-2xl w-12 h-12 mx-auto flex items-center justify-center">
                      <Archive className="w-6 h-6 text-orange-400" />
                    </div>
                    <div className="space-y-1">
                      <p className="text-xs text-white font-bold">拖放模型檔案或 ZIP 訓練成果</p>
                      <p className="text-[10px] text-gray-400 leading-relaxed max-w-[200px] mx-auto">
                        支援 .pt (YOLO), .pth (SSDLite), .onnx, .zip<br/>
                        * 檔名含 small 視為 SSDLite-Small 架構
                      </p>
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <div className="p-8 rounded-xl border border-white/5 bg-slate-950/40 text-center text-gray-500 text-xs leading-relaxed">
                <Database className="w-8 h-8 text-gray-600 mx-auto mb-2" />
                已達模型載入上限 (3/3)<br />
                請先移除右側模型以重新載入新權重
              </div>
            )}

            {error && (
              <div className="p-3 bg-red-500/10 border border-red-500/30 text-red-400 rounded-xl text-[11px] flex items-start gap-2 animate-shake">
                <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
                <span>{error}</span>
              </div>
            )}

            {/* 進度條 */}
            <div className="bg-slate-950/50 rounded-xl p-4 border border-white/5 space-y-3 text-xs">
              <div className="flex justify-between items-center">
                <span className="text-gray-400 font-medium">模型庫使用率</span>
                <span className="text-white font-mono font-bold">{sessionCount} / 3 Sessions</span>
              </div>
              <div className="w-full bg-white/5 h-2 rounded-full overflow-hidden border border-white/5">
                <div 
                  className="bg-gradient-to-r from-orange-500 to-amber-400 h-full transition-all duration-500 rounded-full"
                  style={{ width: `${(sessionCount / 3) * 100}%` }}
                ></div>
              </div>
            </div>
          </div>

          {/* 裝置選擇器面板 */}
          <div className="glass-panel p-6 rounded-2xl border border-white/[0.06] shadow-xl space-y-4">
            <div className="flex items-center justify-between border-b border-white/5 pb-3">
              <h3 className="text-xs font-bold text-white tracking-widest uppercase flex items-center gap-2">
                <Monitor className="w-4 h-4 text-indigo-400" />
                推論設備配置
              </h3>
              <span className="text-[10px] bg-indigo-500/15 text-indigo-300 border border-indigo-500/30 px-2 py-0.5 rounded-md font-mono">
                {currentDeviceLabel}
              </span>
            </div>

            <div className="space-y-3">
              {availableDevices.map(dev => {
                const isSelected = dev.id === currentDevice || (currentDevice === 'auto' && dev.id === availableDevices[0]?.id && !availableDevices.find(d => d.id === 'auto'));
                
                return (
                  <button
                    key={dev.id}
                    onClick={() => {
                      if (!isSelected && !deviceLoading) {
                        switchDevice(dev.id);
                      }
                    }}
                    disabled={deviceLoading}
                    className={`w-full text-left p-3.5 rounded-xl border transition-all flex flex-col gap-2 ${
                      isSelected 
                        ? 'bg-gradient-to-r from-orange-500/10 to-amber-500/5 border-orange-500/40 shadow-[0_0_15px_rgba(249,115,22,0.08)]' 
                        : 'bg-slate-950/40 border-white/5 hover:border-white/20 hover:bg-slate-900/40 cursor-pointer'
                    } ${deviceLoading ? 'opacity-50 cursor-not-allowed' : ''}`}
                  >
                    <div className="flex items-center justify-between">
                      <span className={`text-xs font-bold flex items-center gap-2.5 ${isSelected ? 'text-orange-400' : 'text-gray-300'}`}>
                        {dev.type === 'cuda' ? <Server className="w-4 h-4" /> : <Cpu className="w-4 h-4" />}
                        {dev.label}
                      </span>
                      {isSelected && <CheckCircle2 className="w-4 h-4 text-orange-500" />}
                    </div>
                    
                    {dev.details && Object.keys(dev.details).length > 0 && (
                      <div className="text-[10px] text-gray-500 font-mono grid grid-cols-2 gap-x-2 gap-y-1 mt-1 pl-6">
                        {dev.details.vram_total_gb && <span>VRAM: {dev.details.vram_allocated_gb}G / {dev.details.vram_total_gb}G</span>}
                        {dev.details.compute_capability && <span>Compute Cap: {dev.details.compute_capability}</span>}
                        {dev.details.ram_total_gb && <span>RAM: {dev.details.ram_used_gb}G / {dev.details.ram_total_gb}G</span>}
                      </div>
                    )}
                  </button>
                );
              })}

              <button
                onClick={() => !deviceLoading && switchDevice('auto')}
                disabled={deviceLoading}
                className={`w-full text-left p-3.5 rounded-xl border transition-all flex flex-col gap-2 ${
                  currentDevice === 'auto' 
                    ? 'bg-gradient-to-r from-orange-500/10 to-amber-500/5 border-orange-500/40 shadow-[0_0_15px_rgba(249,115,22,0.08)]' 
                    : 'bg-slate-950/40 border-white/5 hover:border-white/20 hover:bg-slate-900/40 cursor-pointer'
                } ${deviceLoading ? 'opacity-50 cursor-not-allowed' : ''}`}
              >
                <div className="flex items-center justify-between">
                  <span className={`text-xs font-bold flex items-center gap-2.5 ${currentDevice === 'auto' ? 'text-orange-400' : 'text-gray-300'}`}>
                    <Monitor className="w-4 h-4" />
                    自動調配最佳設備 (Auto)
                  </span>
                  {currentDevice === 'auto' && <CheckCircle2 className="w-4 h-4 text-orange-500" />}
                </div>
              </button>
            </div>
            
            {deviceLoading && (
              <div className="flex items-center gap-2.5 text-[10px] text-orange-400 bg-orange-500/10 p-3 rounded-xl border border-orange-500/25 animate-pulse font-mono">
                <RefreshCw className="w-3.5 h-3.5 animate-spin flex-shrink-0" />
                <span>切換設備中，系統重載約需 5-15 秒...</span>
              </div>
            )}
          </div>
        </div>

        {/* 右側：動態迭代的 Session 卡片清單 */}
        <div className="lg:col-span-2 space-y-6">
          {sessionCount === 0 ? (
            <div className="glass-panel p-16 rounded-3xl border border-white/[0.06] text-center text-gray-500 flex flex-col items-center justify-center gap-4 shadow-xl">
              <Archive className="w-12 h-12 text-gray-600 animate-pulse" />
              <div className="space-y-2 max-w-sm flex flex-col items-center">
                <p className="text-white text-sm font-bold">目前無載入的模型實驗</p>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-gray-400">請自左側拖入權重或成果包。</span>
                  <div className="relative group inline-block">
                    <button className="cursor-help w-4 h-4 rounded-full bg-white/10 hover:bg-orange-500 hover:text-white text-[10px] text-gray-400 font-bold transition-all flex items-center justify-center border border-white/10" aria-label="載入說明">
                      ?
                    </button>
                    <div className="absolute left-1/2 -translate-x-1/2 bottom-full mb-2 w-64 p-3 bg-slate-950/95 border border-white/10 rounded-xl text-xs text-gray-300 shadow-2xl opacity-0 group-hover:opacity-100 pointer-events-none transition-all duration-300 z-50 leading-relaxed font-sans font-normal backdrop-blur-md text-left">
                      請在左側拖入 YOLO 訓練成果 ZIP 檔或權重。載入後，系統將自動解析消融特徵、訓練曲線與混淆矩陣。
                    </div>
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <div className="space-y-6">
              {Object.keys(sessions).map(id => {
                const spec = sessions[id];
                return (
                  <div
                    key={id}
                    className="glass-panel p-6 rounded-2xl border border-white/[0.06] space-y-5 hover:border-orange-500/25 transition-all flex flex-col justify-between shadow-xl relative overflow-hidden group"
                  >
                    <div className="absolute top-0 left-0 w-1.5 h-full bg-gradient-to-b from-orange-500 to-amber-400"></div>

                    {/* 卡片頭部：編輯名稱與檔案尺寸 */}
                    <div className="flex items-center justify-between gap-4 flex-wrap pb-3.5 border-b border-white/5 pl-2">
                      <div className="flex items-center gap-2.5 flex-1 min-w-[200px]">
                        <Edit2 className="w-3.5 h-3.5 text-orange-400 group-hover:scale-110 transition-transform" />
                        <input
                          type="text"
                          value={localNames[id] || ''}
                          onChange={(e) => handleNameChange(id, e.target.value)}
                          onBlur={() => handleNameBlur(id)}
                          onKeyDown={(e) => e.key === 'Enter' && handleNameBlur(id)}
                          className="bg-slate-950/60 border border-white/10 hover:border-orange-500/30 focus:border-orange-500 focus:outline-none focus:ring-1 focus:ring-orange-500/20 rounded-xl px-3.5 py-2 text-sm text-white font-bold w-full max-w-sm transition-all"
                          placeholder="請輸入此模型的顯示名稱"
                          title="點擊修改模型顯示名稱 (滑鼠移開或按 Enter 儲存)"
                        />
                      </div>
                      
                      <div className="flex items-center gap-4">
                        <span className="text-[10px] px-3 py-1 bg-white/5 text-gray-400 border border-white/5 rounded-full font-mono font-semibold">
                          {spec.weights_size_mb} MB
                        </span>
                        
                        <button
                          onClick={() => deleteSession(id)}
                          className="p-2 hover:bg-red-500/20 text-gray-500 hover:text-red-400 rounded-xl border border-transparent hover:border-red-500/30 transition-all cursor-pointer"
                          title="移除模型"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </div>
                    </div>

                    {/* 參數細節 (Grid) */}
                    <div className="grid grid-cols-1 md:grid-cols-4 gap-4 text-xs pl-2">
                      <div className="bg-slate-950/30 p-3.5 rounded-xl border border-white/5 space-y-1">
                        <span className="text-gray-500 text-[10px] uppercase font-mono tracking-wider block">來源格式檔案</span>
                        <div className="flex items-center gap-2">
                          {spec.format_label && (
                            <span className={`text-[9px] px-1.5 py-0.5 rounded font-bold border ${
                              spec.format_label === 'PyTorch' ? 'bg-red-500/15 text-red-400 border-red-500/25' :
                              spec.format_label === 'ONNX' ? 'bg-blue-500/15 text-blue-400 border-blue-500/25' :
                              spec.format_label === 'TFLite' ? 'bg-green-500/15 text-green-400 border-green-500/25' :
                              spec.format_label === 'TensorRT' ? 'bg-purple-500/15 text-purple-400 border-purple-500/25' :
                              spec.format_label.includes('SSDLite') ? 'bg-indigo-500/15 text-indigo-400 border-indigo-500/25' :
                              'bg-gray-500/15 text-gray-400 border-gray-500/25'
                            }`}>
                              {spec.format_label}
                            </span>
                          )}
                          <span className="text-gray-300 font-bold truncate text-[11px]" title={spec.zip_name}>
                            {spec.zip_name}
                          </span>
                        </div>
                      </div>
                      
                      <div className="bg-slate-950/30 p-3.5 rounded-xl border border-white/5 space-y-1">
                        <span className="text-gray-500 text-[10px] uppercase font-mono tracking-wider block">推論架構 (Arch)</span>
                        <span className="text-gray-200 font-mono font-bold block text-[11px] truncate" title={spec.model_arch}>
                          {spec.model_arch || 'yolo'}
                        </span>
                      </div>

                      <div className="bg-slate-950/30 p-3.5 rounded-xl border border-white/5 space-y-1">
                        <span className="text-gray-500 text-[10px] uppercase font-mono tracking-wider block">優化器與輪數</span>
                        <span className="text-gray-200 font-mono font-bold block text-[11px]">
                          {spec.optimizer || 'N/A'} (Epochs: {spec.epochs || 'N/A'})
                        </span>
                      </div>
                      
                      <div className="bg-slate-950/30 p-3.5 rounded-xl border border-white/5 space-y-1">
                        <span className="text-gray-500 text-[10px] uppercase font-mono tracking-wider block">最佳 mAP / mAP@50</span>
                        <span className="text-emerald-400 font-mono font-bold block text-[11px]">
                          {spec.metrics_summary?.mAP || 'N/A'} / {spec.metrics_summary?.mAP_50 || 'N/A'}
                        </span>
                      </div>
                    </div>

                    {/* 模型格式轉換與下載 */}
      <ExportPanel session={spec} />

      {/* 儲存路徑細節 (小字腳部) */}
                    <div className="text-[9px] font-mono text-gray-600 flex items-center gap-1.5 pt-1 pl-2">
                      <FileCode className="w-3.5 h-3.5 text-gray-500 flex-shrink-0" />
                      <span className="font-bold text-gray-500">實體工作區目錄:</span>
                      <span className="text-gray-400 truncate max-w-lg" title={spec.dir_path}>
                        {spec.dir_path}
                      </span>
                    </div>

                  </div>
                );
              })}
            </div>
          )}
        </div>

      </div>

    </div>
  );
};

export default SystemSpecs;
