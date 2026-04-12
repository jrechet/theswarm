// SSE client with reconnect and activity feed rendering
(function() {
  const statusEl = document.getElementById('sse-status');
  const feedEl = document.getElementById('activity-feed');
  let reconnectDelay = 1000;
  let es = null;

  function connect() {
    es = new EventSource('/api/events');

    es.onopen = function() {
      if (statusEl) statusEl.textContent = 'Connected';
      reconnectDelay = 1000;
    };

    es.onmessage = function(event) {
      if (!feedEl) return;
      try {
        const data = JSON.parse(event.data);
        const item = document.createElement('div');
        item.className = 'activity-item';

        const time = new Date(data.occurred_at).toLocaleTimeString();
        const agent = data.agent || data.type;
        const detail = data.detail || data.action || data.type;

        item.innerHTML = [
          '<span class="activity-time">' + time + '</span>',
          '<span class="activity-agent">' + agent + '</span>',
          '<span class="activity-detail">' + detail + '</span>'
        ].join('');

        // Remove "waiting" message
        const empty = feedEl.querySelector('.empty-state');
        if (empty) empty.remove();

        feedEl.prepend(item);

        // Keep max 100 items
        while (feedEl.children.length > 100) {
          feedEl.removeChild(feedEl.lastChild);
        }
      } catch(e) {
        console.warn('SSE parse error:', e);
      }
    };

    es.onerror = function() {
      es.close();
      if (statusEl) statusEl.textContent = 'Reconnecting...';
      setTimeout(connect, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 2, 30000);
    };
  }

  // Only connect if we're on a page with the feed
  if (feedEl || statusEl) {
    connect();
  }
})();
