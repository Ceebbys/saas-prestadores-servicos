/**
 * push.js — cliente Web Push.
 *
 * 1. Registra o service worker
 * 2. Pega VAPID public key do backend
 * 3. Chama Notification.requestPermission + PushManager.subscribe
 * 4. POST /inbox/notifications/push-subscribe/ com a subscription
 *
 * Disparado por um botão "Ativar notificações" (data-action="enable-push")
 * em qualquer página autenticada.
 */
(function () {
  "use strict";

  if (typeof window === "undefined") return;
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
    return;
  }

  /** Converte base64url para Uint8Array (formato exigido pelo subscribe). */
  function urlBase64ToUint8Array(base64String) {
    const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
    const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
    const raw = atob(base64);
    const out = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; ++i) out[i] = raw.charCodeAt(i);
    return out;
  }

  function getCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute("content") : "";
  }

  async function getVapidKey() {
    const resp = await fetch("/inbox/notifications/vapid-public-key/", {
      credentials: "same-origin",
    });
    if (!resp.ok) return null;
    const data = await resp.json();
    return data.enabled ? data.publicKey : null;
  }

  async function registerSW() {
    return navigator.serviceWorker.register("/static/js/service-worker.js");
  }

  async function subscribeUser() {
    const publicKey = await getVapidKey();
    if (!publicKey) {
      console.warn("[push] VAPID_PUBLIC_KEY ausente no backend; push desabilitado.");
      return null;
    }
    const reg = await registerSW();
    let sub = await reg.pushManager.getSubscription();
    if (!sub) {
      sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(publicKey),
      });
    }
    // Manda para o backend
    const resp = await fetch("/inbox/notifications/push-subscribe/", {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": getCsrfToken(),
      },
      body: JSON.stringify(sub.toJSON()),
    });
    if (!resp.ok) {
      console.warn("[push] subscribe falhou no backend", resp.status);
      return null;
    }
    return sub;
  }

  async function unsubscribeUser() {
    const reg = await navigator.serviceWorker.getRegistration();
    if (!reg) return;
    const sub = await reg.pushManager.getSubscription();
    if (!sub) return;
    const endpoint = sub.endpoint;
    await sub.unsubscribe();
    await fetch("/inbox/notifications/push-unsubscribe/", {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": getCsrfToken(),
      },
      body: JSON.stringify({ endpoint }),
    });
  }

  /** Expõe para botões inline e Alpine. */
  window.V2BPush = {
    async enable() {
      if (Notification.permission === "denied") {
        alert("Notificações estão bloqueadas no seu navegador.");
        return false;
      }
      if (Notification.permission !== "granted") {
        const result = await Notification.requestPermission();
        if (result !== "granted") return false;
      }
      const sub = await subscribeUser();
      return !!sub;
    },
    disable: unsubscribeUser,
  };

  // Auto-bind em botões com data-action
  document.addEventListener("click", async (event) => {
    const target = event.target.closest('[data-action="enable-push"]');
    if (!target) return;
    event.preventDefault();
    target.disabled = true;
    try {
      const ok = await window.V2BPush.enable();
      if (ok) {
        target.textContent = "Notificações ativadas ✓";
      } else {
        target.disabled = false;
      }
    } catch (e) {
      console.error("[push] enable failed", e);
      target.disabled = false;
    }
  });
})();
