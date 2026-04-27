// SSE client with reconnect, activity feed rendering, and HTMX-driven dashboard updates
(function() {
  var statusEl = document.getElementById('sse-status');
  var feedEl = document.getElementById('activity-feed');
  var base = document.documentElement.dataset.base || '';
  var reconnectDelay = 1000;
  var es = null;

  // Throttle HTMX refreshes to avoid hammering the server
  var _refreshTimers = {};
  function throttledRefresh(target, url, delay) {
    if (_refreshTimers[target]) return;
    _refreshTimers[target] = setTimeout(function() {
      delete _refreshTimers[target];
      var el = document.getElementById(target);
      if (el && typeof htmx !== 'undefined') {
        htmx.ajax('GET', url, {target: '#' + target, swap: 'innerHTML'});
      }
    }, delay || 500);
  }

  // Refresh dashboard sections based on event type
  function onDomainEvent(data) {
    var type = data.type || '';

    switch (type) {
      case 'CycleStarted':
      case 'CycleCompleted':
      case 'CycleFailed':
        // Full refresh: stats + both cycle tables
        throttledRefresh('stats-container', base + '/fragments/stats', 300);
        throttledRefresh('active-cycles-container', base + '/fragments/active-cycles', 300);
        throttledRefresh('recent-cycles-container', base + '/fragments/recent-cycles', 300);
        break;

      case 'PhaseChanged':
        // Phase change: update active cycles + stats
        throttledRefresh('stats-container', base + '/fragments/stats', 800);
        throttledRefresh('active-cycles-container', base + '/fragments/active-cycles', 500);
        break;

      case 'AgentActivity':
        // Activity: update active cycles (cost may have changed)
        throttledRefresh('active-cycles-container', base + '/fragments/active-cycles', 1000);
        break;

      case 'DemoReady':
        showDemoToast(data);
        if (typeof window.__swarmShowDemoNotification === 'function') {
          try { window.__swarmShowDemoNotification(data); } catch (e) {}
        }
        break;
    }

    // If on a cycle detail page, refresh that too
    var detailEl = document.getElementById('cycle-detail');
    if (detailEl) {
      var cycleId = detailEl.dataset.cycleId;
      var eventCycleId = String(data.cycle_id || '');
      if (cycleId && eventCycleId === cycleId) {
        throttledRefresh('cycle-overview', base + '/fragments/cycle/' + cycleId + '/overview', 500);
        throttledRefresh('cycle-phases', base + '/fragments/cycle/' + cycleId + '/phases', 500);
        throttledRefresh('cycle-timeline', base + '/fragments/cycle/' + cycleId + '/timeline', 500);
        if (type === 'AgentThought' || type === 'AgentStep' || type === 'AgentActivity') {
          throttledRefresh('cycle-thoughts', base + '/fragments/cycle/' + cycleId + '/thoughts', 800);
        }
      }
    }
  }

  // Render activity feed item
  function renderActivityItem(data) {
    if (!feedEl) return;

    var item = document.createElement('div');
    item.className = 'activity-item';

    var time = data.occurred_at ? new Date(data.occurred_at).toLocaleTimeString() : '--:--';
    var agent = data.agent || data.type || '?';
    var detail = data.detail || data.action || data.phase || data.type || '';
    var type = data.type || '';

    // Add type-specific styling
    var typeClass = '';
    if (type === 'CycleCompleted') typeClass = ' activity-success';
    else if (type === 'CycleFailed') typeClass = ' activity-danger';
    else if (type === 'CycleStarted') typeClass = ' activity-accent';

    item.className = 'activity-item' + typeClass;
    item.innerHTML = [
      '<span class="activity-time">' + time + '</span>',
      '<span class="activity-agent">' + escapeHtml(agent) + '</span>',
      '<span class="activity-detail">' + escapeHtml(detail) + '</span>'
    ].join('');

    // Remove "waiting" message
    var empty = feedEl.querySelector('.empty-state');
    if (empty) empty.remove();

    feedEl.prepend(item);

    // Keep max 100 items
    while (feedEl.children.length > 100) {
      feedEl.removeChild(feedEl.lastChild);
    }
  }

  function escapeHtml(str) {
    var div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  // Show a new-demo toast (cloned from #demo-toast-tpl)
  var _demoToastSeen = {};
  function showDemoToast(data) {
    var host = document.getElementById('demo-toast-host');
    var tpl = document.getElementById('demo-toast-tpl');
    if (!host || !tpl) return;

    var key = data.report_id || data.event_id;
    if (key && _demoToastSeen[key]) return;
    if (key) _demoToastSeen[key] = true;

    var node = tpl.content.firstElementChild.cloneNode(true);

    var titleEl = node.querySelector('[data-field="title"]');
    if (titleEl) titleEl.textContent = data.title || 'New demo ready';

    var playEl = node.querySelector('[data-field="play"]');
    if (playEl && data.play_url) playEl.setAttribute('href', data.play_url);

    var thumbWrap = node.querySelector('[data-field="thumbnail"]');
    if (thumbWrap && data.thumbnail_url) {
      var img = thumbWrap.querySelector('img');
      if (img) img.setAttribute('src', data.thumbnail_url);
      thumbWrap.hidden = false;
    }

    var dismiss = node.querySelector('.demo-toast-dismiss');
    function remove() {
      node.classList.add('demo-toast-leaving');
      setTimeout(function() {
        if (node.parentNode) node.parentNode.removeChild(node);
      }, 250);
    }
    if (dismiss) dismiss.addEventListener('click', remove);
    setTimeout(remove, 20000);

    host.appendChild(node);
    requestAnimationFrame(function() { node.classList.add('demo-toast-entered'); });
  }

  // Elapsed time updater for running cycles
  function updateElapsedTimers() {
    var cells = document.querySelectorAll('.elapsed-cell[data-started]');
    var now = Date.now();
    cells.forEach(function(cell) {
      var started = cell.dataset.started;
      if (!started) return;
      var startMs = new Date(started).getTime();
      if (isNaN(startMs)) return;
      var secs = Math.max(0, Math.floor((now - startMs) / 1000));
      if (secs < 60) {
        cell.textContent = secs + 's';
      } else {
        var mins = Math.floor(secs / 60);
        var remSecs = secs % 60;
        if (mins < 60) {
          cell.textContent = mins + 'm ' + remSecs + 's';
        } else {
          var hours = Math.floor(mins / 60);
          var remMins = mins % 60;
          cell.textContent = hours + 'h ' + remMins + 'm';
        }
      }
    });
  }

  // Update elapsed timers every second
  setInterval(updateElapsedTimers, 1000);

  function connect() {
    es = new EventSource(base + '/api/events');

    es.onopen = function() {
      if (statusEl) {
        statusEl.innerHTML = '<span class="status-dot connected"></span><span class="sidebar-status-label">Live updates</span>';
      }
      reconnectDelay = 1000;

      // On reconnect, refresh all sections to catch missed events
      throttledRefresh('stats-container', base + '/fragments/stats', 100);
      throttledRefresh('active-cycles-container', base + '/fragments/active-cycles', 100);
      throttledRefresh('recent-cycles-container', base + '/fragments/recent-cycles', 100);
    };

    es.onmessage = function(event) {
      try {
        var data = JSON.parse(event.data);
        renderActivityItem(data);
        onDomainEvent(data);
      } catch(e) {
        // Ignore parse errors
      }
    };

    es.onerror = function() {
      es.close();
      if (statusEl) {
        statusEl.innerHTML = '<span class="status-dot reconnecting"></span><span class="sidebar-status-label">Live updates: reconnecting…</span>';
      }
      setTimeout(connect, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 2, 30000);
    };
  }

  // Only connect if we're on a page that needs it
  if (feedEl || statusEl || document.getElementById('cycle-detail')) {
    connect();
  }
})();
