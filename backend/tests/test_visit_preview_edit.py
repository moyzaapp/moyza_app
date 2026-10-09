"""
"Volver a editar datos" desde la vista previa de una visita
(PLAN_DASHBOARD_INICIO.md, fase 1, arreglo previo 2).

Antes el botón llevaba a /visits/new/{propiedad} y al guardar se creaba una
segunda visita. Ahora lleva a /visits/edit/{visita} y, si la visita sigue
sin firmar (draft / preview), al guardar se vuelve a la vista previa.

Integración contra la app levantada (se omite si no responde). Crea un
agente, una propiedad y una visita en borrador en MOYZA y lo borra al final.

    docker exec moyza_backend python -m pytest tests/test_visit_preview_edit.py -q
"""
import os
import urllib.error
import urllib.parse
import urllib.request

import pytest

BASE_URL = os.getenv("MOYZA_TEST_BASE_URL", "http://localhost:8000")
ADMIN_EMAIL = os.getenv("MOYZA_TEST_ADMIN_EMAIL", "admin@moyza.com")
TAG = "PYTEST-PREVIEW-EDIT"


def _server_up() -> bool:
    try:
        urllib.request.urlopen(BASE_URL + "/", timeout=3)
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
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
def draft_visit():
    from app.db.session import SessionLocal
    from app.models.agent import Agent
    from app.models.company import Company
    from app.models.property import Property
    from app.models.property_visit import PropertyVisit
    from app.models.visit_audit_log import VisitAuditLog

    db = SessionLocal()
    moyza = db.query(Company).filter_by(code="MOYZA").one()
    agent = Agent(name=f"{TAG} AGENTE", email="pytest.preview.edit@example.com")
    agent.companies.append(moyza)
    db.add(agent)
    db.flush()
    prop = Property(title=f"{TAG} PROP", company_id=moyza.id, agent_id=agent.id)
    db.add(prop)
    db.flush()
    visit = PropertyVisit(property_id=prop.id, visitor_name="Visitante original", phone="34600000000",
                          purchase_fees="2500", notes="Notas", agent_id=agent.id, visit_status="draft")
    db.add(visit)
    db.commit()

    data = {"agent_id": agent.id, "property_id": prop.id, "visit_id": visit.id}
    yield data

    db.query(VisitAuditLog).filter(VisitAuditLog.visit_id == visit.id).delete(synchronize_session=False)
    db.query(PropertyVisit).filter(PropertyVisit.property_id == prop.id).delete(synchronize_session=False)
    db.query(Property).filter(Property.id == prop.id).delete(synchronize_session=False)
    db.query(Agent).filter(Agent.id == agent.id).delete(synchronize_session=False)
    db.commit()
    db.close()


def _visit_count(property_id):
    from app.db.session import SessionLocal
    from app.models.property_visit import PropertyVisit
    db = SessionLocal()
    try:
        return db.query(PropertyVisit).filter(PropertyVisit.property_id == property_id).count()
    finally:
        db.close()


def test_el_preview_enlaza_a_editar_la_misma_visita(draft_visit):
    status, body, _ = _request("GET", f"/visits/preview/{draft_visit['visit_id']}")
    assert status == 200
    assert f'href="/visits/edit/{draft_visit["visit_id"]}"' in body
    assert f'href="/visits/new/{draft_visit["property_id"]}"' not in body


def test_editar_desde_el_preview_no_crea_otra_visita_y_vuelve_al_preview(draft_visit):
    before = _visit_count(draft_visit["property_id"])

    status, _, headers = _request("POST", f"/visits/update/{draft_visit['visit_id']}", {
        "visitor_name": "Visitante corregido",
        "phone_country_code": "34",
        "phone_number": "600000001",
        "purchase_fees": "3000",
        "notes": "Notas corregidas",
        "agent_id": draft_visit["agent_id"],
        "visit_mode": "solo",
    })

    assert status == 302
    assert headers.get("location") == f"/visits/preview/{draft_visit['visit_id']}"
    assert _visit_count(draft_visit["property_id"]) == before

    from app.db.session import SessionLocal
    from app.models.property_visit import PropertyVisit
    db = SessionLocal()
    try:
        visit = db.get(PropertyVisit, draft_visit["visit_id"])
        assert visit.visitor_name == "Visitante corregido"
        assert visit.purchase_fees == "3000"
        assert visit.visit_status in ("draft", "preview")
    finally:
        db.close()
