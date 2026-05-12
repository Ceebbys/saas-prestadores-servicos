/**
 * composer-templates.js — dropdown de templates no composer da inbox.
 *
 * Comportamento:
 * 1. Usuário digita '/' como primeiro char (ou apenas '/' isolado), abre dropdown.
 * 2. Continua digitando → filtra templates por nome/shortcut/conteúdo.
 * 3. Setas ↑↓ navegam; Enter seleciona; Esc fecha.
 * 4. Clica no botão "Templates" → abre dropdown sem filtro.
 * 5. Seleção: GET /inbox/templates/api/<id>/render/<conv_id>/ → substitui textarea.
 *
 * Sem dependência de Alpine — vanilla JS para inicializar em swaps HTMX.
 */
(function () {
  "use strict";

  function initComposer(textarea) {
    if (textarea.dataset.templatesInitialized === "true") return;
    textarea.dataset.templatesInitialized = "true";
    const conversationId = textarea.dataset.conversationId;
    const composer = textarea.closest("form");
    if (!composer) return;
    const dropdown = composer.querySelector("[data-template-dropdown]");
    const toggleBtn = composer.querySelector("[data-templates-toggle]");
    if (!dropdown) return;

    let isOpen = false;
    let templates = [];
    let activeIndex = 0;
    let filter = "";

    function getCsrfToken() {
      const meta = document.querySelector('meta[name="csrf-token"]');
      return meta ? meta.getAttribute("content") : "";
    }

    function getChannel() {
      const channelInput = document.getElementById("channel-" + conversationId);
      return channelInput ? channelInput.value : "";
    }

    async function fetchTemplates(q) {
      const channel = getChannel();
      const params = new URLSearchParams({ q: q || "", channel: channel || "" });
      try {
        const resp = await fetch(`/inbox/templates/api/search/?${params.toString()}`, {
          credentials: "same-origin",
        });
        if (!resp.ok) return [];
        const data = await resp.json();
        return data.templates || [];
      } catch (e) {
        return [];
      }
    }

    function renderDropdown() {
      if (templates.length === 0) {
        dropdown.innerHTML = `
          <div class="px-4 py-6 text-center text-xs text-slate-400">
            Nenhum template encontrado.
            <a href="/inbox/templates/create/" class="text-indigo-600 hover:underline ml-1">Criar?</a>
          </div>`;
        return;
      }
      dropdown.innerHTML = templates.map((t, i) => `
        <div class="template-row px-3 py-2 cursor-pointer border-b border-slate-100 last:border-b-0 ${i === activeIndex ? 'bg-indigo-50' : 'hover:bg-slate-50'}"
             data-template-id="${t.id}" data-template-index="${i}">
          <div class="flex items-center justify-between gap-2">
            <p class="text-sm font-medium text-slate-900 truncate">${escapeHtml(t.name)}</p>
            ${t.shortcut ? `<code class="text-[10px] bg-slate-100 px-1.5 py-0.5 rounded text-slate-600">/${escapeHtml(t.shortcut)}</code>` : ""}
          </div>
          <p class="text-xs text-slate-500 line-clamp-1 mt-0.5">${escapeHtml(t.preview)}</p>
        </div>
      `).join("");

      // Bind click handlers
      dropdown.querySelectorAll(".template-row").forEach((row) => {
        row.addEventListener("click", () => {
          const idx = parseInt(row.dataset.templateIndex, 10);
          selectTemplate(idx);
        });
      });
    }

    function escapeHtml(s) {
      const div = document.createElement("div");
      div.textContent = s || "";
      return div.innerHTML;
    }

    function open() {
      isOpen = true;
      dropdown.style.display = "block";
    }

    function close() {
      isOpen = false;
      dropdown.style.display = "none";
      filter = "";
      activeIndex = 0;
    }

    async function refresh(q) {
      filter = q || "";
      templates = await fetchTemplates(q);
      activeIndex = 0;
      renderDropdown();
    }

    async function selectTemplate(idx) {
      const tpl = templates[idx];
      if (!tpl) return;
      try {
        const resp = await fetch(
          `/inbox/templates/api/${tpl.id}/render/${conversationId}/`,
          { credentials: "same-origin" },
        );
        if (!resp.ok) {
          textarea.value = tpl.preview;  // fallback
          close();
          return;
        }
        const data = await resp.json();
        // Substitui se a textarea estiver vazia OU começa com '/' (estamos
        // navegando no shortcut). Caso contrário, insere no caret.
        const current = textarea.value;
        if (!current.trim() || current.trim().startsWith("/")) {
          textarea.value = data.rendered;
        } else {
          const start = textarea.selectionStart || 0;
          textarea.value = current.slice(0, start) + data.rendered + current.slice(start);
        }
        textarea.focus();
        textarea.dispatchEvent(new Event("input", { bubbles: true }));
        close();
      } catch (e) {
        console.error("[templates] select failed", e);
      }
    }

    // Input listener: detecta '/' como primeiro char
    textarea.addEventListener("input", async (e) => {
      const val = textarea.value;
      if (val.startsWith("/")) {
        const q = val.slice(1).trim();
        if (!isOpen) open();
        await refresh(q);
      } else {
        if (isOpen) close();
      }
    });

    // Teclas para navegar
    textarea.addEventListener("keydown", (e) => {
      if (!isOpen) return;
      if (e.key === "ArrowDown") {
        e.preventDefault();
        activeIndex = Math.min(activeIndex + 1, templates.length - 1);
        renderDropdown();
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        activeIndex = Math.max(activeIndex - 1, 0);
        renderDropdown();
      } else if (e.key === "Enter" && !e.shiftKey && templates.length > 0) {
        e.preventDefault();
        selectTemplate(activeIndex);
      } else if (e.key === "Escape") {
        close();
      }
    });

    // Clica fora → fecha
    document.addEventListener("click", (e) => {
      if (isOpen && !composer.contains(e.target)) close();
    });

    // Botão Templates → abre sem filtro
    if (toggleBtn) {
      toggleBtn.addEventListener("click", async (e) => {
        e.preventDefault();
        if (isOpen) {
          close();
        } else {
          open();
          await refresh("");
          textarea.focus();
        }
      });
    }
  }

  function initAll() {
    document.querySelectorAll("[data-composer-textarea]").forEach(initComposer);
  }

  document.addEventListener("DOMContentLoaded", initAll);
  // HTMX após swap (thread/composer re-renderiza)
  document.body.addEventListener("htmx:afterSwap", initAll);

  // Init imediato se DOM já pronto
  if (document.readyState !== "loading") initAll();
})();
