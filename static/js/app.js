/**
 * SaaS Prestadores - Main JS
 * Minimal JavaScript for HTMX enhancements
 */

// HTMX CSRF Token configuration
document.addEventListener('DOMContentLoaded', function () {
    // Set CSRF token for all HTMX requests
    document.body.addEventListener('htmx:configRequest', function (event) {
        const csrfToken = document.querySelector('meta[name="csrf-token"]');
        if (csrfToken) {
            event.detail.headers['X-CSRFToken'] = csrfToken.content;
        }
    });

    // Close modal on backdrop click
    document.body.addEventListener('click', function (event) {
        if (event.target.id === 'modal-backdrop') {
            closeModal();
        }
    });

    // Close modal on Escape key
    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape') {
            closeModal();
        }
    });

    // Auto-dismiss toasts after 5 seconds
    document.querySelectorAll('[data-auto-dismiss]').forEach(function (el) {
        const delay = parseInt(el.dataset.autoDismiss) || 5000;
        setTimeout(function () {
            el.classList.add('toast-exit');
            setTimeout(function () { el.remove(); }, 300);
        }, delay);
    });

    // Listen for HTMX afterSwap to re-init toasts
    document.body.addEventListener('htmx:afterSwap', function () {
        document.querySelectorAll('[data-auto-dismiss]:not([data-initialized])').forEach(function (el) {
            el.dataset.initialized = 'true';
            const delay = parseInt(el.dataset.autoDismiss) || 5000;
            setTimeout(function () {
                el.classList.add('toast-exit');
                setTimeout(function () { el.remove(); }, 300);
            }, delay);
        });
    });
});

// Modal helpers
function closeModal() {
    const container = document.getElementById('modal-container');
    if (container) {
        const backdrop = container.querySelector('.modal-backdrop');
        if (backdrop) {
            backdrop.style.opacity = '0';
            setTimeout(function () { container.innerHTML = ''; }, 150);
        } else {
            container.innerHTML = '';
        }
    }
}

// Pipeline drag and drop
function initDragDrop() {
    const cards = document.querySelectorAll('[data-draggable="opportunity"]');
    const columns = document.querySelectorAll('[data-drop-zone="stage"]');

    cards.forEach(function (card) {
        card.setAttribute('draggable', 'true');

        card.addEventListener('dragstart', function (e) {
            e.dataTransfer.setData('text/plain', card.dataset.opportunityId);
            card.classList.add('opacity-50');
        });

        card.addEventListener('dragend', function () {
            card.classList.remove('opacity-50');
        });
    });

    columns.forEach(function (column) {
        column.addEventListener('dragover', function (e) {
            e.preventDefault();
            column.classList.add('ring-2', 'ring-indigo-400', 'ring-opacity-50');
        });

        column.addEventListener('dragleave', function () {
            column.classList.remove('ring-2', 'ring-indigo-400', 'ring-opacity-50');
        });

        column.addEventListener('drop', function (e) {
            e.preventDefault();
            column.classList.remove('ring-2', 'ring-indigo-400', 'ring-opacity-50');
            const opportunityId = e.dataTransfer.getData('text/plain');
            const stageId = column.dataset.stageId;

            // Use HTMX to send the move request
            htmx.ajax('POST', '/crm/opportunities/' + opportunityId + '/move/', {
                values: { stage_id: stageId },
                target: '#pipeline-board',
                swap: 'innerHTML'
            });
        });
    });
}

// Re-initialize drag & drop after HTMX swaps
document.body.addEventListener('htmx:afterSettle', function (event) {
    if (event.detail.target.id === 'pipeline-board' || event.detail.target.closest('#pipeline-board')) {
        initDragDrop();
    }
});
