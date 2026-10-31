// Service Worker for PulseBoard PWA (Network-First Navigation Strategy)
const CACHE_NAME = 'pulseboard-v8';
const ASSETS = [
  './manifest.json',
  './icon.svg',
  './icon-192.png',
  './icon-512.png',
  './icon-maskable-192.png',
  './icon-maskable-512.png',
  './apple-touch-icon.png'
];

self.addEventListener('install', (e) => {
  self.skipWaiting();
  e.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(ASSETS))
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((k) => {
          if (k !== CACHE_NAME) return caches.delete(k);
        })
      );
    }).then(() => self.clients.claim())
  );
});

// Network-First for HTML navigation so updates appear immediately
self.addEventListener('fetch', (e) => {
  const req = e.request;
  
  if (req.mode === 'navigate') {
    e.respondWith(
      fetch(req)
        .then((networkRes) => {
          networkRes.clone().text().then((body) => {
            if (networkRes.ok && !/vercel\.com\/toolbar|\/_vercel\//i.test(body)) {
              caches.open(CACHE_NAME).then((cache) => cache.put(req, networkRes.clone()));
            }
          }).catch(() => {});
          return networkRes;
        })
        .catch(() => caches.match(req).then((res) => res || caches.match('./index.html')))
    );
    return;
  }

  // Stale-while-revalidate for static assets
  e.respondWith(
    caches.match(req).then((cached) => {
      const networked = fetch(req).then((res) => {
        if (res && res.status === 200) {
          caches.open(CACHE_NAME).then((cache) => cache.put(req, res.clone()));
        }
        return res;
      }).catch(() => null);
      return cached || networked;
    })
  );
});
