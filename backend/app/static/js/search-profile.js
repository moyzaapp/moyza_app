/*
 * Perfil de búsqueda del comprador: ubicación en cascada y mínimo de ubicación
 * (PLAN_PERFIL_OBLIGATORIO.md, decisión 4; PLAN_PERFIL_UBICACION.md).
 *
 * Marcado: macro `search_profile_fields` de
 * templates/components/search_profile_form.html. El bloque de ubicación es
 * `[data-geo-cascade]` con:
 *   - `data-geo-source`: id del <script type="application/json"> con el árbol
 *     {país: {provincia: {población: [zonas]}}} (provincia deducida del CP;
 *     las poblaciones sin CP válido cuelgan de `data-no-province`, que no es
 *     una provincia elegible);
 *   - `select[data-geo="country"]` y `select[data-geo="province"]`;
 *   - `[data-geo-list="cities"]` y `[data-geo-list="zones"]`: casillas con
 *     "Todas" (`input[data-geo-all]`) y un `[data-geo-empty]` hermano.
 * El servidor ya pinta el estado inicial (perfil guardado); aquí solo se
 * reconstruyen los niveles cuando el agente cambia uno:
 *   país → provincias (y poblaciones y zonas), provincia → poblaciones (y
 *   zonas), poblaciones → zonas (las de las marcadas, o de todas si "Todas").
 * "Todas" marca y deshabilita las demás casillas (deshabilitadas no se
 * envían: lista vacía = Todas). Desmarcar la última casilla vuelve a "Todas".
 *
 * Mínimo de ubicación (con `data-places-required`): al enviar, si no hay
 * provincia ni ninguna población o zona concreta marcada, se cancela el envío,
 * se muestra el mensaje (`data-places-error`) y se enfoca la provincia. Se
 * ignora dentro de un <fieldset disabled> (el perfil del modal de seguimiento
 * solo cuenta con «Contactado»). Escucha en captura para adelantarse a la
 * guardia de doble envío de ui.js (`form[data-once]`).
 *
 * El servidor lo valida igualmente (buyer_matching.missing_profile_fields).
 *
 * Perfil obligatorio solo en Venta (PLAN_PERFIL_SOLO_VENTA.md). El bloque del
 * perfil es `[data-search-profile]` y trae la regla del servidor:
 *   - `data-required-operations`: JSON con las operaciones que exigen perfil
 *     (buyer_matching.profile_required_operations); los mínimos siguen al
 *     select de operación. Sin él, `data-profile-required` = obligatorio fijo.
 *   - `data-minimums-if-filled`: perfil opcional que, si se rellena algún dato
 *     (ni país ni operación cuentan), debe ir completo.
 * Al cambiar la operación o los datos se ponen o quitan `required` y el
 * asterisco de los campos `[data-profile-min]` (tipo y precio máximo) y de la
 * ubicación (`[data-profile-mark]`); el mínimo de ubicación solo se comprueba
 * mientras los mínimos se exigen.
 */
