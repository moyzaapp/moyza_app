"""
Teléfonos: composición del número con indicativo, lectura de los guardados en
texto libre y enlaces (PLAN_WHATSAPP_ALERTA.md, PLAN_TELEFONO_COMPRADOR.md).

Formato canónico guardado:
- Indicativo del selector (PhoneCountryCodes.OPTIONS, los frecuentes):
  dígitos con el indicativo y sin `+` ("34600112233"), el mismo que usan las
  visitas.
- Indicativo escrito a mano con la opción "Otro…" que no está en el selector:
  con `+` delante ("+41791234567"), para que al leerlo se sepa que el
  indicativo es explícito.

Regla de lectura (split_phone, phone_display, tel_href, whatsapp_url,
canonical_phone):
- Si el valor empieza por `+` o `00`, el indicativo es explícito: primero se
  busca en el selector y, si no está, se separa con el indicativo más largo de
  PhoneCountryCodes.ALL_CODES que coincida (todos los de E.164).
- Si NO empieza por `+` ni `00`, solo se reconocen los indicativos del
  selector y, si no, se asume España. Los teléfonos antiguos guardados sin
  indicativo no se reinterpretan con la lista completa: "600112233" es un
  móvil español, no Malasia (+60).

`whatsapp_url`, `phone_display`, `split_phone` y `tel_href` se registran como
filtros Jinja en `app/web/template_env.py`, así que cualquier plantilla puede
pintar el botón con una línea:

    {% set url = alert.lead_phone | whatsapp_url %}

La regla del prefijo es la misma que la del selector de país de visitas
(`PhoneCountryCodes.split`): no se duplica aquí.
"""

from app.core.constants import PhoneCountryCodes

# Dígitos mínimos de la parte local (sin indicativo) para considerar el número completo
MIN_LOCAL_DIGITS = 6
# Dígitos máximos de la parte local que acepta un formulario
MAX_LOCAL_DIGITS = 12
# E.164: un número internacional tiene como mucho 15 dígitos (indicativo incluido)
MAX_E164_DIGITS = 15
# Indicativo más largo de E.164 (p. ej. 593 Ecuador)
MAX_COUNTRY_CODE_DIGITS = 3


def _has_plus_prefix(text: str) -> bool:
    """True si hay un `+` antes del primer dígito ("+34 …", "(+34) …")."""
    for ch in text:
        if ch.isdigit():
            return False
        if ch == "+":
            return True
    return False


def _digits(value) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _match_any_code(digits: str) -> tuple[str, str] | None:
    """(código, local) con el indicativo más largo de ALL_CODES que coincida
    dejando al menos MIN_LOCAL_DIGITS dígitos locales, o None."""
    for size in range(MAX_COUNTRY_CODE_DIGITS, 0, -1):
        code = digits[:size]
        if code in PhoneCountryCodes.ALL_CODES and len(digits) - size >= MIN_LOCAL_DIGITS:
            return code, digits[size:]
    return None


def _split(phone) -> tuple[str, str, bool]:
    """(código, local, reconocido) según la regla de lectura del módulo.

    Si no se reconoce el indicativo devuelve (DEFAULT, dígitos, False)."""
    text = str(phone or "").strip()
    digits = _digits(text)
    international = _has_plus_prefix(text) or digits.startswith("00")
    if digits.startswith("00"):
        digits = digits[2:]
    if not digits:
        return PhoneCountryCodes.DEFAULT, "", False

    code, local = PhoneCountryCodes.split(digits)
    if local != digits:
        return code, local, True
    if international:
        match = _match_any_code(digits)
        if match:
            return match[0], match[1], True
    return PhoneCountryCodes.DEFAULT, digits, False


def _stored(code: str, local: str) -> str:
    """Formato guardado: sin `+` con indicativo del selector; con `+` si no."""
    if code in PhoneCountryCodes.short_codes():
        return code + local
    return "+" + code + local


