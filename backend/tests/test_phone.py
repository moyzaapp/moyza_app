"""
Teléfono con indicativo en los formularios de comprador
(PLAN_TELEFONO_COMPRADOR.md, fase 1): funciones puras de `app.core.phone`,
sin base de datos ni app levantada.

    docker exec moyza_backend python -m pytest tests/test_phone.py -q
"""
import pytest

from app.core.phone import (
    PHONE_ERROR_MESSAGE,
    PhoneValidationError,
    canonical_phone,
    compose_phone,
    phone_display,
    phone_from_form,
    split_phone,
    tel_href,
    whatsapp_url,
)


# ---------------------------------------------------------------------------
# compose_phone
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("code, raw, expected", [
    ("34", "600112233", "34600112233"),
    ("34", "600 11 22 33", "34600112233"),
    # Indicativo repetido: se quita una vez
    ("34", "+34 600 11 22 33", "34600112233"),
    ("34", "0034600112233", "34600112233"),
    ("34", "0034 600 11 22 33", "34600112233"),
    ("34", "34600112233", "34600112233"),
    ("57", "300 123 4567", "573001234567"),
    ("57", "+57 300 123 4567", "573001234567"),
    ("593", "+593 99 123 4567", "593991234567"),
    # Otro indicativo distinto del seleccionado: no se toca
    ("34", "+57 300 123 4567", "34573001234567"),
    # Lo que queda sería demasiado corto: no se recorta (34 + "341234")
    ("34", "34 1234", "34341234"),
    # Vacío o sin dígitos
    ("34", "", ""),
    ("34", None, ""),
    ("34", "sin teléfono", ""),
])
def test_compose_phone(code, raw, expected):
    assert compose_phone(code, raw) == expected


@pytest.mark.parametrize("code", ["", None, "99", "abc", "+34"])
def test_compose_phone_codigo_invalido_usa_default(code):
    # "+34" se acepta como 34 (solo cuentan los dígitos)
    assert compose_phone(code, "600112233") == "34600112233"


def test_compose_phone_no_recorta_dos_veces():
    assert compose_phone("34", "+34 34 600 11 22 33") == "3434600112233"


# ---------------------------------------------------------------------------
# phone_from_form (validación y campo antiguo)
# ---------------------------------------------------------------------------

def test_phone_from_form_valido_y_vacio():
    assert phone_from_form("34", "+34 600 11 22 33") == "34600112233"
    assert phone_from_form("57", "300 123 4567") == "573001234567"
    assert phone_from_form("34", "") is None
    assert phone_from_form("34", "   ") is None


@pytest.mark.parametrize("raw", ["12345", "1234567890123", "34 123"])
def test_phone_from_form_local_fuera_de_rango(raw):
    with pytest.raises(PhoneValidationError) as excinfo:
        phone_from_form("34", raw)
    assert str(excinfo.value) == PHONE_ERROR_MESSAGE


def test_phone_from_form_limites():
    assert phone_from_form("34", "123456") == "34123456"
    assert phone_from_form("34", "123456789012") == "34123456789012"


def test_phone_from_form_campo_antiguo():
    assert phone_from_form(None, None, "600112233") == "34600112233"
    assert phone_from_form(None, None, "+57 300 123 4567") == "573001234567"
    assert phone_from_form(None, None, "") is None
    assert phone_from_form(None, None, None) is None
    with pytest.raises(PhoneValidationError):
        phone_from_form(None, None, "12345")
    # Si llegan los campos nuevos, el antiguo se ignora
    assert phone_from_form("34", "", "600112233") is None


# ---------------------------------------------------------------------------
# split_phone / phone_display / tel_href
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("phone, expected", [
    ("34600112233", ("34", "600112233")),
    ("+34 600 11 22 33", ("34", "600112233")),
    ("0034600112233", ("34", "600112233")),
    ("573001234567", ("57", "3001234567")),
    # Antiguo sin indicativo: España y el número completo
    ("600112233", ("34", "600112233")),
    ("", ("34", "")),
    (None, ("34", "")),
])
def test_split_phone(phone, expected):
    assert split_phone(phone) == expected


@pytest.mark.parametrize("phone, expected", [
    ("34600112233", "+34 600 112 233"),
    ("+34 600 11 22 33", "+34 600 112 233"),
    ("0034600112233", "+34 600 112 233"),
    ("573001234567", "+57 300 123 4567"),
    ("593991234567", "+593 991 234 567"),
    # Sin indicativo reconocido: tal cual
    ("600112233", "600112233"),
    ("+41 79 123 45 67", "+41 79 123 45 67"),
    ("sin teléfono", "sin teléfono"),
    ("", ""),
    (None, ""),
])
def test_phone_display(phone, expected):
    assert phone_display(phone) == expected


def test_tel_href():
    assert tel_href("34600112233") == "tel:+34600112233"
    assert tel_href("600 11 22 33") == "tel:+34600112233"
    assert tel_href("12 34") == "tel:1234"


def test_canonical_y_whatsapp_coinciden():
    for phone in ("600112233", "+34 600 11 22 33", "573001234567", "+41 79 123 45 67"):
        assert whatsapp_url(phone) == f"https://wa.me/{canonical_phone(phone)}"
    assert canonical_phone("12345") is None
    assert whatsapp_url("12345") is None


def test_lo_compuesto_se_lee_igual():
    """Lo que guarda el formulario lo entienden split, display y WhatsApp."""
    phone = compose_phone("57", "300 123 4567")
    assert split_phone(phone) == ("57", "3001234567")
    assert phone_display(phone) == "+57 300 123 4567"
    assert whatsapp_url(phone) == "https://wa.me/573001234567"
