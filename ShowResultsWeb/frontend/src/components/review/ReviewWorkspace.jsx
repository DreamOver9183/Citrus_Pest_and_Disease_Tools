import React, { useCallback, useEffect, useState } from 'react';
import { useExperiment } from '../../context/ExperimentContext';
import ReviewGallery from './ReviewGallery';
import ReviewJobList from './ReviewJobList';
import ReviewLauncher from './ReviewLauncher';
import ReviewLightbox from './ReviewLightbox';

// 「驗證評估」分頁的逐張檢視模式：左欄送出與紀錄，右欄目前選中之檢視的圖庫。
//
// 燈箱開關留在元件本地（純呈現）；選中的 job、篩選條件與捲動位置在 useReview。
const ReviewWorkspace = () => {
  const { reviewJobs, reviewSelectedJobId, reviewScrollRef } = useExperiment();
  const [lightbox, setLightbox] = useState(null);

  const job = reviewJobs.find((j) => j.job_id === reviewSelectedJobId && j.state === 'done') || null;

  // 切走分頁再回來時還原捲動位置
  useEffect(() => {
    const saved = reviewScrollRef.current;
    if (saved) requestAnimationFrame(() => window.scrollTo(0, saved));
    return () => {
      reviewScrollRef.current = window.scrollY;
    };
  }, [reviewScrollRef]);

  const closeLightbox = useCallback(() => setLightbox(null), []);

  return (
    <>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 items-start">
        <div className="space-y-6">
          <ReviewLauncher />
          <section className="space-y-3">
            <h3 className="text-sm font-medium text-ink">
              檢視紀錄 <span className="text-ds-neutral-600 tabular-nums">({reviewJobs.length})</span>
            </h3>
            <ReviewJobList />
          </section>
        </div>
        <div className="lg:col-span-2">
          <ReviewGallery job={job} onOpen={(names, index) => setLightbox({ names, index })} />
        </div>
      </div>

      {lightbox && job && (
        <ReviewLightbox job={job} names={lightbox.names} startIndex={lightbox.index} onClose={closeLightbox} />
      )}
    </>
  );
};

export default ReviewWorkspace;
