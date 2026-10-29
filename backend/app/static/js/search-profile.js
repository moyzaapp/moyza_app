/*
 * Perfil de búsqueda del comprador: ubicación en cascada y mínimo de ubicación
 * (PLAN_PERFIL_OBLIGATORIO.md, decisión 4; PLAN_PERFIL_UBICACION.md; zonas por
 * población, PLAN_PERFIL_ZONAS.md).
 *
 * Marcado: macro `search_profile_fields` de
 * templates/components/search_profile_form.html. El bloque de ubicación es
 * `[data-geo-cascade]` con:
 *   - `data-geo-source`: id del <script type="application/json"> con el árbol
 *     {país: {provincia: {población: [zonas]}}} (provincia deducida del CP;
 *     las poblaciones sin CP válido cuelgan de `data-no-province`, que no es
 *     una provincia elegible);
 *   - `select[data-geo="country"]` y `select[data-geo="province"]`;
 *   - `[data-geo-list="cities"]`: casillas de población, SIN "Todas"
 *     (PLAN_PERFIL_ZONAS.md: al menos una concreta), con un `[data-geo-empty]`
 *     hermano;
 *   - `[data-geo-zones]`: <fieldset> de Zona, oculto y deshabilitado mientras
 *     no haya ninguna población marcada. Dentro, `[data-geo-list="zones"]` con
 *     "Todas" (`input[data-geo-all]`, `name="zones_all"`, en
 *     `[data-geo-all-wrap]`, que solo se ve si hay zonas) y un grupo
 *     `[data-geo-group]` por población marcada que tenga zonas (con título si
 *     hay más de un grupo).
 * El servidor ya pinta el estado inicial (perfil guardado); aquí solo se
 * reconstruyen los niveles cuando el agente cambia uno:
 *   país → provincias (y poblaciones y zonas), provincia → poblaciones (y
 *   zonas), poblaciones → zonas (solo las de las marcadas, agrupadas).
 * "Todas" las zonas no se marca nunca sola; marcada, marca y deshabilita las
 * demás (deshabilitadas no se envían: lista vacía = Todas).
 *
 * Mínimo de ubicación (con `data-places-required`): al enviar, si no hay
 * ninguna población marcada se cancela el envío y se muestra el aviso
 * `data-places-error` ("Marca al menos una población"); si las marcadas tienen
 * zonas y no hay ninguna zona ni "Todas", el aviso `data-zones-error` ("Elige
 * al menos una zona o marca Todas"). Se ignora dentro de un <fieldset
 * disabled> (el perfil del modal de seguimiento solo cuenta con «Contactado»).
 * Escucha en captura para adelantarse a la guardia de doble envío de ui.js
 * (`form[data-once]`).
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
 * asterisco de los campos `[data-profile-min]` (tipo, precio máximo y
 * dormitorios máximos) y de la
 * población (`[data-profile-mark]`); el de Zona (`[data-zone-mark]`) solo si
 * hay zonas que elegir. El mínimo de ubicación solo se comprueba mientras los
 * mínimos se exigen.
 */
