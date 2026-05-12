/**
 * realtime.js — cliente WebSocket para inbox + notificações.
 *
 * Conecta a /ws/inbox/ e /ws/notifications/, reconecta com backoff
 * exponencial, e expõe um event bus simples para o resto do JS.
 *
 * Uso pelo HTML:
 *   <body data-realtime-enabled="true">
 *   (esse atributo é setado pelo template authenticated.html)
 *
 * Eventos disparados em document via CustomEvent:
 *   v2b:inbox:message-new       — nova mensagem em qualquer conversa do tenant
 *   v2b:inbox:conv-updated      — Conversation alterada (status, assigned, etc.)
 *   v2b:notification:new        — nova notificação pessoal
 *
 * Componentes Alpine podem ouvir com:
 *   document.addEventListener('v2b:inbox:message-new', (e) => { ... })
 */
(function () {
  "use strict";

  if (!document.body || document.body.dataset.realtimeEnabled !== "true") {
    return;
  }

  function makeWsUrl(path) {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${window.location.host}${path}`;
  }

  /**
   * Cliente WS resiliente com reconnect exponencial (max 30s).
   * @param {string} path - ex.: '/ws/inbox/'
   * @param {object} handlers - { onMessage, onOpen, onClose }
   */
  function createClient(path, handlers) {
    let ws = null;
    let retries = 0;
    let closedExplicitly = false;
    let pingTimer = null;

    function connect() {
      if (closedExplicitly) return;
      try {
        ws = new WebSocket(makeWsUrl(path));
      } catch (err) {
        scheduleRetry();
        return;
      }
      ws.addEventListener("open", () => {
        retries = 0;
        if (handlers.onOpen) handlers.onOpen(ws);
        // Ping a cada 25s para manter conexão (alguns proxies fecham 30s idle)
        clearInterval(pingTimer);
        pingTimer = setInterval(() => {
          if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ action: "ping" }));
          }
        }, 25000);
      });
      ws.addEventListener("message", (event) => {
        let payload;
        try {
          payload = JSON.parse(event.data);
        } catch (e) {
          return;
        }
        if (handlers.onMessage) handlers.onMessage(payload, ws);
      });
      ws.addEventListener("close", () => {
        clearInterval(pingTimer);
        if (handlers.onClose) handlers.onClose();
        scheduleRetry();
      });
      ws.addEventListener("error", () => {
        // close será disparado em sequência; deixa o backoff lá
      });
    }

    function scheduleRetry() {
      if (closedExplicitly) return;
      retries += 1;
      const delay = Math.min(30000, 1000 * 2 ** Math.min(retries, 5));
      setTimeout(connect, delay);
    }

    function close() {
      closedExplicitly = true;
      clearInterval(pingTimer);
      if (ws) {
        try { ws.close(); } catch (e) { /* noop */ }
      }
    }

    function send(data) {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(data));
        return true;
      }
      return false;
    }

    return { connect, close, send };
  }

  function dispatch(name, detail) {
    document.dispatchEvent(new CustomEvent(name, { detail }));
  }

  // ---------------- Inbox ----------------
  const inbox = createClient("/ws/inbox/", {
    onMessage: (payload) => {
      switch (payload.type) {
        case "message.new":
          dispatch("v2b:inbox:message-new", payload);
          break;
        case "conversation.updated":
          dispatch("v2b:inbox:conv-updated", payload);
          break;
        case "subscribed":
        case "unsubscribed":
        case "pong":
          // controle interno; não propaga
          break;
        case "error":
          if (window.console) {
            console.warn("[realtime] inbox error:", payload);
          }
          break;
      }
    },
    onOpen: () => {
      // Auto-subscribe se a página atual tem um data-conversation-id
      const detailEl = document.querySelector("[data-current-conversation-id]");
      if (detailEl) {
        const cid = parseInt(detailEl.dataset.currentConversationId, 10);
        if (cid) {
          inbox.send({ action: "subscribe", conversation_id: cid });
        }
      }
    },
  });
  inbox.connect();

  // ---------------- Notificações ----------------
  const notif = createClient("/ws/notifications/", {
    onMessage: (payload) => {
      if (payload.type === "notification.new") {
        dispatch("v2b:notification:new", payload);
      }
    },
  });
  notif.connect();

  // Expõe para outros scripts (p.ex. componentes inline) caso precisem
  window.V2BRealtime = { inbox, notif };
})();
