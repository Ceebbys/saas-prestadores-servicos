/**
 * Rich-text init: ativa Quill 2.x em todo <textarea data-rich-text="true">.
 *
 * Estratégia (progressive enhancement):
 *  1. Para cada textarea encontrada, cria uma <div> ao lado para o Quill;
 *  2. esconde a textarea original (mantém no DOM para o submit);
 *  3. sincroniza o HTML do Quill -> textarea a cada mudança e antes do submit;
 *  4. preserva valor inicial da textarea (renderiza HTML existente no editor).
 *
 * Sanitização: feita no backend (apps/proposals/sanitizer.py). Aqui não confiamos
 * no Quill como camada de segurança.
 */
(function () {
    "use strict";

    if (typeof window.Quill === "undefined") {
        // Quill ainda não carregou — pode acontecer se o script for incluído
        // antes do quill.js. Adia até DOMContentLoaded e tenta de novo.
        document.addEventListener("DOMContentLoaded", initAll);
        return;
    }
    document.addEventListener("DOMContentLoaded", initAll);

    function initAll() {
        if (typeof window.Quill === "undefined") {
            console.warn("Quill não está disponível — campos rich-text seguirão como textareas comuns.");
            return;
        }

        const SizeStyle = Quill.import("attributors/style/size");
        SizeStyle.whitelist = ["12px", "14px", "16px", "18px", "20px", "24px", "32px"];
        Quill.register(SizeStyle, true);

        const textareas = document.querySelectorAll(
            'textarea[data-rich-text="true"]'
        );
        textareas.forEach(initOne);
    }

    function initOne(textarea) {
        if (textarea.dataset.richTextInitialized === "1") {
            return;
        }
        textarea.dataset.richTextInitialized = "1";

        // Container do editor
        const container = document.createElement("div");
        container.className = "rich-text-editor mt-1 bg-white rounded-lg ring-1 ring-slate-300 overflow-hidden";
        container.style.minHeight = "180px";

        // Insere o container imediatamente após a textarea
        textarea.parentNode.insertBefore(container, textarea.nextSibling);

        // Esconde a textarea (mas mantém ela no DOM para o submit do form)
        textarea.style.display = "none";

        const toolbar = [
            [{ header: [1, 2, 3, false] }],
            [{ size: ["12px", "14px", "16px", "18px", "20px", "24px", "32px"] }],
            ["bold", "italic", "underline", "strike"],
            [{ align: [] }],
            [{ list: "ordered" }, { list: "bullet" }],
            ["blockquote", "link"],
            ["clean"],
        ];

        const editor = new Quill(container, {
            theme: "snow",
            modules: { toolbar: toolbar },
            placeholder: textarea.placeholder || "Digite o conteúdo...",
        });

        // Carrega valor inicial (HTML) da textarea para o editor
        const initialValue = textarea.value || "";
        if (initialValue.trim()) {
            // Quill espera Delta ou HTML via clipboard.dangerouslyPasteHTML
            editor.clipboard.dangerouslyPasteHTML(0, initialValue);
        }

        // Sincroniza editor -> textarea em tempo real
        editor.on("text-change", function () {
            // Quill produz "<p><br></p>" para conteúdo vazio — normaliza
            const html = editor.root.innerHTML;
            textarea.value = html === "<p><br></p>" ? "" : html;
        });

        // Defesa: garante sync antes do submit (caso text-change tenha race)
        const form = textarea.closest("form");
        if (form) {
            form.addEventListener("submit", function () {
                const html = editor.root.innerHTML;
                textarea.value = html === "<p><br></p>" ? "" : html;
            });
        }
    }
})();
