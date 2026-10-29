"""
Honorarios en caso de compra en importe o porcentaje (PLAN_CEDER_COMPRADORES.md §2).

- Unitarios (sin base de datos): limpieza, unidad, importe y texto del informe
  del modelo, y composición y validación del formulario en la ruta.
- Integración contra la app levantada (se omite si no responde): alta y
  edición con porcentaje. Crea un agente y una propiedad en MOYZA y los borra.

    docker exec moyza_backend python -m pytest tests/test_visit_purchase_fees.py -q
"""
import os
import urllib.error
import urllib.parse
import urllib.request

import pytest

from app.models.property_visit import PropertyVisit
from app.web.routes.visits import purchase_fees_error
from app.web.routes.visits import purchase_fees_from_form


# ---------------------------------------------------------------------------
# Modelo
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("2500", "2500"),
    ("€ 2.500 + IVA", "2.500"),
    ("2 % + IVA", "2%"),
    ("2,5%", "2,5%"),
    (None, ""),
])
def test_clean_purchase_fees_conserva_el_porcentaje(raw, expected):
    assert PropertyVisit.clean_purchase_fees(raw) == expected


@pytest.mark.parametrize("stored, unit, amount, display", [
    ("2500", "€", "2500", "€2500 + IVA"),
    ("2%", "%", "2", "2% + IVA"),
    ("2,5%", "%", "2,5", "2,5% + IVA"),
    (None, "€", "", None),
])
def test_unidad_importe_y_texto_del_informe(stored, unit, amount, display):
    visit = PropertyVisit(purchase_fees=stored)
    assert visit.purchase_fees_unit == unit
    assert visit.purchase_fees_amount == amount
    assert visit.purchase_fees_display == display


# ---------------------------------------------------------------------------
# Formulario
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("form, expected", [
    ({"purchase_fees": "2500"}, "2500"),
    ({"purchase_fees": "2500", "purchase_fees_unit": "€"}, "2500"),
    ({"purchase_fees": "3", "purchase_fees_unit": "%"}, "3%"),
    ({"purchase_fees": "3 %", "purchase_fees_unit": "%"}, "3%"),
    # El '%' escrito en el campo vale aunque el selector diga €
    ({"purchase_fees": "3%", "purchase_fees_unit": "€"}, "3%"),
    ({"purchase_fees": "", "purchase_fees_unit": "%"}, ""),
])
def test_purchase_fees_from_form(form, expected):
    assert purchase_fees_from_form(form) == expected


@pytest.mark.parametrize("value", ["2500", "2.500", "2500,50", "0%", "2%", "2,5%", "100%"])
def test_honorarios_validos(value):
    assert purchase_fees_error(value) is None


def test_porcentaje_fuera_de_rango():
    for value in ("101%", "150%", "1.2.3%"):
        assert purchase_fees_error(value) == "El porcentaje de honorarios debe estar entre 0 y 100"


def test_formato_no_valido():
    for value in ("abc", "%", "2%%", "%2"):
        assert purchase_fees_error(value).startswith("Los honorarios deben ser")


# ---------------------------------------------------------------------------
# Integración: alta y edición con porcentaje
# ---------------------------------------------------------------------------

BASE_URL = os.getenv("MOYZA_TEST_BASE_URL", "http://localhost:8000")
ADMIN_EMAIL = os.getenv("MOYZA_TEST_ADMIN_EMAIL", "admin@moyza.com")
TAG = "PYTEST-HONORARIOS"


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
def fees_property():
    from app.db.session import SessionLocal
    from app.models.agent import Agent
    from app.models.company import Company
    from app.models.property import Property
    from app.models.visit_audit_log import VisitAuditLog

    db = SessionLocal()
    moyza = db.query(Company).filter_by(code="MOYZA").one()
    agent = Agent(name=f"{TAG} AGENTE", email="pytest.honorarios@example.com")
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


def _form(fees_property, **extra):
    data = {
        "visitor_name": f"{TAG} CLIENTE",
        "phone_country_code": "34",
        "phone_number": "600000002",
        "purchase_fees": "2500",
        "notes": "Notas",
        "generate_sheet": "true",
        "agent_id": fees_property["agent_id"],
        "visit_mode": "solo",
    }
    data.update(extra)
    return data


def _visit(property_id):
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        return db.query(PropertyVisit).filter(PropertyVisit.property_id == property_id).one()
    finally:
        db.close()


@server
def test_alta_y_edicion_con_porcentaje(fees_property):
    prop_id = fees_property["property_id"]

    # El formulario de alta trae el selector € | %
    status, body, _ = _request("GET", f"/visits/new/{prop_id}")
    assert status == 200
    assert 'name="purchase_fees_unit"' in body and '<option value="%">%</option>' in body

    # Porcentaje fuera de rango: no se crea
    status, _, headers = _request("POST", f"/visits/create/{prop_id}",
                                  _form(fees_property, purchase_fees="120", purchase_fees_unit="%"))
    assert status == 302 and headers["location"] == f"/visits/new/{prop_id}"

    # Alta con porcentaje: se guarda "2,5%" y el preview dice "2,5% + IVA"
    status, _, headers = _request("POST", f"/visits/create/{prop_id}",
                                  _form(fees_property, purchase_fees="2,5", purchase_fees_unit="%"))
    assert status == 302 and "/visits/preview/" in headers["location"]
    visit = _visit(prop_id)
    assert visit.purchase_fees == "2,5%"
    status, body, _ = _request("GET", f"/visits/preview/{visit.id}")
    assert status == 200 and "2,5% + IVA" in body

    # La edición rellena el selector en % y el importe sin signo
    status, body, _ = _request("GET", f"/visits/edit/{visit.id}")
    assert status == 200
    assert '<option value="%" selected>%</option>' in body
    assert 'value="2,5"' in body

    # Edición de vuelta a euros
    status, _, _ = _request("POST", f"/visits/update/{visit.id}",
                            _form(fees_property, purchase_fees="3000", purchase_fees_unit="€"))
    assert status == 302
    visit = _visit(prop_id)
    assert visit.purchase_fees == "3000" and visit.purchase_fees_display == "€3000 + IVA"
