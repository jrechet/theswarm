// Browser notifications for new demos (Sprint D V5)
(function () {
  if (typeof window === 'undefined') return;
  if (!('Notification' in window)) return;
  if (!('serviceWorker' in navigator)) return;

  var base = document.documentElement.dataset.base || '';
  var btn = document.getElementById('notifications-toggle');
  if (!btn) return;

  btn.hidden = false;
  var swRegistration = null;

  function setState(state) {
    btn.setAttribute('data-state', state);
    var label = btn.querySelector('[data-field="label"]');
    var icon = btn.querySelector('[data-field="icon"]');
    if (state === 'enabled') {
      if (label) label.textContent = 'Notifications on';
      if (icon) icon.textContent = '🔔';
      btn.title = 'Browser notifications enabled for new demos';
    } else if (state === 'denied') {
      if (label) label.textContent = 'Notifications blocked';
      if (icon) icon.textContent = '🔕';
      btn.title = 'Re-enable notifications in your browser site settings';
      btn.disabled = true;
    } else {
      if (label) label.textContent = 'Notify me';
      if (icon) icon.textContent = '🔔';
      btn.title = 'Enable browser notifications for new demos';
    }
  }

  function registerSW() {
    return navigator.serviceWorker
      .register(base + '/static/js/sw.js', {scope: base + '/'})
      .then(function (reg) { swRegistration = reg; return reg; })
      .catch(function () { return null; });
  }

  function currentPermission() {
    try { return Notification.permission; } catch (e) { return 'default'; }
  }

  function syncFromPermission() {
    var p = currentPermission();
    if (p === 'granted') setState('enabled');
    else if (p === 'denied') setState('denied');
    else setState('idle');
  }

  function requestPermission() {
    if (currentPermission() === 'granted') {
      setState('enabled');
      return Promise.resolve('granted');
    }
    return Notification.requestPermission().then(function (result) {
      if (result === 'granted') {
        setState('enabled');
        registerSW();
      } else if (result === 'denied') {
        setState('denied');
      }
      return result;
    });
  }

  btn.addEventListener('click', requestPermission);

  function showDemoNotification(data) {
    if (currentPermission() !== 'granted') return;
    var title = data.title || 'New demo ready';
    var body = data.project_id ? ('Project: ' + data.project_id) : 'A new demo is ready to view.';
    var url = data.play_url || (base + '/demos/');
    var opts = {
      body: body,
      icon: base + '/static/icon.png',
      badge: base + '/static/icon.png',
      tag: 'swarm-demo-' + (data.report_id || data.event_id || Date.now()),
      renotify: false,
      data: {url: url},
    };
    if (swRegistration && swRegistration.showNotification) {
      swRegistration.showNotification(title, opts).catch(function () {
        try { new Notification(title, opts); } catch (e) {}
      });
    } else {
      try { new Notification(title, opts); } catch (e) {}
    }
  }

  window.__swarmShowDemoNotification = showDemoNotification;

  syncFromPermission();
  if (currentPermission() === 'granted') registerSW();
})();
