/*
 * UI helpers MOYZA / MOES PREMIUM.
 *
 * Se carga una sola vez en base.html (en <head>, no depende del DOM al cargar).
 *
 * Qué hace:
 *  - Modales accesibles: UI.openModal(id, opener) / UI.closeModal(id). Cierra con Escape,
 *    con cualquier [data-modal-close] dentro del modal y con clic en el fondo. Mueve el
 *    foco dentro del modal y lo devuelve al elemento que lo abrió. En pantallas táctiles
 *    no enfoca ningún campo al abrir (abriría el teclado y taparía medio modal); enfoca
 *    el panel, y el usuario toca el campo que quiera.
 *  - Hoja móvil: arrastrar hacia abajo la barra superior (o la cabecera) cierra el modal.
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

    function isTouch() {
        return window.matchMedia && window.matchMedia('(pointer: coarse)').matches;
    }

    function isMobileSheet() {
        return window.matchMedia && window.matchMedia('(max-width: 639px)').matches;
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

        var body = modal.querySelector('[data-modal-body]');
        if (body) body.scrollTop = 0;

        var panel = modal.querySelector('[data-modal-panel]');
        var explicit = modal.querySelector('[autofocus]');
        var target;
        if (isTouch()) {
            // No abrir el teclado solo por abrir el modal
            target = panel || modal.querySelector(FOCUSABLE);
        } else {
            target = explicit || modal.querySelector('input:not([type="hidden"]):not([disabled]), select:not([disabled]), textarea:not([disabled])') || modal.querySelector(FOCUSABLE) || panel;
        }
        if (target) setTimeout(function () { try { target.focus({ preventScroll: true }); } catch (e) { target.focus(); } }, 20);
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
        if (entry && entry.opener && typeof entry.opener.focus === 'function' && document.contains(entry.opener)) {
            try { entry.opener.focus({ preventScroll: true }); } catch (e) { entry.opener.focus(); }
        }
    }

    function closeTop() {
        if (openStack.length) closeModal(openStack[openStack.length - 1].id);
    }

    function isOpen(id) {
        var modal = el(id);
        return !!modal && !modal.classList.contains('hidden');
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

    // Hoja móvil: arrastrar hacia abajo desde la barra o la cabecera cierra el modal
    (function enableSwipeToClose() {
        var startY = null, startX = null, panel = null, dialog = null, dragging = false;

        document.addEventListener('touchstart', function (e) {
            if (!isMobileSheet()) return;
            var handle = e.target.closest('[data-modal-panel] > header, [data-modal-panel] > [aria-hidden="true"]');
            if (!handle) return;
            panel = handle.closest('[data-modal-panel]');
            dialog = panel && panel.closest('[role="dialog"]');
            if (!dialog) return;
            startY = e.touches[0].clientY;
            startX = e.touches[0].clientX;
            dragging = true;
            panel.style.transition = 'none';
        }, { passive: true });

        document.addEventListener('touchmove', function (e) {
            if (!dragging || !panel) return;
            var dy = e.touches[0].clientY - startY;
            var dx = Math.abs(e.touches[0].clientX - startX);
            if (dy > 0 && dy > dx) panel.style.transform = 'translateY(' + dy + 'px)';
        }, { passive: true });

        document.addEventListener('touchend', function (e) {
            if (!dragging || !panel) return;
            var dy = (e.changedTouches[0].clientY - startY);
            panel.style.transition = 'transform 150ms ease-out';
            if (dy > 90) {
                panel.style.transform = 'translateY(100%)';
                var toClose = dialog, p = panel;
                setTimeout(function () {
                    closeModal(toClose.id);
                    p.style.transform = '';
                    p.style.transition = '';
                }, 150);
            } else {
                panel.style.transform = '';
            }
            dragging = false; panel = null; dialog = null;
        });
    })();

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
        isOpen: isOpen,
        escapeHtml: escapeHtml
    };
})();
