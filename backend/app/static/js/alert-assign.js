/*
 * Bloque "Agente asignado" de las alertas de comprador (PLAN_ASIGNACION_ALERTAS.md).
 *
 * Marcado: macro `assign_fields` de templates/alerts/assign_fields.html. Uso:
 *
 *   var assign = AlertAssign.init('qa');            // prefijo de los ids
 *   assign.setOwner(12, 'Laura');                   // al elegir la propiedad (alta)
 *   assign.setCurrent(12, 'Laura');                 // al abrir la reasignación
 *   assign.clear();                                 // al quitar la propiedad
 *
 * Modo "create" (alta): el select parte del captador de la propiedad; si se
 * elige otro, aviso ámbar "La alerta irá a X y no a Y" y campo Motivo
 * (opcional). Modo "reassign": el agente actual no se puede elegir y el
 * motivo está siempre visible. En los dos, si el agente elegido no pertenece
 * a la empresa activa, se avisa de que se le dará acceso (decisión §4-1 B).
 *
 * Para el agente (sin select) solo se muestra "Se asignará a {captador}".
 * Todo el texto se escribe con textContent: sin innerHTML.
 */
window.AlertAssign = (function () {
    'use strict';

    function $(id) { return document.getElementById(id); }

    function init(prefix) {
        var root = $(prefix + 'AssignBlock');
        if (!root) return null;

        var mode = root.dataset.mode || 'create';
        var companyId = root.dataset.companyId || '';
        var companyName = root.dataset.companyName || '';
        var select = $(prefix + 'AgentSelect');
        var hint = $(prefix + 'AssignHint');
        var warn = $(prefix + 'AssignWarn');
        var warnText = $(prefix + 'AssignWarnText');
        var warnCompany = $(prefix + 'AssignWarnCompany');
        var reasonWrap = $(prefix + 'ReasonWrap');
        var reason = $(prefix + 'Reason');
        var infoName = $(prefix + 'AssignInfoName');

        var ownerId = '';
        var ownerName = '';

        function show(el, on) { if (el) el.classList.toggle('hidden', !on); }

        function chosenOption() {
            if (!select || !select.value) return null;
            return select.options[select.selectedIndex];
        }

        function belongs(option) {
            var ids = (option.dataset.companies || '').split(',');
            return ids.indexOf(String(companyId)) !== -1;
        }

        function sync() {
            if (!select) return;
            var option = chosenOption();
            var name = option ? option.dataset.name : '';
            var differs = !!option && String(select.value) !== String(ownerId);
            var noAccess = !!option && !belongs(option);

            if (mode === 'reassign') {
                hint.textContent = ownerName ? 'Ahora la atiende ' + ownerName + '.' : '';
                show(hint, !!ownerName);
                warnText.textContent = '';
                show(warnText, false);
                show(reasonWrap, true);
            } else {
                if (!ownerId) {
                    hint.textContent = 'La propiedad no tiene agente captador: elige quién atenderá al comprador.';
                } else {
                    hint.textContent = 'Agente de la propiedad';
                }
                show(hint, !ownerId || !differs);
                warnText.textContent = (differs && ownerId)
                    ? 'La alerta irá a ' + name + ' y no a ' + ownerName + ', agente de la propiedad.'
                    : '';
                show(warnText, differs && !!ownerId);
                show(reasonWrap, !!option && (differs || !ownerId));
                if (!(differs || !ownerId) && reason) reason.value = '';
            }

            warnCompany.textContent = noAccess
                ? name + ' no pertenece a ' + companyName + '; al asignarle se le dará acceso a ' + companyName + '.'
                : '';
            show(warnCompany, noAccess);
            show(warn, (mode !== 'reassign' && differs && !!ownerId) || noAccess);
        }

        function reset() {
            if (reason) reason.value = '';
            if (select) {
                Array.prototype.forEach.call(select.options, function (opt) { opt.disabled = false; });
            }
        }

        if (select) select.addEventListener('change', sync);

        return {
            // Alta: preselecciona el captador de la propiedad
            setOwner: function (id, name) {
                reset();
                ownerId = id ? String(id) : '';
                ownerName = name || '';
                if (select) {
                    select.required = true;
                    select.value = ownerId;
                    if (select.value !== ownerId) select.value = '';
                }
                if (infoName) infoName.textContent = ownerName;
                show(root, true);
                sync();
            },
            // Reasignación: el agente actual no se puede volver a elegir
            setCurrent: function (id, name) {
                reset();
                ownerId = id ? String(id) : '';
                ownerName = name || '';
                if (select) {
                    select.value = '';
                    Array.prototype.forEach.call(select.options, function (opt) {
                        opt.disabled = opt.value !== '' && opt.value === ownerId;
                    });
                }
                show(root, true);
                sync();
            },
            clear: function () {
                reset();
                ownerId = '';
                ownerName = '';
                if (select) {
                    select.value = '';
                    if (mode !== 'reassign') select.required = false;
                }
                if (mode !== 'reassign') show(root, false);
                sync();
            }
        };
    }

    return { init: init };
})();
