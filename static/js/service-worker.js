/**
 * service-worker.js — handler de Web Push da ServiçoPro.
 *
 * Registrado por static/js/push.js após o user dar permissão.
 * Recebe pushes do backend via VAPID, mostra notificação nativa,
 * e ao clicar abre/foca a aba com a URL alvo.
 */
self.addEventListener("install", (event) => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("push", (event) => {
  if (!event.data) return;
  let payload;
  try {
    payload = event.data.json();
  } catch (e) {
    payload = { title: "ServiçoPro", body: event.data.text() };
  }
  const title = payload.title || "ServiçoPro";
  const options = {
    body: payload.body || "",
    icon: "/static/img/icon-192.png",
    badge: "/static/img/badge-72.png",
    tag: payload.tag || undefined,
    data: { url: payload.url || "/" },
    requireInteraction: false,
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true })
      .then((clientList) => {
        // Se já tem janela aberta na origin, foca + navega
        for (const client of clientList) {
          if ("focus" in client) {
            client.focus();
            if ("navigate" in client) {
              try { client.navigate(url); } catch (e) { /* noop */ }
            }
            return;
          }
        }
        if (self.clients.openWindow) {
          return self.clients.openWindow(url);
        }
      })
  );
});
