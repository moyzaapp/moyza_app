"""
Teléfono del visitante con el selector de país de compradores, incluida la
opción "Otro…" con el indicativo escrito a mano
(PLAN_VISITAS_INDICATIVO_HONORARIOS.md §2.1).

- Unitarios: composición del teléfono desde el formulario y su lectura.
- Integración contra la app levantada (se omite si no responde): alta con
  "Otro…", vista previa, edición y un indicativo que no existe. Crea un
  agente y una propiedad en MOYZA y los borra.

    docker exec moyza_backend python -m pytest tests/test_visit_phone_other.py -q
"""
import os
import urllib.error
import urllib.parse
import urllib.request

import pytest

from app.core.phone import PhoneValidationError, phone_display, split_phone
from app.models.property_visit import PropertyVisit
from app.web.routes.visits import visit_phone_from_form


# ---------------------------------------------------------------------------
# Unitarios
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("form, expected", [
    ({"phone_country_code": "34", "phone_number": "600 112 233"}, "34600112233"),
    ({"phone_country_code": "57", "phone_number": "3001234567"}, "573001234567"),
    # "Otro…": indicativo escrito, se guarda con "+" para que se sepa que es explícito
    ({"phone_country_code": "other", "phone_country_code_other": "41", "phone_number": "791234567"}, "+41791234567"),
    ({"phone_country_code": "other", "phone_country_code_other": "+41", "phone_number": "791234567"}, "+41791234567"),
    # Un indicativo escrito que está en el selector se guarda como los del selector
    ({"phone_country_code": "other", "phone_country_code_other": "34", "phone_number": "600112233"}, "34600112233"),
    ({"phone_country_code": "34", "phone_number": ""}, None),
    ({}, None),
])
def test_visit_phone_from_form(form, expected):
    assert visit_phone_from_form(form) == expected


@pytest.mark.parametrize("form", [
    {"phone_country_code": "other", "phone_country_code_other": "999", "phone_number": "791234567"},
    {"phone_country_code": "other", "phone_country_code_other": "", "phone_number": "791234567"},
    {"phone_country_code": "34", "phone_number": "12345"},
    {"phone_country_code": "34", "phone_number": "6001122334455"},
])
def test_visit_phone_no_valido(form):
    with pytest.raises(PhoneValidationError):
        visit_phone_from_form(form)


def test_lectura_del_guardado_con_otro():
    # La edición rellena "Otro…" + 41 y la ficha lo muestra agrupado
    assert split_phone("+41791234567") == ("41", "791234567")
    assert phone_display("+41791234567") == "+41 791 234 567"
    assert phone_display("34600112233") == "+34 600 112 233"
    assert PropertyVisit(phone="+41791234567").phone == "+41791234567"


# ---------------------------------------------------------------------------
# Integración
# ---------------------------------------------------------------------------

BASE_URL = os.getenv("MOYZA_TEST_BASE_URL", "http://localhost:8000")
ADMIN_EMAIL = os.getenv("MOYZA_TEST_ADMIN_EMAIL", "admin@moyza.com")
TAG = "PYTEST-TEL-OTRO"


def _server_up() -> bool:
    try:
        urllib.request.urlopen(BASE_URL + "/", timeout=3)
        return True
    except Exception:
        return False


server = pytest.mark.skipif(
    not _server_up(),
    reason=f"La app no responde en {BASE_URL}; tests de integración omitidos",
)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _request(method, path, data=None):
    from app.core.security import create_access_token
    token = create_access_token({"sub": ADMIN_EMAIL})
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(BASE_URL + path, data=body, method=method)
    req.add_header("Cookie", f"access_token={token}; active_company=MOYZA")
    try:
        resp = urllib.request.build_opener(_NoRedirect).open(req, timeout=20)
        return resp.status, resp.read().decode("utf-8", "replace"), dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), dict(e.headers)


@pytest.fixture(scope="module")
def phone_property():
    from app.db.session import SessionLocal
    from app.models.agent import Agent
    from app.models.company import Company
    from app.models.property import Property
    from app.models.visit_audit_log import VisitAuditLog

    db = SessionLocal()
    moyza = db.query(Company).filter_by(code="MOYZA").one()
    agent = Agent(name=f"{TAG} AGENTE", email="pytest.tel.otro@example.com")
    agent.companies.append(moyza)
    db.add(agent)
    db.flush()
    prop = Property(title=f"{TAG} PROP", company_id=moyza.id, agent_id=agent.id)
    db.add(prop)
    db.commit()

    yield {"agent_id": agent.id, "property_id": prop.id}

    visit_ids = [v.id for v in db.query(PropertyVisit.id).filter(PropertyVisit.property_id == prop.id)]
    if visit_ids:
        db.query(VisitAuditLog).filter(VisitAuditLog.visit_id.in_(visit_ids)).delete(synchronize_session=False)
    db.query(PropertyVisit).filter(PropertyVisit.property_id == prop.id).delete(synchronize_session=False)
    db.query(Property).filter(Property.id == prop.id).delete(synchronize_session=False)
    db.query(Agent).filter(Agent.id == agent.id).delete(synchronize_session=False)
    db.commit()
    db.close()


def _form(phone_property, **extra):
    data = {
        "visitor_name": f"{TAG} CLIENTE",
        "phone_country_code": "other",
        "phone_country_code_other": "41",
        "phone_number": "791234567",
        "purchase_fees": "2500",
        "notes": "Notas",
        "generate_sheet": "true",
        "agent_id": phone_property["agent_id"],
        "visit_mode": "solo",
    }
    data.update(extra)
    return data


def _visits(property_id):
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        return db.query(PropertyVisit).filter(PropertyVisit.property_id == property_id).all()
    finally:
        db.close()


@server
def test_alta_y_edicion_con_indicativo_otro(phone_property):
    prop_id = phone_property["property_id"]

    # El formulario de alta trae el selector con "Otro…" y el campo del indicativo
    status, body, _ = _request("GET", f"/visits/new/{prop_id}")
    assert status == 200
    assert 'name="phone_country_code"' in body and 'value="other"' in body
    assert 'name="phone_country_code_other"' in body
    assert "phone-field.js" in body

    # Indicativo que no existe: no se crea y vuelve al formulario
    status, _, headers = _request("POST", f"/visits/create/{prop_id}",
                                  _form(phone_property, phone_country_code_other="999"))
    assert status == 302 and headers["location"] == f"/visits/new/{prop_id}"
    assert _visits(prop_id) == []

    # Alta con "Otro…" + 41: se guarda con "+" y la vista previa lo agrupa
    status, _, headers = _request("POST", f"/visits/create/{prop_id}", _form(phone_property))
    assert status == 302 and "/visits/preview/" in headers["location"]
    (visit,) = _visits(prop_id)
    assert visit.phone == "+41791234567"
    status, body, _ = _request("GET", f"/visits/preview/{visit.id}")
    assert status == 200 and "+41 791 234 567" in body

    # La edición sale con "Otro…" seleccionado y el 41 escrito
    status, body, _ = _request("GET", f"/visits/edit/{visit.id}")
    assert status == 200
    assert 'value="other" data-full="Otro…" data-short="Otro" selected' in body
    assert 'name="phone_country_code_other"' in body and 'value="41"' in body
    assert 'value="791234567"' in body

    # Edición de vuelta a un país del selector: formato sin "+"
    status, _, _ = _request("POST", f"/visits/update/{visit.id}",
                            _form(phone_property, phone_country_code="34", phone_country_code_other="",
                                  phone_number="600 000 004"))
    assert status == 302
    (visit,) = _visits(prop_id)
    assert visit.phone == "34600000004"
