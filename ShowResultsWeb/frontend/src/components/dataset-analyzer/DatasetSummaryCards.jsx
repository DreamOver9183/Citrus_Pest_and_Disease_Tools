import React from 'react';
import { Image, Tag, Layers3, Ghost } from 'lucide-react';
import { formatNumber, formatPct } from './datasetFormat';

const CARDS = [
  {
    key: 'total_images',
    label: '影像總數',
    en: 'Total Images',
    icon: Image,
    tone: 'text-rose-400 bg-rose-500/10',
  },
  {
    key: 'total_annotations',
    label: '標註總數',
    en: 'Total Annotations',
    icon: Tag,
    tone: 'text-orange-400 bg-orange-500/10',
  },
  {
    key: 'class_count',
    label: '類別數',
    en: 'Classes',
    icon: Layers3,
    tone: 'text-indigo-400 bg-indigo-500/10',
  },
  {
    key: 'background_images',
    label: '空標註影像',
    en: 'Background Samples',
    icon: Ghost,
    tone: 'text-sky-400 bg-sky-500/10',
  },
];

const DatasetSummaryCards = ({ stats }) => {
  const values = {
    total_images: stats.total_images,
    total_annotations: stats.total_annotations,
    class_count: (stats.classes || []).length,
    background_images: stats.background_images,
  };

  const annPerImage = stats.total_images
    ? (stats.total_annotations / stats.total_images).toFixed(2)
    : '0';
  const bgPct = stats.total_images
    ? (100 * stats.background_images) / stats.total_images
    : 0;

  const subtitles = {
    total_images: `${stats.splits?.length || 0} 個資料分割`,
    total_annotations: `平均每張 ${annPerImage} 個標註`,
    class_count:
      stats.declared_nc != null ? `data.yaml 宣告 nc = ${stats.declared_nc}` : '由標註內容推得',
    background_images: `佔 ${formatPct(bgPct)}．負樣本用於降低假陽性`,
  };

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
      {CARDS.map((card) => {
        const Icon = card.icon;
        return (
          <div
            key={card.key}
            className="glass-panel p-5 rounded-2xl border border-white/[0.06] shadow-xl relative overflow-hidden"
          >
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="text-[10px] text-gray-500 uppercase font-mono tracking-wider">
                  {card.en}
                </p>
                <p className="text-2xl font-extrabold text-white mt-1 font-sans tracking-tight">
                  {formatNumber(values[card.key])}
                </p>
              </div>
              <div className={`p-2 rounded-lg flex-shrink-0 ${card.tone}`}>
                <Icon className="w-4 h-4" />
              </div>
            </div>
            <p className="text-[11px] text-gray-300 font-sans font-semibold mt-2">{card.label}</p>
            <p className="text-[9px] text-gray-500 font-sans mt-0.5 leading-relaxed">
              {subtitles[card.key]}
            </p>
          </div>
        );
      })}
    </div>
  );
};

export default DatasetSummaryCards;
