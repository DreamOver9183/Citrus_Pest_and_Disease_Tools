import React, { useEffect, useRef } from 'react';
import { X } from 'lucide-react';

// 右側滑出的設定抽屜。
//
// 為什麼設定要收起來：裝置、本機資料夾、上傳這三件事在一次使用裡通常只做一次，
// 但它們原本常駐在左欄，佔掉三分之一的版面去顯示不會變的東西。收進抽屜之後，
// 主畫面只剩「你手上有哪些模型」這一條主軸。
//
// **開關狀態刻意放在呼叫端的元件本地 state，不放 context/hooks。**
// CLAUDE.md 硬規則 2 的判準是「切走分頁再切回來還需要在嗎」——抽屜是純呈現，
// 而真正需要存活的東西（掃描結果、勾選項目、進行中的請求）本來就在
// useLocalLibrary 這個耐久 hook 裡，不受抽屜開關影響。呼叫端另外在觸發按鈕上
// 顯示未處理事項的標記，使用者才不會因為抽屜關著而漏掉掃描結果。
const SettingsDrawer = ({ open, onClose, title = '設定', children }) => {
  const panelRef = useRef(null);

  // Esc 關閉。只在開啟時掛監聽，避免每個分頁都常駐一個 keydown handler。
  useEffect(() => {
    if (!open) return undefined;
    const onKeyDown = (e) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [open, onClose]);

  // 開啟時把焦點移進面板，鍵盤使用者才不會停在背後的頁面上。
  useEffect(() => {
    if (open && panelRef.current) panelRef.current.focus();
  }, [open]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />

      <aside
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        className="relative w-full max-w-md h-full overflow-y-auto bg-ground border-l border-ds-neutral-800 shadow-ds-lg focus:outline-none"
      >
        <div className="sticky top-0 z-10 flex items-center justify-between px-6 py-4 bg-ground border-b border-ds-neutral-800">
          <h2 className="text-sm font-medium text-ink">{title}</h2>
          <button
            onClick={onClose}
            className="p-1.5 rounded-ds-sm text-ds-neutral-500 hover:text-ink hover:bg-ds-neutral-800/60 transition-colors cursor-pointer focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2"
            aria-label="關閉設定"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="px-6 py-6 space-y-8">{children}</div>
      </aside>
    </div>
  );
};

export default SettingsDrawer;
