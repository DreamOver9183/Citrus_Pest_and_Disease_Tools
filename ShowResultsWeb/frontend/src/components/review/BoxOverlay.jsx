import React from 'react';
import { BOX_STYLES, GT_DASH, shortClassName } from './reviewStyles';

// SVG 沒有便宜的量字方法；CJK 字寬約等於字級、ASCII 約 0.6 倍，畫標籤底色用估計值就夠了
const textWidth = (text, size) =>
  [...text].reduce((sum, ch) => sum + (ch.charCodeAt(0) > 0x2e80 ? size : size * 0.6), 0);

// 疊在影像上的框。
//
// 用 SVG 而不是在伺服器端把框燒進圖片：圖層切換與門檻調整都只是重畫，不必重新產圖。
// viewBox 用影像原始（已依 EXIF 轉正的）寬高，呼叫端負責讓容器的長寬比與影像一致，
// 座標就能直接用後端回傳的像素值。
//
// 實線 = 預測、虛線 = 標註；layer 為 'gt' / 'pred' / 'both'。
const BoxOverlay = ({ item, classNames, layer = 'both', showLabels = false }) => {
  const { width, height } = item;
  const nameOf = (cls) => shortClassName(classNames?.[cls] ?? String(cls));
  const gtById = Object.fromEntries(item.gt.map((g) => [g.id, g]));

  const shapes = [];
  if (layer !== 'pred') {
    item.gt.forEach((g) => {
      let text = null;
      if (g.status === 'fn') text = `漏：${nameOf(g.cls)}`;
      else if (layer === 'gt' || g.status === 'wrong') text = `標註：${nameOf(g.cls)}`;
      shapes.push({ key: `g${g.id}`, box: g.box, status: g.status, dashed: true, text });
    });
  }
  if (layer !== 'gt') {
    item.preds.forEach((p) => {
      const conf = p.conf != null ? ` ${p.conf.toFixed(2)}` : '';
      let text = `${nameOf(p.cls)}${conf}`;
      if (p.status === 'fp') text = `誤報：${text}`;
      if (p.status === 'wrong') {
        text = `錯判：${nameOf(gtById[p.pair]?.cls)}→${nameOf(p.cls)}${conf}`;
      }
      shapes.push({ key: `p${p.id}`, box: p.box, status: p.status, dashed: false, text });
    });
  }

  const fontSize = Math.max(12, Math.round(Math.max(width, height) / 40));

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      className="absolute inset-0 w-full h-full pointer-events-none"
      aria-hidden="true"
    >
      {shapes.map(({ key, box, status, dashed }) => (
        <rect
          key={key}
          x={box[0]}
          y={box[1]}
          width={Math.max(0, box[2] - box[0])}
          height={Math.max(0, box[3] - box[1])}
          fill="none"
          stroke={BOX_STYLES[status]?.stroke}
          strokeWidth={2}
          strokeDasharray={dashed ? GT_DASH : undefined}
          vectorEffect="non-scaling-stroke"
        />
      ))}
      {showLabels &&
        shapes
          .filter((s) => s.text)
          .map(({ key, box, status, text }) => {
            const w = textWidth(text, fontSize) + fontSize * 0.5;
            const h = fontSize * 1.3;
            const y = box[1] - h >= 0 ? box[1] - h : box[1];
            const x = Math.max(0, Math.min(box[0], width - w));
            return (
              <g key={`t${key}`}>
                <rect x={x} y={y} width={w} height={h} fill={BOX_STYLES[status]?.stroke} />
                <text x={x + fontSize * 0.25} y={y + fontSize} fontSize={fontSize} fill="var(--color-bg)">
                  {text}
                </text>
              </g>
            );
          })}
    </svg>
  );
};

export default BoxOverlay;
