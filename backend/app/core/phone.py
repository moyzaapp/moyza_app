"""
Teléfonos: composición del número con indicativo, lectura de los guardados en
texto libre y enlaces (PLAN_WHATSAPP_ALERTA.md, PLAN_TELEFONO_COMPRADOR.md).

Formato canónico guardado: dígitos con el indicativo y sin `+`
("34600112233"), el mismo que usan las visitas.

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
      Como no se sabe cuánto mide ese indicativo, se descuentan 3 dígitos (el
      más largo posible) al comprobar la parte local.
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
        local = digits[MAX_COUNTRY_CODE_DIGITS:]
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
    guardado tal cual, como hasta ahora (teléfonos antiguos)."""
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


class PhoneValidationError(ValueError):
    """Teléfono de formulario con una parte local fuera de rango."""

    def __init__(self, message: str = PHONE_ERROR_MESSAGE):
        super().__init__(message)


def valid_country_code(country_code) -> str:
    """El indicativo si está en el selector; si no, PhoneCountryCodes.DEFAULT."""
    code = _digits(country_code)
    known = {option[0] for option in PhoneCountryCodes.OPTIONS}
    return code if code in known else PhoneCountryCodes.DEFAULT


def compose_phone(country_code, raw_number) -> str:
    """Devuelve el teléfono canónico 'códigodígitos' (p. ej. '34600112233') o ''.

    - country_code: uno de PhoneCountryCodes; si no es válido se usa DEFAULT.
    - raw_number: lo que escribió el usuario; se queda solo con dígitos.
    - Si el usuario repitió el indicativo seleccionado en el número
      ("+34 600…", "0034 600…", "34 600…"), se elimina UNA vez, solo si lo que
      queda tiene al menos MIN_LOCAL_DIGITS dígitos (así "34 1234" no se
      recorta a "1234"). Un indicativo distinto del seleccionado no se toca:
      la interfaz avisa antes de guardar.
    - Si no quedan dígitos devuelve ''.
    """
    code = valid_country_code(country_code)
    digits = _digits(raw_number)
    if not digits:
        return ""

    for prefix in ("00" + code, code):
        if digits.startswith(prefix) and len(digits) - len(prefix) >= MIN_LOCAL_DIGITS:
            digits = digits[len(prefix):]
            break

    return code + digits


def phone_from_form(country_code, number, legacy=None) -> str | None:
    """Teléfono canónico a partir de los campos del formulario, o None si va vacío.

    - Campos nuevos (`*_country_code` + `*_number`): `compose_phone` y la parte
      local debe tener entre MIN_LOCAL_DIGITS y MAX_LOCAL_DIGITS dígitos.
    - Compatibilidad durante el despliegue: si solo llega el campo antiguo de
      texto libre (`legacy`), se interpreta con `canonical_phone`.

    Lanza PhoneValidationError si el número no es aceptable.
    """
    if number is None and country_code is None:
        raw = (legacy or "").strip()
        if not raw:
            return None
        phone = canonical_phone(raw)
        if phone is None:
            raise PhoneValidationError()
        return phone

    phone = compose_phone(country_code, number)
    if not phone:
        return None

    local = phone[len(valid_country_code(country_code)):]
    if not MIN_LOCAL_DIGITS <= len(local) <= MAX_LOCAL_DIGITS:
        raise PhoneValidationError()
    return phone


def split_phone(phone) -> tuple[str, str]:
    """(código, número local) para rellenar el selector.

    Envuelve PhoneCountryCodes.split quitando antes un prefijo `00`. Para
    teléfonos antiguos sin indicativo reconocible asume España y deja el
    número completo para que el agente lo revise.
    """
    digits = _digits(phone)
    if digits.startswith("00"):
        digits = digits[2:]
    return PhoneCountryCodes.split(digits)


def _group_local(local: str) -> str:
    """'600112233' → '600 112 233'; '3001234567' → '300 123 4567'."""
    groups = [local[i:i + 3] for i in range(0, len(local), 3)]
    if len(groups) > 1 and len(groups[-1]) == 1:
        groups[-2:] = [groups[-2] + groups[-1]]
    return " ".join(groups)


def phone_display(phone) -> str:
    """'+34 600 112 233' para mostrar; si no se reconoce el indicativo,
    devuelve el texto tal cual (teléfonos antiguos)."""
    if phone is None:
        return ""
    text = str(phone).strip()
    digits = _digits(text)
    if digits.startswith("00"):
        digits = digits[2:]
    if not digits:
        return text

    code, local = PhoneCountryCodes.split(digits)
    if local == digits:
        return text
    return f"+{code} {_group_local(local)}"