(function () {
    'use strict';

    var LABEL_CLASS = 'inline-flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 cursor-pointer hover:bg-gray-50';
    var CHECK_CLASS = 'w-4 h-4 rounded border-gray-300 text-gray-900 focus:ring-gray-900/30';

    // Mismo orden que el servidor (buyer_matching._sorted): sin acentos ni
    // mayúsculas y, a igualdad ('Jaen' / 'Jaén'), el texto exacto
    function byName(a, b) {
        return a.localeCompare(b, 'es', { sensitivity: 'base' }) || (a < b ? -1 : (a > b ? 1 : 0));
    }

    function uniquePush(list, value) {
        if (value && list.indexOf(value) === -1) list.push(value);
    }

    // ------------------------------------------------------------------ cascada

    function initCascade(block) {
        var source = document.getElementById(block.getAttribute('data-geo-source'));
        var tree = {};
        try { tree = source ? JSON.parse(source.textContent || '{}') : {}; } catch (err) { tree = {}; }
        var noProvince = block.getAttribute('data-no-province') || 'Sin provincia';
        var countrySelect = block.querySelector('select[data-geo="country"]');
        var provinceSelect = block.querySelector('select[data-geo="province"]');
        var citiesList = block.querySelector('[data-geo-list="cities"]');
        var zonesList = block.querySelector('[data-geo-list="zones"]');
        if (!provinceSelect || !citiesList || !zonesList) return;

        function branches() {
            var country = countrySelect ? countrySelect.value : '';
            if (country) return tree[country] ? [tree[country]] : [];
            return Object.keys(tree).map(function (key) { return tree[key]; });
        }

        // {población: [zonas]} de la provincia elegida (o de todas las del país)
        function cityZones() {
            var province = provinceSelect.value;
            var result = {};
            branches().forEach(function (branch) {
                Object.keys(branch).forEach(function (name) {
                    if (province && name !== province) return;
                    var cities = branch[name];
                    Object.keys(cities).forEach(function (city) {
                        if (!result[city]) result[city] = [];
                        cities[city].forEach(function (zone) { uniquePush(result[city], zone); });
                    });
                });
            });
            return result;
        }

        function allBox(list) { return list.querySelector('input[data-geo-all]'); }
        function items(list) { return Array.prototype.slice.call(list.querySelectorAll('input[type="checkbox"]:not([data-geo-all])')); }
        function checkedValues(list) {
            var all = allBox(list);
            if (all && all.checked) return [];
            return items(list).filter(function (i) { return i.checked; }).map(function (i) { return i.value; });
        }

        function applyAll(list) {
            var all = allBox(list);
            var on = !!(all && all.checked);
            items(list).forEach(function (input) {
                input.checked = on ? true : input.checked;
                input.disabled = on;
            });
        }

        // Rehace las casillas de una lista conservando lo marcado que siga existiendo
        function renderList(list, values, selected) {
            var name = list.getAttribute('data-geo-list');
            var all = allBox(list);
            var keep = selected.filter(function (v) { return values.indexOf(v) !== -1; });
            items(list).forEach(function (input) { list.removeChild(input.closest('label')); });
            values.forEach(function (value) {
                var label = document.createElement('label');
                label.className = LABEL_CLASS;
                var input = document.createElement('input');
                input.type = 'checkbox';
                input.name = name;
                input.value = value;
                input.className = CHECK_CLASS;
                input.checked = keep.indexOf(value) !== -1;
                label.appendChild(input);
                label.appendChild(document.createTextNode(' ' + value));
                list.appendChild(label);
            });
            if (all) all.checked = keep.length === 0;
            applyAll(list);
            var empty = list.parentNode.querySelector('[data-geo-empty]');
            if (empty) empty.classList.toggle('hidden', values.length > 0);
        }

        function renderZones() {
            var map = cityZones();
            var chosen = checkedValues(citiesList);
            var source = chosen.length ? chosen : Object.keys(map);
            var zones = [];
            source.forEach(function (city) { (map[city] || []).forEach(function (z) { uniquePush(zones, z); }); });
            renderList(zonesList, zones.sort(byName), checkedValues(zonesList));
        }

        function renderCities(selected) {
            renderList(citiesList, Object.keys(cityZones()).sort(byName), selected);
            renderZones();
        }

        function renderProvinces() {
            var names = [];
            branches().forEach(function (branch) {
                Object.keys(branch).forEach(function (name) { if (name !== noProvince) uniquePush(names, name); });
            });
            names.sort(byName);
            Array.prototype.slice.call(provinceSelect.options).forEach(function (option) {
                if (option.value) provinceSelect.removeChild(option);
            });
            names.forEach(function (name) {
                var option = document.createElement('option');
                option.value = name;
                option.textContent = name;
                provinceSelect.appendChild(option);
            });
            provinceSelect.value = '';
        }

        if (countrySelect) {
            countrySelect.addEventListener('change', function () {
                renderProvinces();
                renderCities([]);
            });
        }
        provinceSelect.addEventListener('change', function () { renderCities([]); });

        [citiesList, zonesList].forEach(function (list) {
            list.addEventListener('change', function (e) {
                var target = e.target;
                if (!target || target.type !== 'checkbox') return;
                if (target.hasAttribute('data-geo-all')) {
                    // Desmarcar "Todas" deja la lista sin marcar para elegir
                    if (!target.checked) items(list).forEach(function (input) { input.checked = false; });
                    applyAll(list);
                } else if (!items(list).some(function (input) { return input.checked; })) {
                    // Sin ninguna marcada = Todas
                    var all = allBox(list);
                    if (all) { all.checked = true; applyAll(list); }
                }
                if (list === citiesList) renderZones();
            });
        });
    }

    function initAll() {
        var blocks = document.querySelectorAll('[data-geo-cascade]');
        for (var i = 0; i < blocks.length; i++) initCascade(blocks[i]);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initAll);
    } else {
        initAll();
    }

    // ------------------------------------- mínimos según operación y datos
    // (PLAN_PERFIL_SOLO_VENTA.md). La regla viene del servidor: aquí no se
    // compara con ninguna operación concreta.

    // Campos que cuentan como "datos del perfil" (mismo criterio que
    // _profile_values_present en routes/alerts.py: ni país ni operación)
    var VALUE_NAMES = ['property_type', 'min_price', 'max_price', 'min_bedrooms', 'max_bedrooms', 'min_bathrooms', 'province'];

    function requiredOperations(root) {
        var raw = root.getAttribute('data-required-operations');
        if (raw === null) return null;
        try { return JSON.parse(raw) || []; } catch (err) { return []; }
    }

    function hasAnyValue(root) {
        var names = VALUE_NAMES.concat([root.getAttribute('data-notes-name') || 'notes']);
        for (var i = 0; i < names.length; i++) {
            var field = root.querySelector('[name="' + names[i] + '"]');
            if (field && !field.disabled && String(field.value || '').trim()) return true;
        }
        // Poblaciones o zonas concretas (con "Todas" van deshabilitadas y no cuentan)
        return root.querySelector('input[type="checkbox"][name]:checked:not(:disabled)') !== null;
    }

    // ¿Se exigen ahora los mínimos? Obligatorio (fijo o por la operación elegida)
    // o, si el perfil es opcional con `data-minimums-if-filled`, en cuanto hay datos
    function minimumsEnforced(root) {
        if (!root) return true;
        var ops = requiredOperations(root);
        var required;
        if (ops !== null) {
            var operation = root.querySelector('select[name="business_type"]');
            required = !!operation && ops.indexOf(operation.value) !== -1;
        } else {
            required = root.hasAttribute('data-profile-required');
        }
        return required || (root.hasAttribute('data-minimums-if-filled') && hasAnyValue(root));
    }

    // Asterisco del label de un campo (lo crea si el servidor lo pintó sin él)
    function setMark(root, field, on) {
        var label = field.id ? root.querySelector('label[for="' + field.id + '"]') : null;
        if (!label) return;
        var mark = label.querySelector('.text-red-500');
        if (!mark && on) {
            label.appendChild(document.createTextNode(' '));
            mark = document.createElement('span');
            mark.className = 'text-red-500';
            mark.setAttribute('aria-hidden', 'true');
            mark.textContent = '*';
            label.appendChild(mark);
        }
        if (mark) mark.classList.toggle('hidden', !on);
    }

    function syncMinimums(root) {
        var on = minimumsEnforced(root);
        Array.prototype.slice.call(root.querySelectorAll('[data-profile-min]')).forEach(function (field) {
            field.required = on;
            setMark(root, field, on);
        });
        Array.prototype.slice.call(root.querySelectorAll('[data-profile-mark]')).forEach(function (mark) {
            mark.classList.toggle('hidden', !on);
        });
        if (!on) {
            Array.prototype.slice.call(root.querySelectorAll('[data-places-required]')).forEach(function (block) {
                showError(block, false);
            });
        }
    }

    function syncAll() {
        var roots = document.querySelectorAll('[data-search-profile]');
        for (var i = 0; i < roots.length; i++) syncMinimums(roots[i]);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', syncAll);
    } else {
        syncAll();
    }

    // Cambiar la operación o rellenar/vaciar un dato pone o quita los mínimos
    ['change', 'input'].forEach(function (type) {
        document.addEventListener(type, function (e) {
            var target = e.target;
            if (!target || !target.closest) return;
            var root = target.closest('[data-search-profile]');
            if (root) syncMinimums(root);
        });
    });

    // ------------------------------------------------------- mínimo de ubicación

    function isActive(block) {
        if (block.closest('fieldset[disabled]')) return false;
        return minimumsEnforced(block.closest('[data-search-profile]'));
    }

    function errorFor(block) {
        var id = block.getAttribute('data-places-error');
        return id ? document.getElementById(id) : null;
    }

    // Provincia elegida, o al menos una población o zona concreta (no "Todas")
    function hasPlace(block) {
        var province = block.querySelector('select[data-geo="province"]');
        if (province && province.value) return true;
        return block.querySelector('input[type="checkbox"][name]:checked:not(:disabled)') !== null;
    }

    function showError(block, visible) {
        var error = errorFor(block);
        if (error) error.classList.toggle('hidden', !visible);
    }

    document.addEventListener('submit', function (e) {
        var form = e.target;
        if (!form.querySelectorAll) return;
        var blocks = form.querySelectorAll('[data-places-required]');
        for (var i = 0; i < blocks.length; i++) {
            var block = blocks[i];
            if (!isActive(block)) continue;
            if (hasPlace(block)) {
                showError(block, false);
                continue;
            }
            e.preventDefault();
            showError(block, true);
            var first = block.querySelector('select[data-geo="province"]') || block.querySelector('input[type="checkbox"]');
            if (first) first.focus();
            return;
        }
    }, true);

    // En cuanto elige provincia o marca una casilla, el aviso desaparece
    document.addEventListener('change', function (e) {
        var target = e.target;
        if (!target || !target.closest) return;
        var block = target.closest('[data-places-required]');
        if (block && hasPlace(block)) showError(block, false);
    });
})();
