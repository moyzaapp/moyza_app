"""
Enlace público de la propiedad, mensaje de WhatsApp y `whatsapp_url` con texto
(PLAN_ENVIO_PROPIEDAD_COMPRADOR.md §4.1, §4.3 y §6). Funciones puras: sin base
de datos ni red (nunca se consulta la web de la inmobiliaria).

    cd backend && python -m pytest tests/test_property_link.py -q
"""
from decimal import Decimal
from types import SimpleNamespace
from urllib.parse import parse_qs, unquote, urlparse

import pytest

from app.core.phone import whatsapp_url
from app.services.property_link import (
    clean_public_url,
    property_public_url,
    share_message,
)

# Comprobada a mano contra la web real el 2026-11-12 (§3)
VERIFIED_1933 = "https://www.inmobiliariamoyza.com/recursos/nficham06.php?cod_inmueble=9834998349193300"

MOYZA = SimpleNamespace(name="MOYZA")
MOES = SimpleNamespace(name="MOES PREMIUM")


def _prop(**fields):
    data = dict(
        referencia="1933", public_url=VERIFIED_1933, company=MOYZA, title="Piso Centro",
        property_type="Piso", zona="Bulevar", city="Jaén", num_dormitorios=3,
        price=Decimal("120000"), address="Calle Secreta 7, 2ºB",
        client=SimpleNamespace(name="Propietario Pérez", phone="34611222333"),
    )
    data.update(fields)
    return SimpleNamespace(**data)


# ---------------------------------------------------------------------------
# property_public_url: solo la columna, nunca calculado
# ---------------------------------------------------------------------------

def test_el_enlace_es_el_de_la_columna_recortado():
    assert property_public_url(_prop()) == VERIFIED_1933
    assert property_public_url(_prop(public_url=f"  {VERIFIED_1933} ")) == VERIFIED_1933


def test_sin_columna_no_hay_enlace_aunque_haya_referencia():
    for value in (None, "", "   "):
        assert property_public_url(_prop(public_url=value)) is None
    assert property_public_url(_prop(public_url=None, company=MOES, referencia="1525")) is None


def test_sin_propiedad_no_hay_enlace():
    assert property_public_url(None) is None


# ---------------------------------------------------------------------------
# clean_public_url
# ---------------------------------------------------------------------------

def test_clean_public_url_vacio_es_none():
    for value in (None, "", "   "):
        assert clean_public_url(value) is None


def test_clean_public_url_recorta_y_acepta_http_y_https():
    assert clean_public_url("  https://a.example/x  ") == "https://a.example/x"
    assert clean_public_url("http://a.example") == "http://a.example"
    assert clean_public_url("HTTPS://A.example/x") == "HTTPS://A.example/x"


@pytest.mark.parametrize("value", [
    "javascript:alert(1)",
    "ftp://a.example/x",
    "texto suelto",
    "www.inmobiliariamoyza.com/ficha",
    "https://",
    "https://a.example/con espacio",
])
def test_clean_public_url_rechaza(value):
    with pytest.raises(ValueError):
        clean_public_url(value)


def test_clean_public_url_maximo_500():
    base = "https://a.example/"
    assert clean_public_url(base + "x" * (500 - len(base)))
    with pytest.raises(ValueError):
        clean_public_url(base + "x" * (501 - len(base)))


# ---------------------------------------------------------------------------
# whatsapp_url con texto
# ---------------------------------------------------------------------------

def test_whatsapp_url_sin_texto_igual_que_hoy():
    assert whatsapp_url("600112233") == "https://wa.me/34600112233"
    assert whatsapp_url("600112233", None) == "https://wa.me/34600112233"
    assert whatsapp_url("600112233", "") == "https://wa.me/34600112233"
    assert whatsapp_url("123", "Hola") is None


def test_whatsapp_url_codifica_el_texto():
    text = "Hola Ánxela, ¿qué tal?\nPiso & garaje · 120.000 €\nhttps://x.example/f?a=1&b=2"
    url = whatsapp_url("+34 600 112 233", text)
    assert url.startswith("https://wa.me/34600112233?text=")
    encoded = url.split("?text=", 1)[1]
    # Todo codificado: ni saltos, ni &, ni €, ni tildes, ni espacios en crudo
    for raw in ("\n", "&", "€", "Á", "¿", " ", "?", "="):
        assert raw not in encoded
    assert "%0A" in encoded and "%26" in encoded and "%E2%82%AC" in encoded and "%C3%81" in encoded
    assert unquote(encoded) == text
    # Un solo parámetro `text` (el & del enlace no lo parte)
    assert parse_qs(urlparse(url).query) == {"text": [text]}


# ---------------------------------------------------------------------------
# share_message
# ---------------------------------------------------------------------------

def test_mensaje_completo():
    message = share_message(_prop(), "Juan Comprador", "Agente Ana")
    assert message == (
        "Hola Juan, soy Agente Ana de MOYZA. Te envío este inmueble que puede encajar con lo que buscas:\n"
        "\n"
        "Piso en Bulevar, Jaén · 3 dorm. · 120.000 €\n"
        + VERIFIED_1933
    )


def test_mensaje_sin_direccion_ni_propietario():
    message = share_message(_prop(), "Juan", "Ana")
    for secret in ("Calle Secreta", "2ºB", "Propietario", "611222333"):
        assert secret not in message


def test_mensaje_sin_nombre_dice_hola_coma():
    for name in (None, "", "   "):
        assert share_message(_prop(), name, "Ana").startswith("Hola, soy Ana de MOYZA. ")


def test_mensaje_omite_datos_vacios():
    prop = _prop(property_type=None, zona=None, num_dormitorios=None, price=None)
    message = share_message(prop, "Juan", "Ana")
    lines = message.split("\n")
    assert lines[2] == "Inmueble en Jaén"
    assert "dorm." not in message and "€" not in message and "None" not in message

    prop = _prop(property_type="Local", zona=None, city=None, num_dormitorios=0)
    lines = share_message(prop, "Juan", "Ana").split("\n")
    assert lines[2] == "Local · 120.000 €"


def test_mensaje_con_la_empresa_de_la_propiedad_y_enlace_manual():
    prop = _prop(company=MOES, public_url="https://moes.example/ficha/77", zona="Centro", city="Centro")
    message = share_message(prop, "Juan", "Ana")
    assert "soy Ana de MOES PREMIUM." in message
    assert "Piso en Centro · " in message
    assert message.endswith("https://moes.example/ficha/77")


def test_filtro_jinja_registrado():
    from app.web.template_env import templates
    assert templates.env.filters["public_url"] is property_public_url
    rendered = templates.env.from_string("{{ prop | public_url }}").render(prop=_prop())
    assert rendered == VERIFIED_1933
