// Cycle replay scrubber — 10fps playback over captured events
(function () {
  var dataEl = document.getElementById('replay-frames-data');
  if (!dataEl) return;

  var frames = [];
  try {
    frames = JSON.parse(dataEl.textContent || '[]');
  } catch (e) {
    frames = [];
  }
  if (!Array.isArray(frames) || frames.length === 0) return;

  var range = document.querySelector('[data-replay-range]');
  var playBtn = document.querySelector('[data-replay-play]');
  var pauseBtn = document.querySelector('[data-replay-pause]');
  var resetBtn = document.querySelector('[data-replay-reset]');
  var speedSel = document.querySelector('[data-replay-speed]');
  var timeEl = document.querySelector('[data-replay-time]');
  var detailTitle = document.querySelector('[data-replay-detail-title]');
  var detailPayload = document.querySelector('[data-replay-detail-payload]');
  var items = document.querySelectorAll('[data-replay-index]');

  var total = frames[frames.length - 1].offset_ms || 0;
  var currentIndex = 0;
  var timer = null;
  var FPS = 10;
  var tickMs = Math.floor(1000 / FPS);
  var virtualMs = 0;

  function fmt(ms) {
    return (ms / 1000).toFixed(2) + 's';
  }

  function renderFrame(idx) {
    currentIndex = idx;
    var frame = frames[idx];
    if (!frame) return;

    if (range) range.value = String(idx);
    if (timeEl) timeEl.textContent = fmt(frame.offset_ms) + ' / ' + fmt(total);

    items.forEach(function (el) {
      var i = parseInt(el.getAttribute('data-replay-index'), 10);
      el.classList.toggle('is-current', i === idx);
      el.classList.toggle('is-past', i < idx);
    });

    if (detailTitle) detailTitle.textContent = frame.event_type;
    if (detailPayload) {
      try {
        detailPayload.textContent = JSON.stringify(frame.payload || {}, null, 2);
      } catch (e) {
        detailPayload.textContent = String(frame.payload);
      }
    }

    var active = document.querySelector('.replay-event-item.is-current');
    if (active && active.scrollIntoView) {
      active.scrollIntoView({block: 'nearest', behavior: 'smooth'});
    }
  }

  function nextIndexForVirtualMs(targetMs) {
    var idx = currentIndex;
    while (idx + 1 < frames.length && frames[idx + 1].offset_ms <= targetMs) {
      idx += 1;
    }
    return idx;
  }

  function stop() {
    if (timer) {
      clearInterval(timer);
      timer = null;
    }
    if (playBtn) playBtn.hidden = false;
    if (pauseBtn) pauseBtn.hidden = true;
  }

  function start() {
    stop();
    if (currentIndex >= frames.length - 1) {
      virtualMs = 0;
      renderFrame(0);
    } else {
      virtualMs = frames[currentIndex].offset_ms;
    }
    var speed = parseFloat((speedSel && speedSel.value) || '1') || 1;
    if (playBtn) playBtn.hidden = true;
    if (pauseBtn) pauseBtn.hidden = false;

    timer = setInterval(function () {
      virtualMs += tickMs * speed;
      var nextIdx = nextIndexForVirtualMs(virtualMs);
      if (nextIdx !== currentIndex) renderFrame(nextIdx);
      if (virtualMs >= total) {
        renderFrame(frames.length - 1);
        stop();
      }
    }, tickMs);
  }

  if (playBtn) playBtn.addEventListener('click', start);
  if (pauseBtn) pauseBtn.addEventListener('click', stop);
  if (resetBtn) resetBtn.addEventListener('click', function () {
    stop();
    virtualMs = 0;
    renderFrame(0);
  });
  if (range) {
    range.addEventListener('input', function () {
      stop();
      var idx = parseInt(range.value, 10) || 0;
      virtualMs = frames[idx] ? frames[idx].offset_ms : 0;
      renderFrame(idx);
    });
  }

  items.forEach(function (el) {
    el.addEventListener('click', function () {
      stop();
      var idx = parseInt(el.getAttribute('data-replay-index'), 10) || 0;
      virtualMs = frames[idx].offset_ms;
      renderFrame(idx);
    });
  });

  renderFrame(0);
})();
