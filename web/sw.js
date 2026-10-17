// remy service worker: makes the app installable and lets the shell open offline.
// Shell: network-first, cache fallback (so a deploy is picked up on the next load).
// API: network only. Bump CACHE when the shell's file list changes.
const CACHE = "remy-shell-v19";
const SHELL = ["/", "/app.css", "/app.js", "/home.css", "/home.js", "/tokens.css", "/manifest.webmanifest", "/icons/icon-192.png", "/icons/icon-512.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin || url.pathname.startsWith("/api/")) return;
  const key = e.request.mode === "navigate" ? "/" : e.request;
  e.respondWith(
    fetch(e.request)
      .then((res) => {
        if (res.ok) caches.open(CACHE).then((c) => c.put(key, res.clone()));
        return res;
      })
      .catch(() => caches.match(key))
  );
});
