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

    // ---- Tablas ordenables por columna ------------------------------------
    //
    // <table class="js-sortable" data-table-id="teamTable">
    //   <th data-sort-type="number|text" data-sort-key="capt" [data-sort-col="3"]>…</th>
    //   <td data-sort-value="42">…</td>
    //
    // Primer clic: números de mayor a menor, texto de A a Z. Las celdas sin
    // valor (data-sort-value vacío) van siempre al final. Con data-table-id el
    // último orden se recuerda en el navegador. data-sort-col solo hace falta
    // cuando la cabecera tiene varias filas (colspan/rowspan) y cellIndex no
    // coincide con la columna real.

    function sortableTables(root) {
        (root || document).querySelectorAll('table.js-sortable').forEach(initSortable);
    }

    function initSortable(table) {
        if (table.dataset.sortReady) return;
        table.dataset.sortReady = '1';
        var tbody = table.tBodies[0];
        if (!tbody) return;
        var headers = Array.prototype.slice.call(table.querySelectorAll('thead th[data-sort-type]'));
        var storeKey = table.dataset.tableId ? 'sort:' + table.dataset.tableId : null;

        function colOf(th) {
            return th.dataset.sortCol !== undefined ? parseInt(th.dataset.sortCol, 10) : th.cellIndex;
        }

        function setIndicator(th, dir) {
            var ind = th.querySelector('.sort-indicator');
            if (!ind) return;
            ind.textContent = dir === 'asc' ? '↑' : dir === 'desc' ? '↓' : '↕';
            ind.classList.toggle('text-gray-400', !dir);
            ind.classList.toggle('text-gray-900', !!dir);
        }

        function apply(th, dir) {
            var col = colOf(th);
            var type = th.dataset.sortType;
            headers.forEach(function (h) {
                delete h.dataset.sortDir;
                h.setAttribute('aria-sort', 'none');
                setIndicator(h, null);
            });
            th.dataset.sortDir = dir;
            th.setAttribute('aria-sort', dir === 'asc' ? 'ascending' : 'descending');
            setIndicator(th, dir);

            var rows = Array.prototype.filter.call(tbody.rows, function (row) {
                return row.cells.length > col && !row.hasAttribute('data-no-sort');
            });
            rows.sort(function (a, b) {
                var va = a.cells[col].dataset.sortValue || '';
                var vb = b.cells[col].dataset.sortValue || '';
                if (va === '' && vb === '') return 0;
                if (va === '') return 1;
                if (vb === '') return -1;
                var cmp = type === 'number'
                    ? parseFloat(va) - parseFloat(vb)
                    : va.localeCompare(vb, 'es', { numeric: true, sensitivity: 'base' });
                return dir === 'asc' ? cmp : -cmp;
            });
            rows.forEach(function (row) { tbody.appendChild(row); });

            if (storeKey) {
                try { window.localStorage.setItem(storeKey, JSON.stringify({ key: th.dataset.sortKey || String(col), dir: dir })); } catch (e) { /* sin almacenamiento */ }
            }
        }

        function toggle(th) {
            var type = th.dataset.sortType;
            var dir = th.dataset.sortDir === 'asc' ? 'desc'
                    : th.dataset.sortDir === 'desc' ? 'asc'
                    : (type === 'number' ? 'desc' : 'asc');
            apply(th, dir);
        }

        headers.forEach(function (th) {
            th.classList.add('cursor-pointer', 'select-none', 'hover:text-gray-900');
            th.setAttribute('aria-sort', 'none');
            th.tabIndex = 0;
            if (!th.querySelector('.sort-indicator')) {
                var ind = document.createElement('span');
                ind.className = 'sort-indicator ml-1 text-gray-400';
                ind.setAttribute('aria-hidden', 'true');
                ind.textContent = '↕';
                th.appendChild(ind);
            }
            th.addEventListener('click', function () { toggle(th); });
            th.addEventListener('keydown', function (e) {
                if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(th); }
            });
        });

        // Reaplicar el último orden elegido en este navegador
        if (storeKey) {
            try {
                var saved = JSON.parse(window.localStorage.getItem(storeKey) || 'null');
                if (saved && saved.key) {
                    var match = headers.filter(function (h) { return (h.dataset.sortKey || String(colOf(h))) === saved.key; })[0];
                    if (match) apply(match, saved.dir === 'asc' ? 'asc' : 'desc');
                }
            } catch (e) { /* ignorar */ }
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () { sortableTables(document); });
    } else {
        sortableTables(document);
    }

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
        sortableTables: sortableTables,
        escapeHtml: escapeHtml
    };
})();
