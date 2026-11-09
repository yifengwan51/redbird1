// MoTrack service worker: makes the page installable and opens the shell
// offline.  Network first, so a fresh deploy is never hidden behind a cache;
// API calls and videos are never cached.
const CACHE = 'motrack-shell-v1';
const SHELL = ['/app/index.html', '/app/app.css', '/app/app.js', '/app/manifest.json', '/app/icons/icon-192.png'];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).catch(() => {}).then(() => self.skipWaiting()));
});
self.addEventListener('activate', (event) => {
  event.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.origin !== location.origin || !url.pathname.startsWith('/app/')) return;
  event.respondWith(fetch(event.request).then((res) => {
    if (res.ok && !res.redirected && SHELL.includes(url.pathname)) {
      const copy = res.clone();
      caches.open(CACHE).then((c) => c.put(event.request, copy));
    }
    return res;
  }).catch(() => caches.match(event.request).then((hit) => hit || caches.match('/app/index.html'))));
});
