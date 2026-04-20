/**
 * Sprint F F8 — A/B demo comparator with synced video scrubbing.
 */
(function () {
  'use strict';

  const shell = document.getElementById('compare-shell');
  if (!shell) return;

  const videos = Array.from(shell.querySelectorAll('video.compare-video'));
  const btnPlay = document.getElementById('compare-play');
  const btnPause = document.getElementById('compare-pause');
  const scrub = document.getElementById('compare-scrub');
  const timeLabel = document.getElementById('compare-time');

  if (videos.length === 0) {
    if (btnPlay) btnPlay.disabled = true;
    if (btnPause) btnPause.disabled = true;
    if (scrub) scrub.disabled = true;
    return;
  }

  let suppressSync = false;

  function playAll() {
    videos.forEach(function (v) {
      v.play().catch(function () { /* autoplay blocked is fine */ });
    });
  }

  function pauseAll() {
    videos.forEach(function (v) { v.pause(); });
  }

  function maxDuration() {
    let d = 0;
    for (const v of videos) {
      if (Number.isFinite(v.duration) && v.duration > d) d = v.duration;
    }
    return d;
  }

  function updateScrubFromVideos() {
    if (suppressSync) return;
    const d = maxDuration();
    if (d <= 0) return;
    const t = videos[0].currentTime;
    scrub.value = String(Math.round((t / d) * 1000));
    timeLabel.textContent = t.toFixed(1) + 's';
  }

  if (btnPlay) btnPlay.addEventListener('click', playAll);
  if (btnPause) btnPause.addEventListener('click', pauseAll);

  if (scrub) {
    scrub.addEventListener('input', function () {
      const d = maxDuration();
      if (d <= 0) return;
      const ratio = parseInt(scrub.value, 10) / 1000;
      const target = ratio * d;
      suppressSync = true;
      videos.forEach(function (v) {
        if (Number.isFinite(v.duration)) {
          v.currentTime = Math.min(v.duration, target);
        }
      });
      timeLabel.textContent = target.toFixed(1) + 's';
      // Release in next tick
      setTimeout(function () { suppressSync = false; }, 50);
    });
  }

  videos.forEach(function (v) {
    v.addEventListener('timeupdate', updateScrubFromVideos);
    v.addEventListener('loadedmetadata', updateScrubFromVideos);
  });
})();
