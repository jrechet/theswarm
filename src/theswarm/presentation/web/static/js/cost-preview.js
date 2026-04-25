// Cost preview modal (Sprint D C5)
(function () {
  var form = document.getElementById('run-cycle-form');
  var modal = document.getElementById('cost-preview-modal');
  if (!form || !modal) return;

  var confirmBtn = document.getElementById('cost-preview-confirm');
  var btn = document.getElementById('run-cycle-btn');
  var endpoint = form.getAttribute('data-estimate-url');
  var confirmed = false;

  function fmtNumber(n) {
    if (typeof n !== 'number' || isNaN(n)) return '—';
    return n.toLocaleString();
  }

  function fmtUsd(n) {
    if (typeof n !== 'number' || isNaN(n)) return '—';
    return '$' + n.toFixed(n < 1 ? 4 : 2);
  }

  function open() {
    modal.hidden = false;
    modal.setAttribute('aria-hidden', 'false');
    document.body.classList.add('modal-open');
  }

  function close() {
    modal.hidden = true;
    modal.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('modal-open');
  }

  function render(estimate) {
    var basisEl = modal.querySelector('[data-cost-basis]');
    var tokensEl = modal.querySelector('[data-cost-tokens]');
    var usdEl = modal.querySelector('[data-cost-usd]');
    var modelsEl = modal.querySelector('[data-cost-models]');
    var backlogEl = modal.querySelector('[data-cycle-backlog]');
    var iterEl = modal.querySelector('[data-cycle-iter]');

    if (basisEl) {
      if (estimate.basis === 'history') {
        basisEl.textContent = 'Estimate from the last ' + estimate.sample_size + ' completed cycle' + (estimate.sample_size === 1 ? '' : 's') + '.';
      } else if (estimate.basis === '...') {
        basisEl.textContent = 'Calculating…';
      } else {
        basisEl.textContent = 'No cycle history yet. Showing baseline estimate from the configured models.';
      }
    }
    if (tokensEl) tokensEl.textContent = fmtNumber(estimate.tokens);
    if (usdEl) usdEl.textContent = fmtUsd(estimate.cost_usd);

    if (modelsEl) {
      modelsEl.innerHTML = '';
      var phases = estimate.models_by_phase || {};
      Object.keys(phases).forEach(function (phase) {
        var li = document.createElement('li');
        li.innerHTML = '<span class="cost-phase">' + phase + '</span><span class="cost-model">' + phases[phase] + '</span>';
        modelsEl.appendChild(li);
      });
    }

    if (iterEl && typeof estimate.max_dev_iterations === 'number') {
      iterEl.textContent = String(estimate.max_dev_iterations);
    }

    if (backlogEl) {
      backlogEl.innerHTML = '';
      if (estimate.backlog_error) {
        var li = document.createElement('li');
        li.className = 'cycle-backlog-empty';
        li.textContent = 'Could not load backlog: ' + estimate.backlog_error;
        backlogEl.appendChild(li);
      } else if (!estimate.backlog || !estimate.backlog.length) {
        var li2 = document.createElement('li');
        li2.className = 'cycle-backlog-empty';
        li2.textContent = 'No status:backlog issues open. PO will run a planning pass and exit early.';
        backlogEl.appendChild(li2);
      } else {
        estimate.backlog.forEach(function (item) {
          var li = document.createElement('li');
          var num = item.number != null ? '#' + item.number : '';
          var title = (item.title || '').slice(0, 100);
          if (item.url) {
            li.innerHTML = '<a href="' + item.url + '" target="_blank" rel="noopener"><span class="cycle-backlog-num">' + num + '</span> <span class="cycle-backlog-title">' + title + '</span></a>';
          } else {
            li.innerHTML = '<span class="cycle-backlog-num">' + num + '</span> <span class="cycle-backlog-title">' + title + '</span>';
          }
          backlogEl.appendChild(li);
        });
      }
    }
  }

  function renderError(message) {
    var basisEl = modal.querySelector('[data-cost-basis]');
    if (basisEl) basisEl.textContent = message || 'Unable to compute estimate.';
  }

  form.addEventListener('submit', function (event) {
    if (confirmed) return;
    event.preventDefault();
    open();
    render({tokens: null, cost_usd: null, models_by_phase: {}, basis: '...', sample_size: 0});
    fetch(endpoint, {headers: {'Accept': 'application/json'}})
      .then(function (r) { return r.ok ? r.json() : Promise.reject(r); })
      .then(render)
      .catch(function () { renderError('Failed to load estimate. You can still run the cycle.'); });
  });

  modal.addEventListener('click', function (event) {
    if (event.target && event.target.hasAttribute('data-modal-close')) {
      close();
    }
  });

  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && !modal.hidden) close();
  });

  if (confirmBtn) {
    confirmBtn.addEventListener('click', function () {
      confirmed = true;
      close();
      if (btn) btn.disabled = true;
      form.submit();
    });
  }
})();