def canonical_phone(phone) -> str | None:
    """Teléfono canónico ('34600112233') a partir de un valor guardado en
    texto libre, o None si no es utilizable.

    Reglas (las mismas que el botón de WhatsApp):
    - Se quitan todos los caracteres que no sean dígitos.
    - Un prefijo internacional escrito como `00` se elimina (0034… → 34…).
    - Si el número empieza por un indicativo conocido (PhoneCountryCodes.split)
      se respeta; si no, se asume España (+34). Es la misma regla que usa el
      selector de país de visitas.
    - Excepción: si el número trae `+` o `00` pero su indicativo no está en el
      selector (p. ej. +41 Suiza), se respeta tal cual en vez de anteponer 34.
      La parte local se mide con el indicativo de ALL_CODES que coincida; si
      no coincide ninguno, se descuentan 3 dígitos (el más largo posible).
    - Devuelve siempre solo dígitos (lo que pide wa.me), también para los
      guardados con `+` ("+41791234567" → "41791234567").
    - Si tras normalizar la parte local tiene menos de 6 dígitos, devuelve None
      (número incompleto).
    - Si el número completo supera los 15 dígitos de E.164 (p. ej. dos
      teléfonos escritos en el mismo campo), devuelve None.
    """
    if phone is None:
        return None

    text = str(phone).strip()
    digits = _digits(text)
    international = _has_plus_prefix(text) or digits.startswith("00")

    if digits.startswith("00"):
        digits = digits[2:]

    if not digits:
        return None

    code, local = PhoneCountryCodes.split(digits)

    if local != digits:
        # Indicativo conocido: split ya garantiza al menos 6 dígitos locales
        number = code + local
    elif international:
        # Indicativo explícito que no está en el selector: se respeta
        number = digits
        match = _match_any_code(digits)
        local = match[1] if match else digits[MAX_COUNTRY_CODE_DIGITS:]
    else:
        # Sin indicativo: España por defecto
        number = PhoneCountryCodes.DEFAULT + digits

    if len(local) < MIN_LOCAL_DIGITS or len(number) > MAX_E164_DIGITS:
        return None

    return number


def whatsapp_url(phone) -> str | None:
    """Enlace https://wa.me/<prefijo><número> para abrir el chat, o None si
    el teléfono no es utilizable (reglas de `canonical_phone`).

    Sin `?text=`: solo abre el chat.
    """
    number = canonical_phone(phone)
    return f"https://wa.me/{number}" if number else None


def tel_href(phone) -> str:
    """Destino del enlace `tel:`: 'tel:+34600112233' cuando el valor guardado
    es canónico (solo dígitos con un indicativo conocido); si no, el texto
    guardado tal cual, como hasta ahora (teléfonos antiguos). Los guardados con
    indicativo escrito a mano ya llevan `+` ("+41791234567" → 'tel:+41791234567')."""
    text = str(phone or "").strip()
    if text.isdigit():
        _code, local = PhoneCountryCodes.split(text)
        if local != text:
            return f"tel:+{text}"
    return f"tel:{text}"


# ---------------------------------------------------------------------------
# Selector de país (formularios de comprador; PLAN_TELEFONO_COMPRADOR.md)
# ---------------------------------------------------------------------------

PHONE_ERROR_MESSAGE = (
    f"Revisa el teléfono: debe tener entre {MIN_LOCAL_DIGITS} y {MAX_LOCAL_DIGITS} "
    "dígitos sin el indicativo"
)

OTHER_CODE_ERROR_MESSAGE = (
    "Indicativo no válido: escribe solo el prefijo del país, por ejemplo 41"
)


class PhoneValidationError(ValueError):
    """Teléfono de formulario no aceptable (parte local fuera de rango o
    indicativo escrito a mano que no existe)."""

    def __init__(self, message: str = PHONE_ERROR_MESSAGE):
        super().__init__(message)


def valid_country_code(country_code) -> str:
    """El indicativo si está en el selector; si no, PhoneCountryCodes.DEFAULT."""
    code = _digits(country_code)
    return code if code in PhoneCountryCodes.short_codes() else PhoneCountryCodes.DEFAULT


def other_country_code(other_code) -> str:
    """Indicativo escrito a mano con la opción "Otro…".

    Se admiten espacios y un `+` delante; el resto deben ser 1 a 3 dígitos de
    un indicativo real (PhoneCountryCodes.ALL_CODES). Si no, PhoneValidationError.
    """
    code = str(other_code or "").strip().lstrip("+").strip()
    if not (code.isdigit() and 1 <= len(code) <= MAX_COUNTRY_CODE_DIGITS
            and code in PhoneCountryCodes.ALL_CODES):
        raise PhoneValidationError(OTHER_CODE_ERROR_MESSAGE)
    return code


def form_country_code(country_code, other_code=None) -> str:
    """Indicativo efectivo del formulario: el escrito si se eligió "Otro…"
    (validado con `other_country_code`); si no, `valid_country_code`."""
    if str(country_code or "").strip() == PhoneCountryCodes.OTHER:
        return other_country_code(other_code)
    return valid_country_code(country_code)


def _compose_parts(country_code, raw_number, other_code=None) -> tuple[str, str] | None:
    """(código, local) del formulario o None si el número va vacío."""
    digits = _digits(raw_number)
    if not digits:
        return None
    code = form_country_code(country_code, other_code)

    for prefix in ("00" + code, code):
        if digits.startswith(prefix) and len(digits) - len(prefix) >= MIN_LOCAL_DIGITS:
            digits = digits[len(prefix):]
            break
    return code, digits


