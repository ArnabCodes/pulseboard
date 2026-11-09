// Service Worker for PulseBoard PWA — v19 "integration wave"
//
// Strategies
//   navigation : network-first -> cache -> inline offline page (a cold
//                first-run offline load shows a themed page, never a browser
//                network error)
//   feed JSON  : stale-while-revalidate — the cached pulse_feed.json is
//                served instantly and refreshed in the background, so the
//                dashboard paints with yesterday's data immediately and shows
//                fresh editorial content on the next render (v14-v16 waited
//                on the network on every load)
//   data JSON  : network-first (teachings_db.json), cache as offline fallback
//   article
//   images     : runtime cache-first in a dedicated cache (soft cap ~60
//                entries, LRU-ish trim) for known outlet CDNs; opaque
//                cross-origin responses are cached too, so cover images
//                survive offline
//   images     : stale-while-revalidate; opaque cross-origin responses are
//                cached too (opaque responses report status 0 — still
//                renderable; only genuine failures are skipped)
//   other      : stale-while-revalidate
//
// Update flow (v17): the worker still skipWaiting()s at install, but the old
// auto-reload of window clients on activate was REMOVED — a forced reload
// mid-read is hostile. Instead the page sets window.__pbUpdateReady = true on
// controllerchange (see the boot block in index.html) and the settings UI
// offers a Reload button. Updates otherwise apply on the next cold start.
//
// Messages (postMessage from the page):
//   { type: 'SKIP_WAITING' }  -> self.skipWaiting() (install already does
//                                this; the message is the on-demand path)
//   { type: 'PURGE_CACHES' }  -> deletes EVERY cache (settings "reset cached
//                                data"); the worker re-populates lazily
const CACHE_NAME = 'pulseboard-v20';
const IMAGE_CACHE_NAME = CACHE_NAME + '-img'; // runtime article-image cache
const IMAGE_CACHE_MAX = 60;                   // soft cap, LRU-ish trim
const ASSETS = [
  './',
  './manifest.json',
  './icon.svg',
  './icon-192.png',
  './icon-512.png',
  './icon-maskable-192.png',
  './icon-maskable-512.png',
  './apple-touch-icon.png',
  './pulse_feed.json',
  './teachings_db.json'
];

// Cross-origin article-image CDNs allowed into the runtime image cache.
// Suffix match, so cdn.arstechnica.net / *.nypost.com variants all match.
const ARTICLE_IMAGE_HOSTS = [
  'images.unsplash.com',
  'cdn.arstechnica.net',
  'platform.theverge.com',
  'i.guim.co.uk',
  'i.cbc.ca',
  'nypost.com'
];

