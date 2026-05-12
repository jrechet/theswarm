// Surface platform-readiness errors at the top of every page so a missing
// SWARM_VAULT_MASTER_KEY or ANTHROPIC_API_KEY is impossible to miss.
(function () {
  var banner = document.getElementById('readiness-banner');
  if (!banner) return;
  var base = document.documentElement.dataset.base || '';

  var DISMISS_KEY = 'swarm.readinessBanner.dismissed';

  function dismissedFingerprint() {
    try { return sessionStorage.getItem(DISMISS_KEY) || ''; } catch (e) { return ''; }
  }
  function rememberDismiss(fingerprint) {
    try { sessionStorage.setItem(DISMISS_KEY, fingerprint); } catch (e) {}
  }

  banner.addEventListener('click', function (ev) {
    if (ev.target && ev.target.dataset && ev.target.dataset.action === 'dismiss') {
      banner.hidden = true;
      rememberDismiss(banner.dataset.fingerprint || '1');
    }
  });

  function fingerprintFor(checks) {
    var keys = Object.keys(checks).sort();
    return keys.map(function (k) { return k + ':' + checks[k].status; }).join('|');
  }

  function summarize(checks) {
    var problems = [];
    Object.keys(checks).forEach(function (k) {
      var c = checks[k];
      if (c.status === 'error' || c.status === 'warn') {
        problems.push(k.replace(/_/g, ' ') + ': ' + (c.detail || c.status));
      }
    });
    if (!problems.length) return null;
    if (problems.length === 1) return problems[0];
    return problems[0] + ' (+' + (problems.length - 1) + ' more)';
  }

  function render(payload) {
    var checks = (payload && payload.checks) || {};
    var summary = summarize(checks);
    if (!summary) {
      banner.hidden = true;
      return;
    }
    var fingerprint = fingerprintFor(checks);
    banner.dataset.fingerprint = fingerprint;
    if (dismissedFingerprint() === fingerprint) {
      banner.hidden = true;
      return;
    }
    var summaryEl = banner.querySelector('[data-field="summary"]');
    if (summaryEl) summaryEl.textContent = ' ' + summary + ' ';
    banner.classList.toggle('readiness-banner-error', payload.status === 'error');
    banner.hidden = false;
  }

  fetch(base + '/health/ready', { headers: { 'Accept': 'application/json' } })
    .then(function (r) { return r.json(); })
    .then(render)
    .catch(function () { /* silent — banner stays hidden */ });
})();
