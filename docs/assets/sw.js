const CACHE_STATIC = 'eurlex-static-v3';
const STATIC_ASSETS = [
  './', './index.html', './assets/ui.css', './assets/theme.js', './assets/app.js', './assets/manifest.json'
];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE_STATIC).then(c => c.addAll(STATIC_ASSETS)));
});
self.addEventListener('activate', e => { e.waitUntil(self.clients.claim()); });

// For /data/* use network-first; for everything else cache-first.
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (url.pathname.includes('/data/')) {
    e.respondWith(
      fetch(e.request).then(resp => {
        const copy = resp.clone();
        caches.open(CACHE_STATIC).then(c => c.put(e.request, copy));
        return resp;
      }).catch(() => caches.match(e.request))
    );
  } else {
    e.respondWith(
      caches.match(e.request).then(r => r || fetch(e.request))
    );
  }
});