(function () {
    'use strict';

    var LABEL_CLASS = 'inline-flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 cursor-pointer hover:bg-gray-50';
    var CHECK_CLASS = 'w-4 h-4 rounded border-gray-300 text-gray-900 focus:ring-gray-900/30';
    var GROUP_TITLE_CLASS = 'text-xs font-medium text-gray-500 mb-1';
    var GROUP_BOXES_CLASS = 'flex flex-wrap gap-2';

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

        var zonesBlock = block.querySelector('[data-geo-zones]');
        var allWrap = zonesList.querySelector('[data-geo-all-wrap]');

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

        function makeBox(name, value, checked) {
            var label = document.createElement('label');
            label.className = LABEL_CLASS;
            var input = document.createElement('input');
            input.type = 'checkbox';
            input.name = name;
            input.value = value;
            input.className = CHECK_CLASS;
            input.checked = checked;
            label.appendChild(input);
            label.appendChild(document.createTextNode(' ' + value));
            return label;
        }

        function toggleEmpty(list, hasValues) {
            var empty = list.parentNode.querySelector('[data-geo-empty]');
            if (empty) empty.classList.toggle('hidden', hasValues);
        }

        // Rehace las poblaciones conservando lo marcado que siga existiendo (sin "Todas")
        function renderCityList(values, selected) {
            items(citiesList).forEach(function (input) { citiesList.removeChild(input.closest('label')); });
            values.forEach(function (value) {
                citiesList.appendChild(makeBox('cities', value, selected.indexOf(value) !== -1));
            });
            toggleEmpty(citiesList, values.length > 0);
        }

        // Zonas de las poblaciones marcadas, en un grupo por población (título si hay
        // más de uno). Sin poblaciones marcadas el bloque se oculta y deshabilita
        // (no se envía nada); sin zonas, "Todas" no sale. "Todas" no se marca sola.
        function renderZones() {
            var map = cityZones();
            var chosen = checkedValues(citiesList);
            var all = allBox(zonesList);
            var wasAll = !!(all && all.checked);
            var keep = checkedValues(zonesList);
            var groups = [];
            chosen.forEach(function (city) {
                var zones = (map[city] || []).slice().sort(byName);
                if (zones.length) groups.push({ city: city, zones: zones });
            });
            Array.prototype.slice.call(zonesList.querySelectorAll('[data-geo-group]')).forEach(function (group) {
                zonesList.removeChild(group);
            });
            groups.forEach(function (group) {
                var wrap = document.createElement('div');
                wrap.setAttribute('role', 'group');
                wrap.setAttribute('aria-label', 'Zonas de ' + group.city);
                wrap.setAttribute('data-geo-group', '');
                if (groups.length > 1) {
                    var title = document.createElement('p');
                    title.className = GROUP_TITLE_CLASS;
                    title.textContent = group.city;
                    wrap.appendChild(title);
                }
                var boxes = document.createElement('div');
                boxes.className = GROUP_BOXES_CLASS;
                group.zones.forEach(function (zone) {
                    boxes.appendChild(makeBox('zones', zone, keep.indexOf(zone) !== -1));
                });
                wrap.appendChild(boxes);
                zonesList.appendChild(wrap);
            });
            var hasZones = groups.length > 0;
            if (all) all.checked = hasZones && wasAll;
            if (allWrap) allWrap.classList.toggle('hidden', !hasZones);
            applyAll(zonesList);
            toggleEmpty(zonesList, hasZones);
            if (zonesBlock) {
                zonesBlock.classList.toggle('hidden', chosen.length === 0);
                zonesBlock.disabled = chosen.length === 0;
            }
        }

        function renderCities(selected) {
            renderCityList(Object.keys(cityZones()).sort(byName), selected);
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

        citiesList.addEventListener('change', function (e) {
            if (e.target && e.target.type === 'checkbox') renderZones();
        });

        zonesList.addEventListener('change', function (e) {
            var target = e.target;
            if (!target || target.type !== 'checkbox') return;
            if (target.hasAttribute('data-geo-all')) {
                // Desmarcar "Todas" deja la lista sin marcar para elegir
                if (!target.checked) items(zonesList).forEach(function (input) { input.checked = false; });
                applyAll(zonesList);
                return;
            }
            // La misma zona en dos poblaciones: las dos casillas van a la par
            items(zonesList).forEach(function (input) {
                if (input !== target && input.value === target.value) input.checked = target.checked;
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
    var VALUE_NAMES = ['property_type', 'min_price', 'max_price', 'min_bedrooms', 'max_bedrooms', 'min_bathrooms',
        'elevator', 'province'];

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
        // Asterisco de Zona: solo si las poblaciones marcadas tienen zonas
        Array.prototype.slice.call(root.querySelectorAll('[data-geo-cascade]')).forEach(function (block) {
            var mark = block.querySelector('[data-zone-mark]');
            if (mark) mark.classList.toggle('hidden', !(on && zonesOffered(block)));
        });
        if (!on) {
            Array.prototype.slice.call(root.querySelectorAll('[data-places-required]')).forEach(function (block) {
                showError(block, null);
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

    // ¿Hay zonas que elegir? (bloque Zona visible con alguna casilla de zona)
    function zonesOffered(block) {
        var zones = block.querySelector('[data-geo-zones]');
        return !!zones && !zones.disabled && zones.querySelector('input[name="zones"]') !== null;
    }

    // Qué falta en la ubicación (PLAN_PERFIL_ZONAS.md): 'cities' si no hay ninguna
    // población marcada; 'zones' si las marcadas tienen zonas y no hay ninguna zona
    // marcada ni "Todas"; null si está bien
    function placeProblem(block) {
        var cities = block.querySelector('[data-geo-list="cities"]');
        if (!cities || !cities.querySelector('input[name="cities"]:checked')) return 'cities';
        if (!zonesOffered(block)) return null;
        var zones = block.querySelector('[data-geo-list="zones"]');
        var all = zones.querySelector('input[data-geo-all]');
        if (all && all.checked) return null;
        return zones.querySelector('input[name="zones"]:checked') ? null : 'zones';
    }

    // Muestra el aviso de población o de zona (y oculta el otro); null oculta los dos
    function showError(block, problem) {
        [['cities', 'data-places-error'], ['zones', 'data-zones-error']].forEach(function (pair) {
            var id = block.getAttribute(pair[1]);
            var error = id ? document.getElementById(id) : null;
            if (error) error.classList.toggle('hidden', problem !== pair[0]);
        });
    }

    document.addEventListener('submit', function (e) {
        var form = e.target;
        if (!form.querySelectorAll) return;
        var blocks = form.querySelectorAll('[data-places-required]');
        for (var i = 0; i < blocks.length; i++) {
            var block = blocks[i];
            if (!isActive(block)) continue;
            var problem = placeProblem(block);
            showError(block, problem);
            if (!problem) continue;
            e.preventDefault();
            var list = block.querySelector('[data-geo-list="' + problem + '"]');
            var first = (list && list.querySelector('input[type="checkbox"]:not(:disabled)'))
                || block.querySelector('select[data-geo="province"]');
            if (first) first.focus();
            return;
        }
    }, true);

    // En cuanto la ubicación queda bien, el aviso desaparece
    document.addEventListener('change', function (e) {
        var target = e.target;
        if (!target || !target.closest) return;
        var block = target.closest('[data-places-required]');
        if (!block) return;
        var problem = placeProblem(block);
        if (!problem) showError(block, null);
    });
})();
