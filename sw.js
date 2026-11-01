// Service Worker for PulseBoard PWA — v14 "reliability pack"
//
// Strategies
//   navigation : network-first -> cache -> inline offline page (a cold
//                first-run offline load shows a themed page, never a browser
//                network error)
//   data JSON  : network-first (fresh editorial feed), cache as offline fallback
//   images     : stale-while-revalidate; opaque cross-origin responses are
//                cached too, so cover images survive offline (v13 silently
//                dropped them — opaque responses report status 0)
//   other      : stale-while-revalidate
//
// Auto-update: when this version activates OVER an older pulseboard-v* cache
// (an update, not a first install), every open window client is navigated
// (reloaded) exactly once so the new worker takes effect immediately — with no
// app-side code. A reload loop is structurally impossible (activate fires once
// per worker instance) and an in-worker Set guards double-navigation. The
// classic sessionStorage guard is a page-side API a worker cannot read, so the
// one-shot guard lives in worker memory.
const CACHE_NAME = 'pulseboard-v15';
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

// One-shot reload guard for auto-update (per worker instance; see header note).
const reloadedClients = new Set();

self.addEventListener('activate', (e) => {
  e.waitUntil((async () => {
    const keys = await caches.keys();
    // An update = activating over an older pulseboard cache. A first install
    // has none, so its initial page load is never interrupted.
    const isUpdate = keys.some((k) => k.startsWith('pulseboard-') && k !== CACHE_NAME);
    await Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)));
    await self.clients.claim();
    if (isUpdate) {
      const wins = await self.clients.matchAll({ type: 'window', includeUncontrolled: false });
      for (const w of wins) {
        if (reloadedClients.has(w.id) || typeof w.navigate !== 'function') continue;
        if (!w.url || !w.url.startsWith('http')) continue;
        reloadedClients.add(w.id);
        try { await w.navigate(w.url); }
        catch (err) { /* navigate() unsupported or blocked: update applies next launch */ }
      }
    }
  })());
});

self.addEventListener('fetch', (e) => {
  const req = e.request;

  // Fresh editorial feed: network-first, cache only as offline fallback
  if (req.url.includes('pulse_feed.json') || req.url.includes('teachings_db.json')) {
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
