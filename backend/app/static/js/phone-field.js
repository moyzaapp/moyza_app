/*
 * Campo de teléfono con selector de país (macro phone_field de
 * components/phone_macros.html; PLAN_TELEFONO_COMPRADOR.md §2.2-2.3).
 *
 * - Acorta el select a "+34" cuando está cerrado y muestra "🇪🇸 +34 España"
 *   al abrirlo (antes vivía en properties/visit_form.html).
 * - Aviso, sin bloquear, cuando el número ya parece traer un indicativo.
 *   El servidor compone el número con app.core.phone.compose_phone; aquí se
 *   repite la misma regla solo para enseñar qué se va a guardar.
 * - PhoneField.compose(campo) devuelve "código + dígitos" para la
 *   comprobación de compradores duplicados en vivo.
 */
window.PhoneField = (function () {
    'use strict';

    var MIN_LOCAL_DIGITS = 6;   // app.core.phone.MIN_LOCAL_DIGITS

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
        return { select: select, input: input, hint: field.querySelector('[data-phone-hint]') };
    }

    function compose(field) {
        var p = parts(field);
        if (!p.select || !p.input) return '';
        var composed = composeParts(p.select.value, p.input.value);
        return composed ? composed.code + composed.local : '';
    }

    function updateHint(field) {
        var p = parts(field);
        if (!p.hint) return;
        var raw = p.input.value || '';
        var digits = digitsOf(raw);
        var code = p.select.value;
        var composed = composeParts(code, raw);
        var message = '';

        if (composed && composed.stripped) {
            message = 'Parece que el número ya incluye el indicativo; se guardará como +'
                + code + ' ' + groupLocal(composed.local);
        } else if (composed && (hasPlusPrefix(raw) || digits.indexOf('00') === 0)) {
            message = 'El número empieza por otro indicativo. Elige su país en el selector y escribe solo el número; si no, se guardará como +'
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
            p.input.addEventListener('input', function () { updateHint(field); });
            p.select.addEventListener('change', function () { updateHint(field); });
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
