"""
Teléfono con indicativo en los formularios de comprador
(PLAN_TELEFONO_COMPRADOR.md, fase 1): funciones puras de `app.core.phone`,
sin base de datos ni app levantada.

    docker exec moyza_backend python -m pytest tests/test_phone.py -q
"""
import pytest

from app.core.constants import PhoneCountryCodes
from app.core.phone import (
    OTHER_CODE_ERROR_MESSAGE,
    PHONE_ERROR_MESSAGE,
    PhoneValidationError,
    canonical_phone,
    compose_phone,
    form_matches_stored,
    phone_display,
    phone_from_form,
    split_phone,
    storage_phone,
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
    # Indicativo explícito fuera del selector: se separa con ALL_CODES
    ("+41 79 123 45 67", "+41 791 234 567"),
    # Explícito pero inexistente: tal cual
    ("+999 1234567", "+999 1234567"),
    ("sin teléfono", "sin teléfono"),
    ("", ""),
    (None, ""),
])
def test_phone_display(phone, expected):
    assert phone_display(phone) == expected


def test_tel_href():
    # Canónico: con "+"
    assert tel_href("34600112233") == "tel:+34600112233"
    assert tel_href("573001234567") == "tel:+573001234567"
    # Antiguos: tal cual, como antes
    assert tel_href("600112233") == "tel:600112233"
    assert tel_href("+34 600 11 22 33") == "tel:+34 600 11 22 33"
    assert tel_href(None) == "tel:"


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


# ---------------------------------------------------------------------------
# Indicativo "Otro…" escrito a mano (todos los de E.164)
# ---------------------------------------------------------------------------

OTHER = PhoneCountryCodes.OTHER


def test_all_codes_incluye_el_selector_y_es_prefijo_libre():
    codes = PhoneCountryCodes.ALL_CODES
    assert PhoneCountryCodes.short_codes() <= codes
    assert all(code.isdigit() and 1 <= len(code) <= 3 for code in codes)
    assert 200 < len(codes) < 260
    # Ningún indicativo es el inicio de otro: "el más largo que coincida" es único
    assert not [(a, b) for a in codes for b in codes if a != b and b.startswith(a)]


def test_otro_valido_se_guarda_con_mas():
    assert phone_from_form(OTHER, "79 123 45 67", other_code="41") == "+41791234567"
    assert compose_phone(OTHER, "79 123 45 67", "41") == "+41791234567"
    # Espacios o "+" en el indicativo escrito se toleran
    assert phone_from_form(OTHER, "79 123 45 67", other_code=" +41 ") == "+41791234567"


@pytest.mark.parametrize("other", ["999", "", None, "0041", "4a", "1234"])
def test_otro_invalido(other):
    with pytest.raises(PhoneValidationError) as excinfo:
        phone_from_form(OTHER, "79 123 45 67", other_code=other)
    assert str(excinfo.value) == OTHER_CODE_ERROR_MESSAGE
    assert "por ejemplo 41" in OTHER_CODE_ERROR_MESSAGE


def test_otro_sin_numero_no_valida_el_indicativo():
    assert phone_from_form(OTHER, "", other_code="999") is None
    assert compose_phone(OTHER, "", "") == ""


def test_otro_con_indicativo_del_selector_se_guarda_sin_mas():
    assert phone_from_form(OTHER, "600 11 22 33", other_code="34") == "34600112233"
    assert phone_from_form(OTHER, "300 123 4567", other_code="57") == "573001234567"


def test_otro_indicativo_repetido_se_recorta_una_vez():
    assert phone_from_form(OTHER, "+41 79 123 45 67", other_code="41") == "+41791234567"
    assert phone_from_form(OTHER, "0041 79 123 45 67", other_code="41") == "+41791234567"
    assert phone_from_form(OTHER, "+41 41 79 123 45 67", other_code="41") == "+4141791234567"


def test_otro_valida_la_parte_local():
    with pytest.raises(PhoneValidationError) as excinfo:
        phone_from_form(OTHER, "12345", other_code="41")
    assert str(excinfo.value) == PHONE_ERROR_MESSAGE


def test_guardado_con_mas_se_lee():
    phone = "+41791234567"
    assert split_phone(phone) == ("41", "791234567")
    assert phone_display(phone) == "+41 791 234 567"
    assert whatsapp_url(phone) == "https://wa.me/41791234567"
    assert canonical_phone(phone) == "41791234567"
    assert tel_href(phone) == "tel:+41791234567"
    assert split_phone("0041791234567") == ("41", "791234567")


def test_sin_mas_ni_00_no_se_reinterpreta():
    # "600112233" es un móvil español, no Malasia (+60)
    assert split_phone("600112233") == ("34", "600112233")
    assert phone_display("600112233") == "600112233"
    assert whatsapp_url("600112233") == "https://wa.me/34600112233"
    # Con "+" sí es Malasia
    assert split_phone("+600112233") == ("60", "0112233")


def test_mas_uno_es_nanp():
    assert split_phone("+1 212 555 0100") == ("1", "2125550100")
    assert phone_display("+1 212 555 0100") == "+1 212 555 0100"
    assert whatsapp_url("+1 212 555 0100") == "https://wa.me/12125550100"


def test_storage_phone_conserva_el_mas():
    assert storage_phone("+41 79 123 45 67") == "+41791234567"
    assert storage_phone("600 11 22 33") == "34600112233"
    assert storage_phone("+999 1234567") == "+9991234567"
    assert storage_phone("12345") is None
    # Campo antiguo de texto libre con indicativo fuera del selector
    assert phone_from_form(None, None, "+41 79 123 45 67") == "+41791234567"


def test_form_matches_stored():
    assert form_matches_stored("+41791234567", OTHER, "791234567", "41")
    assert form_matches_stored("600112233", "34", "600112233")
    assert not form_matches_stored("+41791234567", OTHER, "791234567", "999")
    assert not form_matches_stored("+41791234567", "34", "791234567")
    assert not form_matches_stored(None, "34", "600112233")


def test_otro_compuesto_se_lee_igual():
    phone = compose_phone(OTHER, "79 123 45 67", "41")
    code, local = split_phone(phone)
    assert (code, local) == ("41", "791234567")
    assert compose_phone(OTHER, local, code) == phone
