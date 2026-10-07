/*
 * Validación de alertas de comprador duplicadas (lado cliente).
 *
 * Lo usan los dos formularios que crean alertas: el modal de /alerts y el
 * modal rápido de la ficha del comprador. Consulta al servidor y pinta un
 * aviso dentro del modal; la decisión final (crear igualmente, ver la alerta
 * o registrar un nuevo contacto sobre la existente) la toma el usuario.
 *
 * El servidor repite la validación al recibir el formulario, así que esto
 * es solo la capa de aviso temprano.
 */
window.AlertDuplicates = (function () {
    'use strict';

    function escapeHtml(text) {
        var div = document.createElement('div');
        div.textContent = text == null ? '' : String(text);
        return div.innerHTML;
    }

    // ---- Consultas --------------------------------------------------------

    function checkAlerts(buyerId, propertyId) {
        var url = '/alerts/check-duplicate?buyer_id=' + encodeURIComponent(buyerId)
            + '&property_id=' + encodeURIComponent(propertyId);
        return fetch(url)
            .then(function (r) { return r.ok ? r.json() : { open: [], recent_closed: [] }; })
            .catch(function () { return { open: [], recent_closed: [] }; });
    }

    function checkBuyer(phone, email) {
        var url = '/alerts/check-buyer?phone=' + encodeURIComponent(phone || '')
            + '&email=' + encodeURIComponent(email || '');
        return fetch(url)
            .then(function (r) { return r.ok ? r.json() : { results: [] }; })
            .then(function (data) { return data.results || []; })
            .catch(function () { return []; });
    }

    // ---- Render -----------------------------------------------------------

    var ICON_WARN = '<svg class="w-5 h-5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">'
        + '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path></svg>';
    var ICON_INFO = '<svg class="w-5 h-5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">'
        + '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>';

    function alertMeta(a) {
        var parts = [];
        if (a.created_at) parts.push('Creada el ' + a.created_at + (a.created_by ? ' por ' + a.created_by : ''));
        if (a.source) parts.push('Origen: ' + a.source);
        if (a.status_label) parts.push('Estado: ' + a.status_label);
        if (a.agent) parts.push('Agente: ' + a.agent);
        if (a.follow_ups) parts.push(a.follow_ups + (a.follow_ups === 1 ? ' seguimiento' : ' seguimientos'));
        return parts.map(escapeHtml).join(' · ');
    }

    function renderOpen(alerts, opts) {
        var title = alerts.length === 1
            ? 'Ya existe una alerta abierta para este comprador en esta propiedad'
            : 'Ya existen ' + alerts.length + ' alertas abiertas para este comprador en esta propiedad';

        var items = alerts.map(function (a) {
            var actions = '<a href="' + escapeHtml(a.url) + '" target="_blank" rel="noopener" '
                + 'class="inline-flex items-center px-3 py-1.5 rounded-lg border border-amber-300 bg-white text-amber-800 text-xs font-medium hover:bg-amber-100 transition-colors">'
                + 'Ver alerta #' + escapeHtml(a.id) + '</a>';
            if (opts.allowRegisterContact !== false) {
                actions += '<button type="button" data-register-contact="' + escapeHtml(a.id) + '" '
                    + 'class="inline-flex items-center px-3 py-1.5 rounded-lg bg-amber-600 text-white text-xs font-medium hover:bg-amber-700 transition-colors">'
                    + 'Registrar como nuevo contacto en esta alerta</button>';
            }
            return '<li class="pt-2">'
                + '<p class="text-xs text-amber-900">' + alertMeta(a) + '</p>'
                + '<div class="flex flex-wrap gap-2 mt-2">' + actions + '</div>'
                + '</li>';
        }).join('');

        return '<div class="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-amber-900">'
            + '<div class="flex items-start gap-3">' + ICON_WARN
            + '<div class="flex-1 min-w-0">'
            + '<p class="text-sm font-semibold">' + escapeHtml(title) + '</p>'
            + '<ul class="divide-y divide-amber-200">' + items + '</ul>'
            + '<p class="text-xs text-amber-800 mt-3">Si aun así quieres registrar otra alerta, pulsa <strong>'
            + escapeHtml(opts.forceLabel || 'Crear de todas formas') + '</strong>. Quedará anotado que es un duplicado confirmado.</p>'
            + '</div></div></div>';
    }

    function renderRecentClosed(alerts, recentDays) {
        var items = alerts.map(function (a) {
            var when = a.completed_at ? 'cerrada el ' + a.completed_at : 'creada el ' + a.created_at;
            return '<li class="flex flex-wrap items-center justify-between gap-2 pt-1">'
                + '<span class="text-xs">Alerta #' + escapeHtml(a.id) + ' ' + escapeHtml(when)
                + ' (' + escapeHtml(a.status_label) + (a.source ? ', origen ' + escapeHtml(a.source) : '') + ')</span>'
                + '<a href="' + escapeHtml(a.url) + '" target="_blank" rel="noopener" class="text-xs font-medium underline hover:no-underline">Ver alerta</a>'
                + '</li>';
        }).join('');

        return '<div class="rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-blue-900">'
            + '<div class="flex items-start gap-3">' + ICON_INFO
            + '<div class="flex-1 min-w-0">'
            + '<p class="text-sm font-semibold">Este comprador ya tuvo una alerta en esta propiedad en los últimos '
            + escapeHtml(recentDays || 30) + ' días</p>'
            + '<ul class="mt-1">' + items + '</ul>'
            + '<p class="text-xs text-blue-800 mt-2">Está cerrada, así que puedes crear una nueva con normalidad.</p>'
            + '</div></div></div>';
    }

    /**
     * Pinta el aviso de alertas existentes en `container`.
     *
     * opts:
     *   forceLabel            texto del botón de envío cuando hay duplicado abierto
     *   allowRegisterContact  false para ocultar "Registrar como nuevo contacto"
     *   getContactPayload()   devuelve {source, notes, priority} para ese registro
     *
     * Devuelve true si hay duplicados abiertos.
     */
    function renderAlertBanner(container, data, opts) {
        opts = opts || {};
        var open = (data && data.open) || [];
        var closed = (data && data.recent_closed) || [];

        if (!open.length && !closed.length) {
            container.innerHTML = '';
            container.classList.add('hidden');
            return false;
        }

        var html = '';
        if (open.length) html += renderOpen(open, opts);
        if (closed.length) html += (html ? '<div class="mt-2"></div>' : '') + renderRecentClosed(closed, data.recent_days);

        container.innerHTML = html;
        container.classList.remove('hidden');

        container.querySelectorAll('[data-register-contact]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var payload = typeof opts.getContactPayload === 'function' ? opts.getContactPayload() : {};
                submitRegisterContact(btn.getAttribute('data-register-contact'), payload);
            });
        });

        return open.length > 0;
    }

    /**
     * Pinta el aviso de comprador ya registrado (modo "Nuevo comprador").
     * opts.onUse(buyer) se llama al pulsar "Usar este comprador".
     * Devuelve true si hay coincidencias.
     */
    function renderBuyerBanner(container, buyers, opts) {
        opts = opts || {};
        if (!buyers || !buyers.length) {
            container.innerHTML = '';
            container.classList.add('hidden');
            return false;
        }

        var items = buyers.map(function (b, i) {
            var meta = [b.phone, b.email].filter(Boolean).join(' · ');
            return '<li class="flex flex-wrap items-center justify-between gap-2 pt-2">'
                + '<div class="min-w-0"><p class="text-sm font-medium">' + escapeHtml(b.name) + '</p>'
                + (meta ? '<p class="text-xs text-amber-800">' + escapeHtml(meta) + '</p>' : '') + '</div>'
                + '<button type="button" data-use-buyer="' + i + '" '
                + 'class="inline-flex items-center px-3 py-1.5 rounded-lg bg-amber-600 text-white text-xs font-medium hover:bg-amber-700 transition-colors">'
                + 'Usar este comprador</button>'
                + '</li>';
        }).join('');

        container.innerHTML = '<div class="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-amber-900">'
            + '<div class="flex items-start gap-3">' + ICON_WARN
            + '<div class="flex-1 min-w-0">'
            + '<p class="text-sm font-semibold">Ya hay un comprador registrado con este teléfono o correo</p>'
            + '<ul class="divide-y divide-amber-200">' + items + '</ul>'
            + '<p class="text-xs text-amber-800 mt-3">Si es otra persona, pulsa <strong>'
            + escapeHtml(opts.forceLabel || 'Crear como comprador nuevo') + '</strong>.</p>'
            + '</div></div></div>';
        container.classList.remove('hidden');

        container.querySelectorAll('[data-use-buyer]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                if (typeof opts.onUse === 'function') opts.onUse(buyers[Number(btn.getAttribute('data-use-buyer'))]);
            });
        });

        return true;
    }

    // ---- Botón de envío ---------------------------------------------------

    var FORCE_CLASSES = ['bg-amber-600', 'hover:bg-amber-700'];
    var NORMAL_CLASSES = ['bg-blue-600', 'hover:bg-blue-700'];

    /**
     * Cambia el botón de envío a modo "forzar" (texto y color ámbar) y marca
     * el campo oculto de confirmación, o lo devuelve a su estado normal.
     */
    function setForceMode(button, hiddenInput, forced, label) {
        if (!button) return;
        if (!button.dataset.normalLabel) button.dataset.normalLabel = button.textContent.trim();
        if (forced) {
            button.textContent = label || 'Crear de todas formas';
            NORMAL_CLASSES.forEach(function (c) { button.classList.remove(c); });
            FORCE_CLASSES.forEach(function (c) { button.classList.add(c); });
            if (hiddenInput) hiddenInput.value = '1';
        } else {
            button.textContent = button.dataset.normalLabel;
            FORCE_CLASSES.forEach(function (c) { button.classList.remove(c); });
            NORMAL_CLASSES.forEach(function (c) { button.classList.add(c); });
            if (hiddenInput) hiddenInput.value = '';
        }
    }

    // ---- Registrar nuevo contacto sobre la alerta existente ----------------

    function submitRegisterContact(alertId, payload) {
        payload = payload || {};
        var form = document.createElement('form');
        form.method = 'POST';
        form.action = '/alerts/' + encodeURIComponent(alertId) + '/register-contact';
        form.style.display = 'none';

        ['source', 'notes', 'priority'].forEach(function (name) {
            var input = document.createElement('input');
            input.type = 'hidden';
            input.name = name;
            input.value = payload[name] == null ? '' : payload[name];
            form.appendChild(input);
        });

        document.body.appendChild(form);
        form.submit();
    }

    return {
        checkAlerts: checkAlerts,
        checkBuyer: checkBuyer,
        renderAlertBanner: renderAlertBanner,
        renderBuyerBanner: renderBuyerBanner,
        setForceMode: setForceMode,
        submitRegisterContact: submitRegisterContact
    };
})();
