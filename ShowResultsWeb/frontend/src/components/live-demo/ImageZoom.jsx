import React, { useState, useRef } from 'react';

// 局部放大鏡元件 (Image Zoom Lens)
const ImageZoom = ({ src, alt, className }) => {
  const [showLens, setShowLens] = useState(false);
  const [lensStyle, setLensStyle] = useState({});
  const containerRef = useRef(null);

  const handleMouseMove = (e) => {
    const container = containerRef.current;
    if (!container) return;

    const rect = container.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;

    // 確保游標在圖片容器邊界內
    if (x < 0 || y < 0 || x > rect.width || y > rect.height) {
      setShowLens(false);
      return;
    }

    const zoomFactor = 2.5; // 放大倍率
    const lensSize = 130;  // 放大鏡尺寸

    // 計算背景影像偏移量
    const bgX = -x * zoomFactor + lensSize / 2;
    const bgY = -y * zoomFactor + lensSize / 2;

    setLensStyle({
      display: 'block',
      left: `${x - lensSize / 2}px`,
      top: `${y - lensSize / 2}px`,
      backgroundImage: `url(${src})`,
      backgroundSize: `${rect.width * zoomFactor}px ${rect.height * zoomFactor}px`,
      backgroundPosition: `${bgX}px ${bgY}px`,
      width: `${lensSize}px`,
      height: `${lensSize}px`,
      position: 'absolute',
      borderRadius: '50%',
      border: '3px solid #f97316', // 看板主題橘色系
      boxShadow: '0 10px 25px rgba(0, 0, 0, 0.5), inset 0 0 10px rgba(0, 0, 0, 0.2)',
      pointerEvents: 'none',
      zIndex: 10
    });
    setShowLens(true);
  };

  return (
    <div
      ref={containerRef}
      className="relative overflow-hidden w-full h-full flex items-center justify-center cursor-crosshair select-none"
      onMouseMove={handleMouseMove}
      onMouseEnter={() => setShowLens(true)}
      onMouseLeave={() => setShowLens(false)}
    >
      <img
        src={src}
        alt={alt}
        className={className}
        referrerPolicy="no-referrer"
      />
      {showLens && (
        <div style={lensStyle} />
      )}
    </div>
  );
};

export default ImageZoom;
