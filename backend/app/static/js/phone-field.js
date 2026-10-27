/*
 * Campo de teléfono con selector de país (macro phone_field de
 * components/phone_macros.html; PLAN_TELEFONO_COMPRADOR.md §2.2-2.3).
 *
 * - Acorta el select a "+34" cuando está cerrado y muestra "🇪🇸 +34 España"
 *   al abrirlo (antes vivía en properties/visit_form.html).
 * - Aviso, sin bloquear, cuando el número ya parece traer un indicativo.
 *   El servidor compone el número con app.core.phone.compose_phone; aquí se
 *   repite la misma regla solo para enseñar qué se va a guardar.
 * - Opción "Otro…" (valor "other"): muestra el input del indicativo escrito
 *   a mano ([data-phone-other]) y lo oculta, desactiva y vacía al volver a
 *   elegir un país de la lista. El select cerrado muestra "Otro".
 * - PhoneField.compose(campo) devuelve "código + dígitos" para la
 *   comprobación de compradores duplicados en vivo (también con "Otro…").
 */
window.PhoneField = (function () {
    'use strict';

    var MIN_LOCAL_DIGITS = 6;   // app.core.phone.MIN_LOCAL_DIGITS
    var OTHER = 'other';        // PhoneCountryCodes.OTHER

    function digitsOf(text) {
        return String(text || '').replace(/\D/g, '');
    }

    function hasPlusPrefix(text) {
        var match = String(text || '').match(/^[^\d]*/);
        return match ? match[0].indexOf('+') !== -1 : false;
    }

    // Misma regla que compose_phone: quita UNA vez "00"+código o código
    function composeParts(code, raw) {
        var digits = digitsOf(raw);
        if (!digits) return null;
        var prefixes = ['00' + code, code];
        var stripped = false;
        for (var i = 0; i < prefixes.length; i++) {
            var p = prefixes[i];
            if (digits.indexOf(p) === 0 && digits.length - p.length >= MIN_LOCAL_DIGITS) {
                digits = digits.slice(p.length);
                stripped = true;
                break;
            }
        }
        return { code: code, local: digits, stripped: stripped };
    }

    // "600112233" -> "600 112 233"; "3001234567" -> "300 123 4567"
    function groupLocal(local) {
        var groups = local.match(/.{1,3}/g) || [];
        if (groups.length > 1 && groups[groups.length - 1].length === 1) {
            var last = groups.pop();
            groups[groups.length - 1] += last;
        }
        return groups.join(' ');
    }

    function parts(field) {
        var select = field.querySelector('[data-phone-country]');
        var input = field.querySelector('[data-phone-number]');
        return {
            select: select,
            input: input,
            hint: field.querySelector('[data-phone-hint]'),
            other: field.querySelector('[data-phone-other]'),
            otherWrap: field.querySelector('[data-phone-other-wrap]')
        };
    }

    // Indicativo efectivo: el elegido o, con "Otro…", los dígitos escritos ('' si no hay)
    function selectedCode(p) {
        if (p.select.value !== OTHER) return p.select.value;
        return p.other ? digitsOf(p.other.value) : '';
    }

    function compose(field) {
        var p = parts(field);
        if (!p.select || !p.input) return '';
        var code = selectedCode(p);
        if (!code) return digitsOf(p.input.value);   // el servidor compara por sufijo
        var composed = composeParts(code, p.input.value);
        return composed ? composed.code + composed.local : '';
    }

    function toggleOther(p, focus) {
        if (!p.other || !p.otherWrap) return;
        var isOther = p.select.value === OTHER;
        p.otherWrap.classList.toggle('hidden', !isOther);
        p.other.disabled = !isOther;
        if (!isOther) {
            p.other.value = '';
        } else if (focus) {
            p.other.focus();
        }
    }

    function updateHint(field) {
        var p = parts(field);
        if (!p.hint) return;
        var raw = p.input.value || '';
        var digits = digitsOf(raw);
        var code = selectedCode(p);
        var composed = code ? composeParts(code, raw) : null;
        var message = '';

        if (composed && composed.stripped) {
            message = 'Parece que el número ya incluye el indicativo; se guardará como +'
                + code + ' ' + groupLocal(composed.local);
        } else if (composed && (hasPlusPrefix(raw) || digits.indexOf('00') === 0)) {
            message = 'El número empieza por otro indicativo. Elige su país en el selector (o «Otro…» y escribe su indicativo) y escribe solo el número; si no, se guardará como +'
                + code + ' ' + groupLocal(composed.local);
        }

        p.hint.textContent = message;
        p.hint.classList.toggle('hidden', !message);
    }

    function initSelect(select) {
        function shorten() {
            var opt = select.options[select.selectedIndex];
            if (opt) opt.textContent = opt.dataset.short;
        }
        function expand() {
            Array.prototype.forEach.call(select.options, function (opt) {
                opt.textContent = opt.dataset.full;
            });
        }
        shorten();
        select.addEventListener('mousedown', expand);
        select.addEventListener('focus', expand);
        select.addEventListener('change', shorten);
        select.addEventListener('blur', shorten);
    }

    function init(root) {
        (root || document).querySelectorAll('[data-phone-field]').forEach(function (field) {
            if (field.dataset.phoneReady) return;
            field.dataset.phoneReady = '1';
            var p = parts(field);
            if (!p.select || !p.input) return;
            initSelect(p.select);
            toggleOther(p, false);
            p.input.addEventListener('input', function () { updateHint(field); });
            p.select.addEventListener('change', function () {
                toggleOther(p, true);
                updateHint(field);
            });
            if (p.other) {
                p.other.addEventListener('input', function () {
                    // Solo dígitos: el "+" ya va fijo delante
                    var clean = digitsOf(p.other.value).slice(0, 3);
                    if (clean !== p.other.value) p.other.value = clean;
                    updateHint(field);
                });
            }
            updateHint(field);
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () { init(); });
    } else {
        init();
    }

    return { init: init, compose: compose };
})();
