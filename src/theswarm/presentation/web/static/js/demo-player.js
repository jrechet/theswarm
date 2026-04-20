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

  // Sprint F F7 — playback-speed control (0.5× / 1× / 2×)
  const SPEED_KEY = 'theswarm:demo-player:speed';
  const speedButtons = document.querySelectorAll('.player-speed-btn');
  let currentSpeed = 1;
  try {
    const stored = parseFloat(window.localStorage.getItem(SPEED_KEY) || '');
    if (stored === 0.5 || stored === 1 || stored === 2) currentSpeed = stored;
  } catch (_) { /* localStorage may be unavailable in sandboxed frames */ }

  function applySpeed(speed) {
    currentSpeed = speed;
    const videos = stage.querySelectorAll('video');
    for (var i = 0; i < videos.length; i++) {
      videos[i].playbackRate = speed;
    }
    for (var b = 0; b < speedButtons.length; b++) {
      var btn = speedButtons[b];
      var match = parseFloat(btn.getAttribute('data-speed')) === speed;
      btn.classList.toggle('is-active', match);
      btn.setAttribute('aria-pressed', match ? 'true' : 'false');
    }
    try { window.localStorage.setItem(SPEED_KEY, String(speed)); } catch (_) {}
  }

  for (var sb = 0; sb < speedButtons.length; sb++) {
    (function (btn) {
      btn.addEventListener('click', function () {
        const v = parseFloat(btn.getAttribute('data-speed'));
        if (!Number.isFinite(v)) return;
        applySpeed(v);
      });
    })(speedButtons[sb]);
  }

  // Re-apply whenever a new video becomes visible (per-slide)
  stage.addEventListener('play', function (e) {
    if (e.target && e.target.tagName === 'VIDEO') e.target.playbackRate = currentSpeed;
  }, true);

  applySpeed(currentSpeed);

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

  // Story action forms — AJAX submit with inline status
  var forms = document.querySelectorAll('.story-action-form');
  forms.forEach(function (form) {
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var container = form.closest('[data-story-actions]');
      var status = container
        ? container.querySelector('.story-action-status')
        : null;
      var btn = form.querySelector('button');
      if (btn) btn.disabled = true;
      if (status) {
        status.textContent = '…';
        status.className = 'story-action-status pending';
      }
      fetch(form.action, {
        method: 'POST',
        body: new FormData(form),
      })
        .then(function (res) {
          if (res.ok) {
            if (status) {
              status.textContent = form.dataset.action + ' recorded';
              status.className = 'story-action-status ok';
            }
          } else if (res.status === 409) {
            if (status) {
              status.textContent = 'already ' + form.dataset.action + 'd';
              status.className = 'story-action-status warn';
            }
          } else {
            if (status) {
              status.textContent = 'failed (' + res.status + ')';
              status.className = 'story-action-status err';
            }
          }
        })
        .catch(function () {
          if (status) {
            status.textContent = 'network error';
            status.className = 'story-action-status err';
          }
        })
        .finally(function () {
          if (btn) btn.disabled = false;
        });
    });
  });
})();
