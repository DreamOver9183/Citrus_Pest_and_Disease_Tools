import React, { useEffect, useState, useRef } from 'react';

const Lightbox = ({ src, onClose }) => {
  const [scale, setScale] = useState(1);
  const [position, setPosition] = useState({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 });
  
  const imgRef = useRef(null);

  // 1. 滾動穿透鎖定 & 鍵盤 ESC 關閉
  useEffect(() => {
    document.body.style.overflow = 'hidden';
    const handleEsc = (e) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleEsc);
    return () => {
      document.body.style.overflow = 'unset';
      window.removeEventListener('keydown', handleEsc);
    };
  }, [onClose]);

  // 2. 計算拖拽邊界，防止圖片飛到視窗外
  const handleMouseDown = (e) => {
    e.preventDefault();
    setIsDragging(true);
    setDragStart({ x: e.clientX - position.x, y: e.clientY - position.y });
  };

  const handleMouseMove = (e) => {
    if (!isDragging) return;
    
    let newX = e.clientX - dragStart.x;
    let newY = e.clientY - dragStart.y;

    // 基於縮放比例計算位移限界 (scale 越大，可拖曳範圍越大)
    const limitX = Math.max(0, (scale - 1) * 350);
    const limitY = Math.max(0, (scale - 1) * 250);
    
    // 箝制座標
    newX = Math.max(-limitX, Math.min(limitX, newX));
    newY = Math.max(-limitY, Math.min(limitY, newY));

    setPosition({ x: newX, y: newY });
  };

  const handleMouseUp = () => {
    setIsDragging(false);
  };

  // 處理滑鼠滾輪縮放
  const handleWheel = (e) => {
    const factor = e.deltaY > 0 ? -0.25 : 0.25;
    const nextScale = Math.max(1, Math.min(5, scale + factor));
    setScale(nextScale);
    
    // 縮回 1.0 時，歸位圖片到中心點
    if (nextScale === 1) {
      setPosition({ x: 0, y: 0 });
    }
  };

  return (
    <div 
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/95 backdrop-blur-md select-none"
      onClick={onClose}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
    >
      {/* 關閉按鈕 - 視窗固定與防干擾樣式 */}
      <button 
        className="fixed top-6 right-6 z-[60] text-gray-400 bg-white/5 p-3 rounded-full hover:bg-red-500/80 hover:text-white transition-all cursor-pointer border border-white/10 shadow-lg"
        onClick={(e) => {
          e.stopPropagation();
          onClose();
        }}
        title="關閉 (Esc)"
      >
        <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>

      {/* 放大說明提示 */}
      <div className="fixed bottom-6 left-1/2 -translate-x-1/2 bg-black/60 px-4 py-2 rounded-full border border-white/10 text-xs text-gray-400 pointer-events-none z-[60]">
        滑鼠滾輪可無級縮放，按住滑鼠左鍵可拖動平移圖片以檢視病徵細節
      </div>

      {/* 拖曳與縮放主體 */}
      <div 
        className="relative max-w-5xl max-h-[85vh] overflow-visible"
        onClick={(e) => e.stopPropagation()}
      >
        <img
          ref={imgRef}
          src={src}
          alt="Zoomed Details"
          className="rounded-lg shadow-2xl transition-transform duration-100 ease-out cursor-grab active:cursor-grabbing max-w-full max-h-[80vh] object-contain"
          style={{
            transform: `scale(${scale}) translate(${position.x / scale}px, ${position.y / scale}px)`,
          }}
          onMouseDown={handleMouseDown}
          onWheel={handleWheel}
        />
      </div>
    </div>
  );
};

export default Lightbox;
