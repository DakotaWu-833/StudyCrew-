/* Public code/shell only. Selected private task copies live separately in IndexedDB. */
const CACHE = "studycrew-static-v2";
const publicAsset = path => /^\/static\/workspace\/(main\.js|workspace\.css|assets\/[A-Za-z0-9_.-]+\.(js|css)|pwa\/icon-(192|512)\.png)$/.test(path);
self.addEventListener("install", event => event.waitUntil((async () => {
  try {
    const response = await fetch("/offline-assets.json", { cache: "no-store" });
    const data = await response.json(), cache = await caches.open(CACHE);
    const urls = data.assets.filter(value => { const url = new URL(value, self.location.origin); return url.origin === self.location.origin && (url.pathname === "/offline-workspace/" || publicAsset(url.pathname)); });
    await cache.addAll(urls);
  } catch { /* Online use remains available if the optional offline shell cannot install. */ }
  await self.skipWaiting();
})()));
self.addEventListener("activate", event => event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key.startsWith("studycrew-static-") && key !== CACHE).map(key => caches.delete(key)))).then(() => self.clients.claim())));
self.addEventListener("fetch", event => {
  const request = event.request, url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin) return;
  if (request.mode === "navigate") {
    event.respondWith(fetch(request).catch(async () => {
      if (/^\/app\/offline\/?$/.test(url.pathname)) { const shell = await caches.match("/offline-workspace/"); if (shell) return shell; }
      return new Response('<!doctype html><html lang="en"><meta name="viewport" content="width=device-width,initial-scale=1"><title>StudyCrew - offline</title><body><h1>You are offline</h1><p>Open the tasks you chose to keep on this device.</p><a href="/app/offline/">Open offline tasks</a><p>Reconnect to view the rest of your workspace.</p></body></html>', { status: 503, headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" } });
    })); return;
  }
  if (!publicAsset(url.pathname)) return;
  event.respondWith(fetch(request).then(async response => { if (response.ok && response.type === "basic") { const cache = await caches.open(CACHE); await cache.put(request, response.clone()); const keys = await cache.keys(); for (const key of keys.slice(0, Math.max(0, keys.length - 100))) { if (new URL(key.url).pathname !== "/offline-workspace/") await cache.delete(key); } } return response; }).catch(async () => (await caches.match(request)) || Response.error()));
});
