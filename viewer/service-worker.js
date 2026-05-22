const SHELL = 'autosplat-shell-v1';
const RUNTIME = 'autosplat-runtime-v1';
const SHELL_FILES = [
  './', './index.html', './css/style.css',
  './js/app.js', './js/viewer.js', './js/dropzone.js',
  './manifest.webmanifest', './assets/og-image.jpg',
  './icons/icon-192.png', './icons/icon-512.png'
];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(SHELL).then(c => c.addAll(SHELL_FILES))
    .then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then(keys =>
    Promise.all(keys.filter(k => k !== SHELL && k !== RUNTIME)
      .map(k => caches.delete(k)))).then(() => self.clients.claim()));
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;

  e.respondWith((async () => {
    // app shell: cache-first
    const shellHit = await caches.match(req, { ignoreSearch: true });
    if (shellHit) return shellHit;

    // runtime cache (CDN engine, demo splat): stale-while-revalidate
    const cached = await caches.open(RUNTIME).then(c => c.match(req));
    const network = fetch(req).then(async (res) => {
      if (res.ok) {
        const cache = await caches.open(RUNTIME);
        cache.put(req, res.clone());
      }
      return res;
    }).catch(() => cached);
    return cached || network;
  })());
});
