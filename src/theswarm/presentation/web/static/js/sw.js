// TheSwarm notifications service worker
// Handles notification clicks: focus existing tab or open URL.
self.addEventListener('install', function (event) {
  self.skipWaiting();
});

self.addEventListener('activate', function (event) {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('notificationclick', function (event) {
  var targetUrl = (event.notification.data && event.notification.data.url) || '/';
  event.notification.close();
  event.waitUntil(
    self.clients.matchAll({type: 'window', includeUncontrolled: true}).then(function (windows) {
      for (var i = 0; i < windows.length; i++) {
        var w = windows[i];
        if ('focus' in w && w.url.indexOf(targetUrl) !== -1) {
          return w.focus();
        }
      }
      if (self.clients.openWindow) return self.clients.openWindow(targetUrl);
      return null;
    }),
  );
});
