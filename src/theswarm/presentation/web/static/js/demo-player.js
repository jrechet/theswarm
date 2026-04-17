/**
 * Demo Player — slide navigation, keyboard controls, autoplay.
 */
(function () {
  'use strict';

  const stage = document.getElementById('player-stage');
  if (!stage) return;

  const slides = stage.querySelectorAll('.player-slide');
  const total = slides.length;
  if (total === 0) return;

  const progressFill = document.getElementById('progress-fill');
  const segments = document.querySelectorAll('.progress-segment');
  const currentEl = document.getElementById('slide-current');
  const btnPrev = document.getElementById('btn-prev');
  const btnNext = document.getElementById('btn-next');
  const btnAutoplay = document.getElementById('btn-autoplay');
  const btnFullscreen = document.getElementById('btn-fullscreen');

  let current = 0;
  let autoplayTimer = null;
  const AUTOPLAY_INTERVAL = 8000;

  function goTo(index) {
    if (index < 0 || index >= total) return;

    slides[current].classList.remove('active');
    slides[current].classList.add('exit');

    current = index;

    slides[current].classList.remove('exit');
    slides[current].classList.add('active');

    // Clean exit class after transition
    setTimeout(function () {
      for (var i = 0; i < slides.length; i++) {
        if (i !== current) slides[i].classList.remove('exit');
      }
    }, 400);

    updateUI();
  }

  function next() {
    if (current < total - 1) {
      goTo(current + 1);
    } else if (autoplayTimer) {
      stopAutoplay();
    }
  }

  function prev() {
    if (current > 0) goTo(current - 1);
  }

  function updateUI() {
    // Counter
    currentEl.textContent = current + 1;

    // Progress bar
    var pct = ((current + 1) / total) * 100;
    progressFill.style.width = pct + '%';

    // Segments
    for (var i = 0; i < segments.length; i++) {
      segments[i].classList.toggle('active', i === current);
      segments[i].classList.toggle('visited', i < current);
    }

    // Disable buttons at edges
    btnPrev.disabled = current === 0;
    btnNext.disabled = current === total - 1;

    // Pause any videos not on current slide
    var allVideos = stage.querySelectorAll('video');
    for (var v = 0; v < allVideos.length; v++) {
      allVideos[v].pause();
    }
  }

  // Autoplay
  function startAutoplay() {
    if (autoplayTimer) return;
    btnAutoplay.classList.add('active');
    autoplayTimer = setInterval(function () {
      if (current < total - 1) {
        next();
      } else {
        stopAutoplay();
      }
    }, AUTOPLAY_INTERVAL);
  }

  function stopAutoplay() {
    if (!autoplayTimer) return;
    btnAutoplay.classList.remove('active');
    clearInterval(autoplayTimer);
    autoplayTimer = null;
  }

  function toggleAutoplay() {
    if (autoplayTimer) stopAutoplay();
    else startAutoplay();
  }

  function toggleFullscreen() {
    if (!document.fullscreenElement) {
      document.documentElement.requestFullscreen().catch(function () {});
    } else {
      document.exitFullscreen().catch(function () {});
    }
  }

  // Event listeners
  btnPrev.addEventListener('click', function () { stopAutoplay(); prev(); });
  btnNext.addEventListener('click', function () { stopAutoplay(); next(); });
  btnAutoplay.addEventListener('click', toggleAutoplay);
  btnFullscreen.addEventListener('click', toggleFullscreen);

  // Segment clicks
  for (var s = 0; s < segments.length; s++) {
    (function (idx) {
      segments[idx].addEventListener('click', function () {
        stopAutoplay();
        goTo(idx);
      });
    })(s);
  }

  // Keyboard navigation
  document.addEventListener('keydown', function (e) {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

    switch (e.key) {
      case 'ArrowRight':
      case ' ':
        e.preventDefault();
        stopAutoplay();
        next();
        break;
      case 'ArrowLeft':
        e.preventDefault();
        stopAutoplay();
        prev();
        break;
      case 'Home':
        e.preventDefault();
        stopAutoplay();
        goTo(0);
        break;
      case 'End':
        e.preventDefault();
        stopAutoplay();
        goTo(total - 1);
        break;
      case 'f':
      case 'F':
        e.preventDefault();
        toggleFullscreen();
        break;
      case 'a':
      case 'A':
        e.preventDefault();
        toggleAutoplay();
        break;
      case 'Escape':
        if (document.fullscreenElement) {
          document.exitFullscreen();
        } else {
          // Navigate back to demos list
          var base = document.documentElement.dataset.base || '';
          window.location.href = base + '/demos/';
        }
        break;
    }
  });

  // Touch swipe support
  var touchStartX = 0;
  var touchStartY = 0;

  stage.addEventListener('touchstart', function (e) {
    touchStartX = e.changedTouches[0].screenX;
    touchStartY = e.changedTouches[0].screenY;
  }, { passive: true });

  stage.addEventListener('touchend', function (e) {
    var dx = e.changedTouches[0].screenX - touchStartX;
    var dy = e.changedTouches[0].screenY - touchStartY;

    // Only horizontal swipes (more horizontal than vertical, min 50px)
    if (Math.abs(dx) > Math.abs(dy) && Math.abs(dx) > 50) {
      stopAutoplay();
      if (dx < 0) next();
      else prev();
    }
  }, { passive: true });

  // Initialize
  updateUI();
})();
