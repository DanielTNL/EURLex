const CACHE_STATIC = 'eurlex-site-v4';
const STATIC_ASSETS = [
  './', './index.html', './live.html',
  './assets/ui.css', './assets/theme.js', './assets/app.js', './assets/live.js', './assets/manifest.json'
];

self.addEventListener('install', e => e.waitUntil(caches.open(CACHE_STATIC).then(c=>c.addAll(STATIC_ASSETS))));
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if(url.pathname.includes('/data/')){
    e.respondWith(fetch(e.request).then(r=>{const c=r.clone(); caches.open(CACHE_STATIC).then(x=>x.put(e.request,c)); return r;}).catch(()=>caches.match(e.request)));
  }else{
    e.respondWith(caches.match(e.request).then(r=>r||fetch(e.request)));
  }
});
