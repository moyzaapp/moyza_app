"""
Dirección sin número en la app: solo lo que hay antes de la primera coma
(`app/core/address.py`, filtro Jinja `street`, `Property.street`).

- Unitario: `street_only`.
- Integración contra la app levantada (patrón `_Client` de
  test_buyer_business_type.py, se omite si la app no responde): crea en MOYZA
  una propiedad "Calle Fuente del Peral, 8" y una alerta sobre ella, comprueba
  las páginas y las borra al terminar. El formulario de edición (modal de
  /properties, relleno desde `data-address` del botón Editar) sí lleva la
  dirección completa.

Ejecución dentro del contenedor:
    docker exec moyza_backend python -m pytest tests/test_address_street.py -q
"""
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

import pytest

from app.core.address import street_only

BASE_URL = os.getenv("MOYZA_TEST_BASE_URL", "http://localhost:8000")
ADMIN_EMAIL = os.getenv("MOYZA_TEST_ADMIN_EMAIL", "admin@moyza.com")
TAG = "PYTEST-CALLE"
FULL_ADDRESS = "Calle Fuente del Peral, 8"
STREET = "Calle Fuente del Peral"
NUMBER = "Fuente del Peral, 8"


# ---------------------------------------------------------------------------
# Unitario
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    ("Calle Fuente del Peral, 8", "Calle Fuente del Peral"),
    ("Calle Test 1", "Calle Test 1"),                       # sin coma: tal cual
    ("Avda. Andalucía, 12, 3º B", "Avda. Andalucía"),      # varias comas: hasta la primera
    ("  Calle Mayor  , 5 ", "Calle Mayor"),                 # espacios
    ("Calle Mayor,", "Calle Mayor"),
    (", 8", ""),
    ("", ""),
    ("   ", ""),
    (None, ""),
])
def test_street_only(value, expected):
    assert street_only(value) == expected


def test_property_street_y_filtro():
    from app.models.property import Property
    from app.web.template_env import templates

    assert Property(address=FULL_ADDRESS).street == STREET
    assert Property(address=None).street == ""
    render = templates.env.from_string("{{ a | street }}|{{ (b | street) or '—' }}").render
    assert render(a=FULL_ADDRESS, b=None) == f"{STREET}|—"


# ---------------------------------------------------------------------------
# Integración
# ---------------------------------------------------------------------------

def _server_up() -> bool:
    try:
        urllib.request.urlopen(BASE_URL + "/", timeout=3)
        return True
    except Exception:
        return False


class _Client:
    """Peticiones con cookies de sesión y empresa, sin seguir redirecciones."""

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    def __init__(self, company: str):
        from app.core.security import create_access_token
        token = create_access_token({"sub": ADMIN_EMAIL})
        self.cookie = f"access_token={token}; active_company={company}"
        self.opener = urllib.request.build_opener(self._NoRedirect)

    def get(self, path, params=None):
        url = BASE_URL + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url)
        req.add_header("Cookie", self.cookie)
        try:
            resp = self.opener.open(req, timeout=20)
            return resp.status, resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8")


@pytest.fixture
def db():
    if not _server_up():
        pytest.skip(f"La app no responde en {BASE_URL}; tests de integración omitidos")

    from app.db.session import SessionLocal
    from app.models.property import Property
    from app.models.property_alert import PropertyAlert

    def cleanup():
        session.rollback()
        for alert in session.query(PropertyAlert).filter(PropertyAlert.lead_name.like(f"{TAG}%")).all():
            session.delete(alert)
        session.flush()
        for prop in session.query(Property).filter(Property.title.like(f"{TAG}%")).all():
            session.delete(prop)
        session.commit()

    session = SessionLocal()
    cleanup()
    yield session

    cleanup()
    session.close()


@pytest.fixture
def prop_and_alert(db):
    """Propiedad activa en MOYZA con "Calle Fuente del Peral, 8" y una alerta abierta sobre ella."""
    from app.core.constants import PropertyStatus
    from app.models.agent import Agent
    from app.models.company import Company
    from app.models.property import Property
    from app.models.property_alert import PropertyAlert
    from app.models.user import User

    moyza = db.query(Company).filter(Company.code == "MOYZA").first()
    agent = db.query(Agent).filter(Agent.companies.any(Company.id == moyza.id)).first()
    admin = db.query(User).filter(User.email == ADMIN_EMAIL).first()
    if agent is None or admin is None:
        pytest.skip("Faltan agente en MOYZA o el usuario admin")

    prop = Property(title=f"{TAG} PISO", address=FULL_ADDRESS, city="Jaén", price=123456,
                    status=PropertyStatus.ACTIVE, business_type="Venta", company_id=moyza.id,
                    agent_id=agent.id)
    db.add(prop)
    db.flush()
    alert = PropertyAlert(property_id=prop.id, company_id=moyza.id, agent_id=agent.id,
                          lead_name=f"{TAG} INTERESADO", business_type="Venta",
                          status="PENDING", created_by=admin.id)
    db.add(alert)
    db.commit()
    return prop, alert


def _without_edit_form(html: str) -> str:
    """La página sin el `data-address` del botón Editar (dato del formulario de edición)."""
    return re.sub(r'data-address="[^"]*"', "", html)


def _check(html: str, path: str):
    assert NUMBER not in html, path
    assert STREET in html, path


def test_paginas_muestran_la_calle_sin_numero(db, prop_and_alert):
    prop, alert = prop_and_alert
    client = _Client("MOYZA")

    status, html = client.get("/properties", {"search": TAG})
    assert status == 200 and prop.title in html
    # Formulario de edición (excepción acordada): dirección completa en el botón Editar
    assert f'data-address="{FULL_ADDRESS}"' in html
    assert NUMBER not in _without_edit_form(html)

    for path, params in ((f"/properties/{prop.id}", None),
                         ("/visits/select-property", None),
                         ("/alerts", {"q": TAG}),
                         (f"/alerts/{alert.id}", None)):
        status, html = client.get(path, params)
        assert status == 200, path
        _check(html, path)

    status, body = client.get("/alerts/search-properties", {"q": "Fuente"})
    assert status == 200
    results = [r for r in json.loads(body)["results"] if r["id"] == prop.id]
    assert [r["address"] for r in results] == [STREET]
    assert NUMBER not in body


def test_buscador_sigue_buscando_en_la_direccion_completa(db, prop_and_alert):
    prop, _ = prop_and_alert
    status, body = _Client("MOYZA").get("/alerts/search-properties", {"q": "Peral, 8"})
    assert status == 200
    assert prop.id in [r["id"] for r in json.loads(body)["results"]]


def test_vista_previa_de_la_ficha_de_visita_no_se_toca():
    """La vista previa HTML de la ficha de visita (lo que se firma) y el PDF llevan la dirección completa."""
    from pathlib import Path
    templates = Path(__file__).resolve().parent.parent / "app" / "web" / "templates"
    assert "{{ property.address }}" in (templates / "visits" / "preview.html").read_text(encoding="utf-8")
