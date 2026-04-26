(() => {
  const SLIDE_MS = 4500;

  const stage = document.querySelector('[data-todays-demo-stage]');
  if (!stage) return;

  const slides = Array.from(stage.querySelectorAll('.todays-demo-slide'));
  const dots = Array.from(stage.querySelectorAll('[data-todays-demo-dot]'));
  const btnPrev = stage.querySelector('[data-todays-demo-prev]');
  const btnNext = stage.querySelector('[data-todays-demo-next]');
  const btnPlayPause = stage.querySelector('[data-todays-demo-playpause]');
  const iconPlay = btnPlayPause.querySelector('[data-icon-play]');
  const iconPause = btnPlayPause.querySelector('[data-icon-pause]');

  let index = 0;
  let timer = null;
  let playing = true;

  function show(i) {
    index = (i + slides.length) % slides.length;
    slides.forEach((s, k) => s.classList.toggle('is-active', k === index));
    dots.forEach((d, k) => d.classList.toggle('is-active', k === index));
  }

  function tick() { show(index + 1); }

  function play() {
    if (timer) return;
    timer = setInterval(tick, SLIDE_MS);
    playing = true;
    iconPlay.hidden = true;
    iconPause.hidden = false;
    btnPlayPause.setAttribute('aria-label', 'Pause');
  }

  function pause() {
    if (timer) { clearInterval(timer); timer = null; }
    playing = false;
    iconPlay.hidden = false;
    iconPause.hidden = true;
    btnPlayPause.setAttribute('aria-label', 'Play');
  }

  btnPrev.addEventListener('click', () => { pause(); show(index - 1); });
  btnNext.addEventListener('click', () => { pause(); show(index + 1); });
  btnPlayPause.addEventListener('click', () => playing ? pause() : play());
  dots.forEach((d, k) => d.addEventListener('click', () => { pause(); show(k); }));

  stage.addEventListener('mouseenter', pause);
  stage.addEventListener('mouseleave', () => { if (!stage.dataset.expanded) play(); });

  // Pause when tab not visible to be a good citizen.
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) pause();
  });

  // Expand button → fullscreen-ish modal overlay reusing the same stage.
  const expandBtn = document.querySelector('.todays-demo-expand');
  const card = stage.closest('.todays-demo');
  expandBtn?.addEventListener('click', () => {
    const expanded = card.classList.toggle('is-expanded');
    stage.dataset.expanded = expanded ? '1' : '';
    document.body.classList.toggle('has-todays-demo-expanded', expanded);
    if (expanded) pause(); else play();
  });
  // Esc closes the expanded view.
  document.addEventListener('keydown', (e) => {
    if (card.classList.contains('is-expanded')) {
      if (e.key === 'Escape') expandBtn.click();
      else if (e.key === 'ArrowRight') { pause(); show(index + 1); }
      else if (e.key === 'ArrowLeft') { pause(); show(index - 1); }
    }
  });

  play();
})();
