/*
 * UI helpers MOYZA / MOES PREMIUM.
 *
 * Instalación: copiar a backend/app/static/js/ui.js y cargar en base.html antes del
 * cierre de <body>:  <script src="/static/js/ui.js"></script>
 *
 * Qué hace:
 *  - Modales accesibles: UI.openModal(id) / UI.closeModal(id). Cierra con Escape, con
 *    cualquier [data-modal-close] dentro del modal y con clic en el fondo. Mueve el foco
 *    al primer control y lo devuelve al elemento que abrió el modal.
 *  - Guardia de doble envío: <form data-once> desactiva el botón de envío al enviar y
 *    muestra "Guardando…" (o el texto de data-loading-text).
 *  - Botones [data-modal-open="id"] abren el modal sin JS en línea.
 *
 * Sin dependencias. Compatible con los modales antiguos (hidden/flex) mientras migran.
 */
window.UI = (function () {
    'use strict';

    var FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
    var openStack = [];   // { id, opener }

    function el(id) {
        return typeof id === 'string' ? document.getElementById(id) : id;
    }

    // ---- Modales ----------------------------------------------------------

    function openModal(id, opener) {
        var modal = el(id);
        if (!modal) return;
        modal.classList.remove('hidden');
        // Modales antiguos que usan display:flex en el contenedor
        if (modal.dataset.legacyFlex !== undefined) modal.classList.add('flex');
        modal.setAttribute('aria-hidden', 'false');
        document.body.classList.add('overflow-hidden');
        openStack.push({ id: modal.id, opener: opener || document.activeElement });

        var first = modal.querySelector('[autofocus]') || modal.querySelector(FOCUSABLE);
        if (first) setTimeout(function () { first.focus(); }, 20);
    }

    function closeModal(id) {
        var modal = el(id);
        if (!modal) return;
        modal.classList.add('hidden');
        modal.classList.remove('flex');
        modal.setAttribute('aria-hidden', 'true');

        var entry = null;
        for (var i = openStack.length - 1; i >= 0; i--) {
            if (openStack[i].id === modal.id) { entry = openStack.splice(i, 1)[0]; break; }
        }
        if (!openStack.length) document.body.classList.remove('overflow-hidden');
        if (entry && entry.opener && typeof entry.opener.focus === 'function') entry.opener.focus();
    }

    function closeTop() {
        if (openStack.length) closeModal(openStack[openStack.length - 1].id);
    }

    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && openStack.length) {
            e.preventDefault();
            closeTop();
        }
    });

    document.addEventListener('click', function (e) {
        var opener = e.target.closest('[data-modal-open]');
        if (opener) {
            e.preventDefault();
            openModal(opener.getAttribute('data-modal-open'), opener);
            return;
        }
        var closer = e.target.closest('[data-modal-close]');
        if (closer) {
            var modal = closer.closest('[role="dialog"]');
            if (modal) { e.preventDefault(); closeModal(modal.id); }
        }
    });

    // ---- Doble envío ------------------------------------------------------

    document.addEventListener('submit', function (e) {
        var form = e.target;
        if (!form.matches || !form.matches('form[data-once]')) return;
        if (e.defaultPrevented) return;
        var btn = form.querySelector('button[type="submit"], input[type="submit"]');
        if (!btn) return;
        var text = form.getAttribute('data-loading-text') || 'Guardando…';
        setTimeout(function () {
            btn.disabled = true;
            btn.setAttribute('aria-busy', 'true');
            if (btn.tagName === 'BUTTON') {
                btn.dataset.originalText = btn.innerHTML;
                btn.textContent = text;
            }
        }, 0);
        // Si la navegación no ocurre (p.ej. descarga), reactivar a los 8 s
        setTimeout(function () {
            btn.disabled = false;
            btn.removeAttribute('aria-busy');
            if (btn.dataset.originalText) btn.innerHTML = btn.dataset.originalText;
        }, 8000);
    });

    // ---- Utilidades -------------------------------------------------------

    function escapeHtml(text) {
        var div = document.createElement('div');
        div.textContent = text == null ? '' : String(text);
        return div.innerHTML;
    }

    return {
        openModal: openModal,
        closeModal: closeModal,
        closeTop: closeTop,
        escapeHtml: escapeHtml
    };
})();