// Minimal themed offline shell for the "nothing cached yet" first-run case.
const OFFLINE_HTML = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>Offline — PulseBoard</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { min-height: 100dvh; display: flex; align-items: center; justify-content: center;
         background: #04060b; color: #e2e8f0; text-align: center; padding: 24px;
         font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
  .frame { max-width: 380px; width: 100%; border: 1px solid rgba(255,255,255,0.08);
           border-radius: 20px; padding: 42px 26px; background: rgba(255,255,255,0.02); }
  .wordmark { font-family: Georgia, 'Times New Roman', serif; font-size: 13px;
              letter-spacing: 0.32em; text-transform: uppercase; color: #94a3b8; margin-bottom: 24px; }
  .wordmark::after { content: ''; display: block; width: 30px; height: 2px; background: #f59e0b; margin: 16px auto 0; }
  h1 { font-family: Georgia, serif; font-weight: 500; font-size: 22px; margin-bottom: 10px; color: #f8fafc; }
  p { font-size: 14px; line-height: 1.6; color: #94a3b8; margin-bottom: 26px; }
  a { display: inline-block; color: #f59e0b; text-decoration: none; font-weight: 600; font-size: 14px;
      padding: 11px 24px; border: 1px solid rgba(245,158,11,0.45); border-radius: 9999px; }
  a:active { background: #f59e0b; color: #04060b; }
</style>
</head>
<body>
<main class="frame">
  <div class="wordmark">PulseBoard</div>
  <h1>You&#39;re offline and nothing is cached yet.</h1>
  <p>The briefing couldn&#39;t be reached and no previous copy is stored on this device. Reconnect and try again.</p>
  <a href="./">Try again</a>
</main>
</body>
</html>`;

const offlinePage = () =>
  new Response(OFFLINE_HTML, {
    status: 200,
    headers: { 'Content-Type': 'text/html; charset=utf-8' }
  });

self.addEventListener('install', (e) => {
  self.skipWaiting();
  e.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(ASSETS))
  );
});

self.addEventListener('activate', (e) => {
  // Delete every cache that is not the current one — old app shells AND the
  // previous version's runtime image cache (IMAGE_CACHE_NAME carries the
  // version suffix, so it is rebuilt empty after every bump).
  e.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)));
    await self.clients.claim();
  })());
});

self.addEventListener('message', (e) => {
  const msg = e.data;
  if (!msg || typeof msg !== 'object') return;
  if (msg.type === 'SKIP_WAITING') self.skipWaiting();
  if (msg.type === 'PURGE_CACHES') {
    e.waitUntil((async () => {
      try {
        const keys = await caches.keys();
        await Promise.all(keys.map((k) => caches.delete(k)));
      } catch (err) { /* already gone */ }
    })());
  }
  if (msg.type === 'SHOW_NOTIFICATION' && msg.title && self.registration && self.registration.showNotification) {
    e.waitUntil(
      self.registration.showNotification(String(msg.title), {
        body: String(msg.body || ''),
        icon: './icon-192.png',
        badge: './icon-192.png',
        tag: String(msg.tag || 'pulseboard-alert'),
        renotify: Boolean(msg.renotify),
        data: { url: msg.url || './', lens: msg.lens || 'smart' }
      }).catch(() => {})
    );
  }
});

self.addEventListener('notificationclick', (e) => {
  e.notification.close();
  const data = (e.notification && e.notification.data) || {};
  const targetLens = data.lens || 'smart';
  e.waitUntil((async () => {
    const allClients = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const client of allClients) {
      if ('focus' in client) {
        await client.focus();
        client.postMessage({ type: 'NOTIFICATION_CLICK', lens: targetLens, url: data.url || '' });
        return;
      }
    }
    if (self.clients.openWindow) {
      await self.clients.openWindow(data.url || './');
    }
  })());
});

// Is this request an <img>-class fetch from an allowed article CDN?
function isArticleImageRequest(req) {
  try {
    const u = new URL(req.url);
    const isImage = req.destination === 'image' ||
      /\.(png|jpe?g|webp|gif|svg|avif)$/i.test(u.pathname);
    if (!isImage) return false;
    return ARTICLE_IMAGE_HOSTS.some(
      (d) => u.hostname === d || u.hostname.endsWith('.' + d)
    );
  } catch (err) {
    return false; // not a parseable URL -> fall through to generic handling
  }
}

// Runtime cache-first with a soft cap. Opaque (no-cors) responses are fine:
// they report status 0 but still render. Everything is best-effort — a cache
// failure must never break an image load.
async function runtimeImageCacheFirst(req) {
  let cache = null;
  try { cache = await caches.open(IMAGE_CACHE_NAME); } catch (err) { cache = null; }

  if (cache) {
    let cached = null;
    try { cached = await cache.match(req, { ignoreVary: true }); } catch (err) { cached = null; }
    if (cached) {
      // LRU-ish recency touch: re-insert so recently used entries sort last.
      try {
        const copy = cached.clone();
        await cache.delete(req, { ignoreVary: true });
        await cache.put(req, copy);
      } catch (err) { /* non-fatal */ }
      return cached;
    }
  }

  const netRes = await fetch(req); // may reject when offline

  if (cache && netRes && (netRes.ok || netRes.type === 'opaque')) {
    try {
      await cache.put(req, netRes.clone());
      // Soft cap: Cache.keys() is insertion-ordered in practice, so dropping
      // from the front evicts the least-recently-(re)inserted entries.
      const keys = await cache.keys();
      const excess = keys.length - IMAGE_CACHE_MAX;
      if (excess > 0) {
        await Promise.all(keys.slice(0, excess).map((k) => cache.delete(k)));
      }
    } catch (err) { /* non-fatal */ }
  }
  return netRes;
}

self.addEventListener('fetch', (e) => {
  const req = e.request;

  // Editorial feed: stale-while-revalidate. Serve the cached copy instantly,
  // refresh it in the background so the NEXT load is fresh. First run (no
  // cache yet) waits on the network like before.
  if (req.url.includes('pulse_feed.json')) {
    e.respondWith((async () => {
      let cache = null;
      try { cache = await caches.open(CACHE_NAME); } catch (err) { cache = null; }
      let cached = null;
      if (cache) {
        try { cached = await cache.match(req); } catch (err) { cached = null; }
      }
      const refresh = fetch(req, { cache: 'no-store' })
        .then((networkRes) => {
          if (networkRes && networkRes.status === 200 && cache) {
            const clone = networkRes.clone();
            const notifyClone = networkRes.clone();
            cache.put(req, clone).catch(() => {});
            notifyClone.json().then((data) => {
              if (data && data.generated_at) {
                self.clients.matchAll({ type: 'window' }).then((clients) => {
                  clients.forEach((client) => client.postMessage({ type: 'FEED_UPDATED', generated_at: data.generated_at }));
                }).catch(() => {});
              }
            }).catch(() => {});
          }
          return networkRes;
        })
        .catch(() => null);
      if (cached) {
        refresh.catch(() => {}); // refresh runs in the background, errors ignored
        return cached;
      }
      const net = await refresh;
      return net || cached || Response.error();
    })());
    return;
  }

  // Teachings: network-first, cache only as offline fallback (unchanged)
  if (req.url.includes('teachings_db.json')) {
    e.respondWith(
      fetch(req)
        .then((networkRes) => {
          if (networkRes && networkRes.status === 200) {
            const clone = networkRes.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(req, clone));
          }
          return networkRes;
        })
        .catch(() => caches.match(req))
    );
    return;
  }

  if (req.mode === 'navigate') {
    e.respondWith(
      fetch(req)
        .then((networkRes) => {
          if (networkRes && networkRes.ok) {
            // Clone twice up front: one copy for the toolbar check, one for
            // the cache — cloning after the page starts reading can throw.
            const forBody = networkRes.clone();
            const forCache = networkRes.clone();
            forBody.text().then((body) => {
              if (!/vercel\.com\/toolbar|\/_vercel\//i.test(body)) {
                caches.open(CACHE_NAME).then((cache) => cache.put(req, forCache));
              }
            }).catch(() => {});
          }
          return networkRes;
        })
        .catch(() =>
          caches.match(req).then((res) => res || caches.match('./') || offlinePage())
        )
    );
    return;
  }

  // Article cover images from known outlet CDNs: runtime cache-first with a
  // soft cap (see runtimeImageCacheFirst). Must run BEFORE the generic image
  // branch below.
  if (isArticleImageRequest(req)) {
    e.respondWith(runtimeImageCacheFirst(req));
    return;
  }

  // Images & icons: stale-while-revalidate. Cross-origin <img> loads are
  // no-cors and resolve to opaque responses (status 0) — still renderable,
  // so they are cached; only genuine failures are skipped.
  const u = new URL(req.url);
  const isImage = req.destination === 'image' ||
    /\.(png|jpe?g|webp|gif|svg|avif)$/i.test(u.pathname);
  if (isImage) {
    e.respondWith(
      caches.match(req).then((cached) => {
        const refresh = fetch(req).then((res) => {
          if (res && (res.ok || res.type === 'opaque')) {
            const clone = res.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(req, clone));
          }
          return res;
        }).catch(() => (cached || Response.error()));
        return cached || refresh;
      })
    );
    return;
  }

  // Stale-while-revalidate for other static assets
  e.respondWith(
    caches.match(req).then((cached) => {
      const networked = fetch(req).then((res) => {
        if (res && res.status === 200) {
          const clone = res.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(req, clone));
        }
        return res;
      }).catch(() => null);
      return cached || networked;
    })
  );
});