def compose_phone(country_code, raw_number, other_code=None) -> str:
    """Devuelve el teléfono canónico (p. ej. '34600112233') o ''.

    - country_code: uno de PhoneCountryCodes; si no es válido se usa DEFAULT.
      Con PhoneCountryCodes.OTHER ("Otro…") el indicativo es `other_code`,
      validado con `other_country_code` (PhoneValidationError si no existe).
    - raw_number: lo que escribió el usuario; se queda solo con dígitos.
    - Si el usuario repitió el indicativo (el elegido o el escrito) en el número
      ("+34 600…", "0034 600…", "34 600…"), se elimina UNA vez, solo si lo que
      queda tiene al menos MIN_LOCAL_DIGITS dígitos (así "34 1234" no se
      recorta a "1234"). Un indicativo distinto del seleccionado no se toca:
      la interfaz avisa antes de guardar.
    - Formato: sin `+` si el indicativo está en el selector (también si se
      escribió a mano, p. ej. "34"); con `+` si no ("+41791234567").
    - Si no quedan dígitos devuelve '' (sin validar el indicativo escrito).
    """
    parts = _compose_parts(country_code, raw_number, other_code)
    return _stored(*parts) if parts else ""


def storage_phone(phone) -> str | None:
    """Valor de texto libre en el formato guardado (`canonical_phone` con `+`
    delante si el indicativo no es del selector), o None si no es utilizable."""
    number = canonical_phone(phone)
    if number is None:
        return None
    code, local, recognized = _split("+" + number)
    # Sin reconocer solo llega un indicativo explícito desconocido: se conserva el `+`
    return _stored(code, local) if recognized else "+" + number


def phone_from_form(country_code, number, legacy=None, other_code=None) -> str | None:
    """Teléfono canónico a partir de los campos del formulario, o None si va vacío.

    - Campos nuevos (`*_country_code` + `*_number`, y `*_country_code_other`
      cuando se elige "Otro…"): `compose_phone` y la parte local debe tener
      entre MIN_LOCAL_DIGITS y MAX_LOCAL_DIGITS dígitos.
    - Compatibilidad durante el despliegue: si solo llega el campo antiguo de
      texto libre (`legacy`), se interpreta con `storage_phone`.

    Lanza PhoneValidationError si el número o el indicativo escrito no son
    aceptables.
    """
    if number is None and country_code is None:
        raw = (legacy or "").strip()
        if not raw:
            return None
        phone = storage_phone(raw)
        if phone is None:
            raise PhoneValidationError()
        return phone

    parts = _compose_parts(country_code, number, other_code)
    if not parts:
        return None

    code, local = parts
    if not MIN_LOCAL_DIGITS <= len(local) <= MAX_LOCAL_DIGITS:
        raise PhoneValidationError()
    return _stored(code, local)


def form_matches_stored(stored, country_code, number, other_code=None) -> bool:
    """True si el formulario de edición llega con lo mismo que pintó
    (`split_phone` del valor guardado). Un indicativo escrito no válido cuenta
    como cambio (lo rechazará `phone_from_form`)."""
    if not stored or number is None:
        return False
    try:
        code = form_country_code(country_code, other_code)
    except PhoneValidationError:
        return False
    return (code, number.strip()) == split_phone(stored)


def split_phone(phone) -> tuple[str, str]:
    """(código, número local) para rellenar el selector.

    Regla de lectura del módulo: con `+`/`00` se reconoce cualquier indicativo
    de ALL_CODES (el formulario selecciona entonces "Otro…" con el código
    escrito); sin ellos, solo los del selector. Para teléfonos antiguos sin
    indicativo reconocible asume España y deja el número completo para que el
    agente lo revise.
    """
    code, local, _recognized = _split(phone)
    return code, local


def _group_local(local: str) -> str:
    """'600112233' → '600 112 233'; '3001234567' → '300 123 4567'."""
    groups = [local[i:i + 3] for i in range(0, len(local), 3)]
    if len(groups) > 1 and len(groups[-1]) == 1:
        groups[-2:] = [groups[-2] + groups[-1]]
    return " ".join(groups)


def phone_display(phone) -> str:
    """'+34 600 112 233' (o '+41 791 234 567') para mostrar; si no se
    reconoce el indicativo, devuelve el texto tal cual (teléfonos antiguos)."""
    if phone is None:
        return ""
    text = str(phone).strip()
    code, local, recognized = _split(text)
    if not recognized:
        return text
    return f"+{code} {_group_local(local)}"
