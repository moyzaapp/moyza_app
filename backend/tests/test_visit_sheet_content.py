"""
Contenido de la ficha de visita y de su vista previa (PLAN_CEDER_COMPRADORES.md).

- §3 Observaciones internas: no salen en el PDF ni en el preview (lo que firma
  el cliente) y sí en la app (listado de visitas y ficha de la propiedad), con
  un panel lateral que lee el texto de data-* escapados.

Unitarios: generan el PDF de verdad y leen su texto con pypdf (se omiten si no
está instalado). Integración contra la app levantada (se omite si no responde):
crea un agente, una propiedad y una visita en MOYZA y los borra al final.

    docker exec moyza_backend python -m pytest tests/test_visit_sheet_content.py -q
"""
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from types import SimpleNamespace

import pytest


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

def _visit(**overrides):
    data = dict(
        id=9, created_at=datetime(2026, 10, 16, 12, 0), visitor_name="Cliente Prueba", dni="1",
        phone=None, email=None, purchase_fees_display="€2500 + IVA", interest_level=4,
        price_feedback=None, location_feedback=None, condition_feedback=None, lighting_feedback=None,
        elevator_feedback=None, garage_feedback=None, notes=None, signature_filepath=None,
        signature_captured_at=None, data_consent_accepted_at=None,
        data_consent_ip=None, agent_signatures_confirmed_at=None,
    )
    data.update(overrides)
    return SimpleNamespace(**data)


def _pdf_text(tmp_path, visit, agent=None):
    """Genera la ficha y devuelve su texto extraído con pypdf."""
    pypdf = pytest.importorskip("pypdf")
    from app.services import visit_sheet_generator as generator

    output = tmp_path / "ficha.pdf"
    generator.generate_visit_sheet(
        property_item=SimpleNamespace(id=3, address="Calle 1", title="Piso", price=100000, company=None),
        visit=visit,
        agent=agent or SimpleNamespace(name="Ana Agente", signature_filepath=None, signature_uploaded_at=None),
        output_path=str(output),
    )
    return " ".join(page.extract_text() for page in pypdf.PdfReader(str(output)).pages)


def test_pdf_sin_observaciones(tmp_path):
    text = _pdf_text(tmp_path, _visit(notes="TEXTO SECRETO del equipo"))
    assert "Cliente Prueba" in text           # el PDF se generó con los datos de la visita
    assert "TEXTO SECRETO" not in text
    assert "Observaciones" not in text


# ---------------------------------------------------------------------------
# Integración: preview, listado y ficha de la propiedad
# ---------------------------------------------------------------------------

BASE_URL = os.getenv("MOYZA_TEST_BASE_URL", "http://localhost:8000")
ADMIN_EMAIL = os.getenv("MOYZA_TEST_ADMIN_EMAIL", "admin@moyza.com")
TAG = "PYTEST-FICHA"
NOTES = 'Nota interna <b>PYTEST</b> "con comillas"'


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


def _get(path):
    from app.core.security import create_access_token
    token = create_access_token({"sub": ADMIN_EMAIL})
    req = urllib.request.Request(BASE_URL + path)
    req.add_header("Cookie", f"access_token={token}; active_company=MOYZA")
    try:
        resp = urllib.request.build_opener(_NoRedirect).open(req, timeout=20)
        return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


@pytest.fixture(scope="module")
def visit_with_notes():
    from app.db.session import SessionLocal
    from app.models.agent import Agent
    from app.models.company import Company
    from app.models.property import Property
    from app.models.property_visit import PropertyVisit
    from app.models.visit_audit_log import VisitAuditLog

    db = SessionLocal()
    moyza = db.query(Company).filter_by(code="MOYZA").one()
    agent = Agent(name=f"{TAG} AGENTE", email="pytest.ficha@example.com")
    agent.companies.append(moyza)
    db.add(agent)
    db.flush()
    prop = Property(title=f"{TAG} PROP", company_id=moyza.id, agent_id=agent.id)
    db.add(prop)
    db.flush()
    visit = PropertyVisit(property_id=prop.id, visitor_name=f"{TAG} CLIENTE", phone="34600000003",
                          purchase_fees="2500", notes=NOTES, agent_id=agent.id, visit_status="preview")
    db.add(visit)
    db.commit()

    yield {"property_id": prop.id, "visit_id": visit.id}

    db.query(VisitAuditLog).filter(VisitAuditLog.visit_id == visit.id).delete(synchronize_session=False)
    db.query(PropertyVisit).filter(PropertyVisit.property_id == prop.id).delete(synchronize_session=False)
    db.query(Property).filter(Property.id == prop.id).delete(synchronize_session=False)
    db.query(Agent).filter(Agent.id == agent.id).delete(synchronize_session=False)
    db.commit()
    db.close()


ESCAPED_NOTES = "Nota interna &lt;b&gt;PYTEST&lt;/b&gt; &#34;con comillas&#34;"


@server
def test_preview_sin_observaciones(visit_with_notes):
    status, body = _get(f"/visits/preview/{visit_with_notes['visit_id']}")
    assert status == 200
    assert f"{TAG} CLIENTE" in body
    assert "PYTEST</b>" not in body and "PYTEST&lt;/b&gt;" not in body
    assert "Observaciones" not in body


@server
@pytest.mark.parametrize("path", ["/visits", "/properties/{property_id}"])
def test_observaciones_en_la_app(visit_with_notes, path):
    status, body = _get(path.format(**visit_with_notes))
    assert status == 200
    # Botón de la fila con el texto escapado en data-* y un único panel por página
    assert f'data-visit-notes="{ESCAPED_NOTES}"' in body
    assert "<b>PYTEST</b>" not in body
    assert body.count('id="visitNotesDrawer"') == 1
    assert f"Ver observaciones internas de la visita de {TAG} CLIENTE" in body


@server
def test_formulario_de_edicion_etiqueta_interna(visit_with_notes):
    status, body = _get(f"/visits/edit/{visit_with_notes['visit_id']}")
    assert status == 200
    assert "Observaciones internas" in body
    assert "no salen en la ficha que firma el cliente" in body
