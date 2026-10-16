"""
Firma de los dos agentes en visitas conjuntas (PLAN_FIRMA_AGENTES_VISITA.md).

- Unitarios (sin base de datos): propiedades del modelo y protección de los
  endpoints /api/v1/visits/* con una app mínima (TestClient) y las búsquedas
  de usuario, empresa y visita sustituidas.
- Integración contra la app levantada (patrón de test_alert_assignment_routes.py,
  se omite si la app no responde): crea agentes, propiedades y visitas con
  el prefijo PYTEST-FIRMA-AGENTES y lo borra todo al terminar, incluidos los
  archivos de firma y los PDFs generados. Ninguna visita tiene teléfono, así
  que finalize no envía WhatsApp.

    docker exec moyza_backend python -m pytest tests/test_visit_agent_signatures.py -q
"""
import base64
import io
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import visits as visits_api
from app.db.deps import get_db
from app.models.agent import Agent
from app.models.property import Property
from app.models.property_visit import PropertyVisit


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def _signature_png(seed: int = 0) -> bytes:
    """PNG con trazos, válido para validate_signature_not_empty."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (700, 250), "white")
    draw = ImageDraw.Draw(img)
    for i in range(6):
        y = 60 + i * 25 + seed
        draw.line([(40, y), (660, 250 - y)], fill="black", width=4)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _signature_data_url(seed: int = 0) -> str:
    return "data:image/png;base64," + base64.b64encode(_signature_png(seed)).decode()


# ---------------------------------------------------------------------------
# Propiedades del modelo
# ---------------------------------------------------------------------------

@pytest.fixture
def signature_file(tmp_path):
    path = tmp_path / "firma.png"
    path.write_bytes(_signature_png())
    return str(path)


class TestAgentSignatureFile:

    def test_sin_firma(self):
        assert not Agent(name="A").has_signature_file

    def test_firma_registrada_sin_archivo(self, tmp_path):
        assert not Agent(name="A", signature_filepath=str(tmp_path / "no_existe.png")).has_signature_file

    def test_firma_registrada_con_archivo(self, signature_file):
        assert Agent(name="A", signature_filepath=signature_file).has_signature_file


class TestVisitAgentSignatureProperties:

    def test_individual_no_requiere_confirmacion(self):
        visit = PropertyVisit(agent_id=1)
        assert not visit.requires_agent_confirmation
        assert not visit.agent_signatures_confirmed
        assert visit.can_finalize_agents

    def test_conjunta_requiere_confirmacion(self):
        visit = PropertyVisit(agent_id=1, companion_agent_id=2)
        assert visit.requires_agent_confirmation
        assert not visit.can_finalize_agents

    def test_conjunta_confirmada(self):
        visit = PropertyVisit(agent_id=1, companion_agent_id=2,
                              agent_signatures_confirmed_at=datetime.utcnow())
        assert visit.agent_signatures_confirmed
        assert visit.can_finalize_agents

    def test_agentes_sin_firma(self, signature_file):
        principal = Agent(id=1, name="Principal", signature_filepath=signature_file)
        companion = Agent(id=2, name="Acompañante")
        visit = PropertyVisit(agent=principal, agent_id=1, companion_agent=companion, companion_agent_id=2)
        assert visit.agents_missing_signature == [companion]

        companion.signature_filepath = signature_file
        assert visit.agents_missing_signature == []

    def test_agentes_sin_firma_individual_solo_mira_al_principal(self):
        principal = Agent(id=1, name="Principal")
        visit = PropertyVisit(agent=principal, agent_id=1)
        assert visit.agents_missing_signature == [principal]

    def test_agentes_sin_firma_usa_el_agente_que_firma(self, signature_file):
        """Visita antigua sin agente: firma el captador de la propiedad."""
        captador = Agent(id=1, name="Captador", signature_filepath=signature_file)
        visit = PropertyVisit(property=Property(title="P", agent=captador))
        assert visit.agents_missing_signature == []


# ---------------------------------------------------------------------------
# Protección de /api/v1/visits/* (sin base de datos)
# ---------------------------------------------------------------------------

API_ENDPOINTS = [
    ("accept-terms", {"accepted": True}),
    ("save-signature", {"signature_data": "x"}),
    ("finalize", None),
    ("confirm-agent-signatures", {"confirmed": True}),
]


@pytest.fixture
def api_client(monkeypatch):
    """App mínima con el router de la API de visitas y sin base de datos real."""
    app = FastAPI()
    app.include_router(visits_api.router, prefix="/api/v1/visits")
    app.dependency_overrides[get_db] = lambda: None
    return TestClient(app)


def _post(client, endpoint, body, visit_id=1):
    return client.post(f"/api/v1/visits/{visit_id}/{endpoint}", json=body)


class TestApiProtection:

    @pytest.mark.parametrize("endpoint,body", API_ENDPOINTS)
    def test_sin_sesion_401(self, api_client, endpoint, body):
        """Sin cookie `access_token`, get_api_user devuelve None sin tocar la base."""
        response = _post(api_client, endpoint, body)
        assert response.status_code == 401

    @pytest.mark.parametrize("endpoint,body", API_ENDPOINTS)
    def test_visita_de_otra_empresa_404(self, api_client, monkeypatch, endpoint, body):
        user = SimpleNamespace(id=5)
        company = SimpleNamespace(id=2)
        seen = {}

        def fake_get_visit(db, visit_id, company_id):
            seen["args"] = (visit_id, company_id)
            return None  # la visita no está en la empresa activa

        monkeypatch.setattr(visits_api, "get_api_user", lambda request, db: user)
        monkeypatch.setattr(visits_api, "resolve_company_for_api", lambda request, u, db: company)
        monkeypatch.setattr(visits_api, "get_visit_in_company", fake_get_visit)

        response = _post(api_client, endpoint, body, visit_id=77)
        assert response.status_code == 404
        assert seen["args"] == (77, 2)

    def test_usuario_sin_empresa_404(self, api_client, monkeypatch):
        monkeypatch.setattr(visits_api, "get_api_user", lambda request, db: SimpleNamespace(id=5))
        monkeypatch.setattr(visits_api, "resolve_company_for_api", lambda request, u, db: None)
        response = _post(api_client, "accept-terms", {"accepted": True})
        assert response.status_code == 404

    def test_con_sesion_y_visita_de_la_empresa_sigue_el_flujo(self, api_client, monkeypatch):
        """Con sesión y visita propia, el endpoint aplica sus reglas de siempre."""
        visit = SimpleNamespace(id=1, visit_status="draft")
        monkeypatch.setattr(visits_api, "get_api_user", lambda request, db: SimpleNamespace(id=5))
        monkeypatch.setattr(visits_api, "resolve_company_for_api", lambda request, u, db: SimpleNamespace(id=1))
        monkeypatch.setattr(visits_api, "get_visit_in_company", lambda db, visit_id, company_id: visit)

        response = _post(api_client, "accept-terms", {"accepted": True})
        assert response.status_code == 400
        assert "preview" in response.json()["detail"]


# ---------------------------------------------------------------------------
# confirm-agent-signatures (sin base de datos)
# ---------------------------------------------------------------------------

class _FakeDB:
    def __init__(self):
        self.commits = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


def _fake_visit(**overrides):
    principal = SimpleNamespace(id=1, name="Ana Principal", signature_uploaded_at=datetime(2026, 1, 2, 10, 0))
    companion = SimpleNamespace(id=2, name="Luis Acompañante", signature_uploaded_at=datetime(2026, 3, 4, 11, 0))
    values = dict(
        id=10, visit_status="signed", requires_agent_confirmation=True,
        agent_signatures_confirmed=False, agents_missing_signature=[],
        signing_agent=principal, companion_agent=companion,
        agent_signatures_confirmed_at=None, agent_signatures_confirmed_by=None,
        agent_signatures_confirmed_ip=None,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture
def confirm_client(monkeypatch):
    """Cliente de la API con sesión, empresa y visita sustituidas."""
    state = {"visit": _fake_visit(), "db": _FakeDB(), "events": []}
    app = FastAPI()
    app.include_router(visits_api.router, prefix="/api/v1/visits")
    app.dependency_overrides[get_db] = lambda: state["db"]
    monkeypatch.setattr(visits_api, "get_api_user", lambda request, db: SimpleNamespace(id=5))
    monkeypatch.setattr(visits_api, "resolve_company_for_api", lambda request, u, db: SimpleNamespace(id=1))
    monkeypatch.setattr(visits_api, "get_visit_in_company", lambda db, visit_id, company_id: state["visit"])
    monkeypatch.setattr(visits_api, "log_visit_event",
                        lambda **kwargs: state["events"].append(kwargs))
    state["client"] = TestClient(app)
    return state


def _confirm(state, confirmed=True):
    return state["client"].post("/api/v1/visits/10/confirm-agent-signatures", json={"confirmed": confirmed})


class TestConfirmAgentSignatures:

    def test_confirma_y_registra_usuario_fecha_ip_y_auditoria(self, confirm_client):
        response = _confirm(confirm_client)
        assert response.status_code == 200
        assert response.json()["redirect_url"] == "/visits/complete/10"

        visit = confirm_client["visit"]
        assert visit.agent_signatures_confirmed_at is not None
        assert visit.agent_signatures_confirmed_by == 5
        assert visit.agent_signatures_confirmed_ip
        assert confirm_client["db"].commits == 1

        [event] = confirm_client["events"]
        assert event["event_type"] == "agent_signatures_confirmed"
        assert event["user_id"] == 5
        assert event["event_data"]["agent_id"] == 1
        assert event["event_data"]["companion_agent_id"] == 2
        assert event["event_data"]["agent_signature_uploaded_at"] == "2026-01-02T10:00:00"
        assert event["event_data"]["companion_signature_uploaded_at"] == "2026-03-04T11:00:00"

    def test_sin_marcar_la_casilla(self, confirm_client):
        assert _confirm(confirm_client, confirmed=False).status_code == 400

    @pytest.mark.parametrize("status", ["draft", "preview", "completed"])
    def test_solo_tras_la_firma_del_cliente(self, confirm_client, status):
        confirm_client["visit"].visit_status = status
        assert _confirm(confirm_client).status_code == 400

    def test_visita_individual(self, confirm_client):
        confirm_client["visit"].requires_agent_confirmation = False
        response = _confirm(confirm_client)
        assert response.status_code == 400
        assert "acompañante" in response.json()["detail"]

    def test_confirmacion_repetida(self, confirm_client):
        confirm_client["visit"].agent_signatures_confirmed = True
        assert _confirm(confirm_client).status_code == 409
        assert confirm_client["events"] == []

    def test_falta_firma_registrada_con_el_nombre(self, confirm_client):
        visit = confirm_client["visit"]
        visit.agents_missing_signature = [visit.companion_agent]
        response = _confirm(confirm_client)
        assert response.status_code == 400
        assert "Luis Acompañante no tiene firma registrada" in response.json()["detail"]
        assert visit.agent_signatures_confirmed_at is None


class TestFinalizeGuards:

    def test_conjunta_sin_confirmar_409_con_el_paso(self, confirm_client):
        confirm_client["visit"].signature_filepath = "firma.png"
        confirm_client["visit"].property_id = 3
        # finalize consulta la propiedad antes de las comprobaciones de estado
        db = confirm_client["db"]
        db.query = lambda model: SimpleNamespace(
            filter=lambda *a: SimpleNamespace(first=lambda: SimpleNamespace(id=3, title="P"))
        )
        response = confirm_client["client"].post("/api/v1/visits/10/finalize")
        assert response.status_code == 409
        assert response.json()["redirect_url"] == "/visits/agent-signatures/10"

    def test_conjunta_confirmada_sin_firma_registrada_400(self, confirm_client):
        visit = confirm_client["visit"]
        visit.signature_filepath = "firma.png"
        visit.property_id = 3
        visit.agent_signatures_confirmed = True
        visit.agents_missing_signature = [visit.signing_agent]
        confirm_client["db"].query = lambda model: SimpleNamespace(
            filter=lambda *a: SimpleNamespace(first=lambda: SimpleNamespace(id=3, title="P"))
        )
        response = confirm_client["client"].post("/api/v1/visits/10/finalize")
        assert response.status_code == 400
        assert "Ana Principal" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Integración contra la app levantada
# ---------------------------------------------------------------------------

BASE_URL = os.getenv("MOYZA_TEST_BASE_URL", "http://localhost:8000")
ADMIN_EMAIL = os.getenv("MOYZA_TEST_ADMIN_EMAIL", "admin@moyza.com")
TAG = "PYTEST-FIRMA-AGENTES"
EMAIL = "pytest.firma.agentes.{}@example.com"
AGENT_SIGNATURES_DIR = "storage/signatures/agents"


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

    def __init__(self, email=None, company="MOYZA"):
        self.cookie = None
        if email:
            from app.core.security import create_access_token
            token = create_access_token({"sub": email})
            self.cookie = f"access_token={token}; active_company={company}"
        self.opener = urllib.request.build_opener(self._NoRedirect)

    def _request(self, method, path, body=None, content_type=None):
        req = urllib.request.Request(BASE_URL + path, data=body, method=method)
        if self.cookie:
            req.add_header("Cookie", self.cookie)
        if content_type:
            req.add_header("Content-Type", content_type)
        try:
            resp = self.opener.open(req, timeout=60)
            return resp.status, resp.read().decode("utf-8", "replace"), dict(resp.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace"), dict(e.headers)

    def get(self, path):
        return self._request("GET", path)

    def post(self, path, data):
        return self._request("POST", path, urllib.parse.urlencode(data).encode(),
                             "application/x-www-form-urlencoded")

    def post_json(self, path, data=None):
        status, body, headers = self._request("POST", path, json.dumps(data or {}).encode(), "application/json")
        try:
            payload = json.loads(body)
        except ValueError:
            payload = {"raw": body}
        return status, payload


def _flash(headers) -> dict:
    """Primer mensaje del flash (cookie `moyza_flash`, lista JSON en base64 urlsafe)."""
    match = re.search(r'moyza_flash="?([^";]+)', headers.get("set-cookie", ""))
    if not match:
        return {}
    messages = json.loads(base64.urlsafe_b64decode(match.group(1)).decode("utf-8"))
    return messages[0] if messages else {}


def _session():
    from app.db.session import SessionLocal
    return SessionLocal()


def _write_agent_signature(agent_id: int) -> str:
    os.makedirs(AGENT_SIGNATURES_DIR, exist_ok=True)
    path = os.path.join(AGENT_SIGNATURES_DIR, f"pytest_firma_agentes_{agent_id}.png")
    with open(path, "wb") as f:
        f.write(_signature_png(agent_id % 7))
    return path


def _remove_file(path):
    if path and os.path.exists(path):
        os.remove(path)


def _cleanup(db):
    from app.models.notification import Notification

    db.rollback()
    props = db.query(Property).filter(Property.title.like(f"{TAG}%")).all()
    prop_ids = [p.id for p in props]
    visits = db.query(PropertyVisit).filter(PropertyVisit.property_id.in_(prop_ids)).all() if prop_ids else []
    for visit in visits:
        _remove_file(visit.signature_filepath)
        _remove_file(visit.visit_sheet_filepath)
    if visits:
        db.query(Notification).filter(
            Notification.entity_type == "visit",
            Notification.entity_id.in_([v.id for v in visits]),
        ).delete(synchronize_session=False)
    for visit in visits:
        db.delete(visit)  # audit_logs, OTP y logs de WhatsApp en cascada (ORM)
    db.flush()
    for prop in props:
        db.delete(prop)
    agents = db.query(Agent).filter(Agent.email.like(EMAIL.format("%"))).all()
    for agent in agents:
        _remove_file(agent.signature_filepath)
        db.delete(agent)
    db.commit()


@pytest.fixture(scope="module")
def data():
    if not _server_up():
        pytest.skip(f"La app no responde en {BASE_URL}; tests de integración omitidos")

    from app.models.company import Company

    db = _session()
    _cleanup(db)
    moyza = db.query(Company).filter_by(code="MOYZA").one()
    moes = db.query(Company).filter_by(code="MOES").one()

    agents = {}
    for key, company in (("principal", moyza), ("acomp", moes), ("sinfirma", moyza), ("moes", moes)):
        agent = Agent(name=f"{TAG} {key.upper()}", email=EMAIL.format(key))
        agent.companies.append(company)
        db.add(agent)
        agents[key] = agent
    db.flush()
    for key in ("principal", "acomp", "moes"):
        agents[key].signature_filepath = _write_agent_signature(agents[key].id)
        agents[key].signature_filename = os.path.basename(agents[key].signature_filepath)
        agents[key].signature_uploaded_at = datetime.utcnow()

    prop = Property(title=f"{TAG} PISO", address="Calle Firma 1", city="Jaen",
                    company_id=moyza.id, agent_id=agents["principal"].id)
    prop_moes = Property(title=f"{TAG} PISO MOES", address="Calle Firma 2", city="Jaen",
                         company_id=moes.id, agent_id=agents["moes"].id)
    db.add_all([prop, prop_moes])
    db.commit()

    out = {key: agent.id for key, agent in agents.items()}
    out.update(property_id=prop.id, property_moes_id=prop_moes.id)
    yield out

    _cleanup(db)
    db.close()


def _new_visit(property_id, agent_id, companion_agent_id=None, status="preview", name="CLIENTE"):
    """Visita sin teléfono (finalize no envía WhatsApp) lista para el flujo legal."""
    db = _session()
    try:
        visit = PropertyVisit(
            property_id=property_id,
            visitor_name=f"{TAG} {name}",
            phone=None,
            purchase_fees="2500",
            notes="test",
            agent_id=agent_id,
            companion_agent_id=companion_agent_id,
            visit_status=status,
        )
        db.add(visit)
        db.commit()
        return visit.id
    finally:
        db.close()


def _load_visit(visit_id):
    db = _session()
    try:
        return db.get(PropertyVisit, visit_id)
    finally:
        db.close()


def _sign_as_client(client, visit_id):
    status, payload = client.post_json(f"/api/v1/visits/{visit_id}/accept-terms", {"accepted": True})
    assert status == 200, payload
    status, payload = client.post_json(f"/api/v1/visits/{visit_id}/save-signature",
                                       {"signature_data": _signature_data_url()})
    assert status == 200, payload
    return payload


def test_endpoints_sin_sesion_responden_401(data):
    visit_id = _new_visit(data["property_id"], data["principal"])
    anonymous = _Client()
    for endpoint, body in API_ENDPOINTS:
        status, _ = anonymous.post_json(f"/api/v1/visits/{visit_id}/{endpoint}", body)
        assert status == 401, endpoint
    # Nada cambió en la visita
    visit = _load_visit(visit_id)
    assert visit.visit_status == "preview" and not visit.data_consent_accepted


def test_endpoints_con_visita_de_otra_empresa_responden_404(data):
    visit_id = _new_visit(data["property_moes_id"], data["moes"])
    admin_moyza = _Client(ADMIN_EMAIL, "MOYZA")
    for endpoint, body in API_ENDPOINTS:
        status, _ = admin_moyza.post_json(f"/api/v1/visits/{visit_id}/{endpoint}", body)
        assert status == 404, endpoint
    assert _load_visit(visit_id).visit_status == "preview"


def test_flujo_completo_de_una_visita_individual_con_sesion(data):
    visit_id = _new_visit(data["property_id"], data["principal"], name="INDIVIDUAL")
    admin = _Client(ADMIN_EMAIL, "MOYZA")

    payload = _sign_as_client(admin, visit_id)
    assert payload["redirect_url"] == f"/visits/complete/{visit_id}"

    status, payload = admin.post_json(f"/api/v1/visits/{visit_id}/finalize")
    assert status == 200, payload
    assert payload["pdf_generated"] is True

    visit = _load_visit(visit_id)
    assert visit.visit_status == "completed"
    assert visit.visit_sheet_filepath and os.path.exists(visit.visit_sheet_filepath)
    assert visit.agent_signatures_confirmed_at is None


# ---------------------------------------------------------------------------
# Integración: paso de confirmación (fase 2)
# ---------------------------------------------------------------------------

def _audit_events(visit_id, event_type):
    from app.models.visit_audit_log import VisitAuditLog
    db = _session()
    try:
        return (
            db.query(VisitAuditLog)
            .filter(VisitAuditLog.visit_id == visit_id, VisitAuditLog.event_type == event_type)
            .all()
        )
    finally:
        db.close()


def _admin_id():
    from app.models.user import User
    db = _session()
    try:
        return db.query(User).filter(User.email == ADMIN_EMAIL).one().id
    finally:
        db.close()


def test_visita_individual_no_pasa_por_el_paso(data):
    visit_id = _new_visit(data["property_id"], data["principal"], name="INDIVIDUAL PASO")
    admin = _Client(ADMIN_EMAIL, "MOYZA")
    payload = _sign_as_client(admin, visit_id)
    assert payload["redirect_url"] == f"/visits/complete/{visit_id}"

    status, _, headers = admin.get(f"/visits/agent-signatures/{visit_id}")
    assert status == 302 and headers.get("location") == f"/visits/complete/{visit_id}"
    status, _, _ = admin.get(f"/visits/complete/{visit_id}")
    assert status == 200

    status, payload = admin.post_json(f"/api/v1/visits/{visit_id}/confirm-agent-signatures", {"confirmed": True})
    assert status == 400


def test_visita_conjunta_confirmada_y_finalizada(data):
    visit_id = _new_visit(data["property_id"], data["principal"], data["acomp"], name="CONJUNTA")
    admin = _Client(ADMIN_EMAIL, "MOYZA")

    # Antes de la firma del cliente no se puede confirmar
    status, _ = admin.post_json(f"/api/v1/visits/{visit_id}/confirm-agent-signatures", {"confirmed": True})
    assert status == 400

    payload = _sign_as_client(admin, visit_id)
    assert payload["redirect_url"] == f"/visits/agent-signatures/{visit_id}"

    # Sin confirmar no se finaliza ni se abre la página de finalizar
    status, payload = admin.post_json(f"/api/v1/visits/{visit_id}/finalize")
    assert status == 409 and payload["redirect_url"] == f"/visits/agent-signatures/{visit_id}"
    status, _, headers = admin.get(f"/visits/complete/{visit_id}")
    assert status == 302 and headers.get("location") == f"/visits/agent-signatures/{visit_id}"
    assert _flash(headers).get("category") == "warning"

    status, body, _ = admin.get(f"/visits/agent-signatures/{visit_id}")
    assert status == 200
    assert "Firmas de los agentes" in body
    assert f"{TAG} PRINCIPAL" in body and f"{TAG} ACOMP" in body
    assert "Confirmo que la ficha de visita se firma" in body
    assert "Sin firma registrada" not in body

    status, payload = admin.post_json(f"/api/v1/visits/{visit_id}/confirm-agent-signatures", {"confirmed": True})
    assert status == 200 and payload["redirect_url"] == f"/visits/complete/{visit_id}"

    visit = _load_visit(visit_id)
    assert visit.agent_signatures_confirmed_at is not None
    assert visit.agent_signatures_confirmed_by == _admin_id()
    assert visit.agent_signatures_confirmed_ip

    [event] = _audit_events(visit_id, "agent_signatures_confirmed")
    assert event.user_id == _admin_id()
    assert event.event_data["agent_id"] == data["principal"]
    assert event.event_data["companion_agent_id"] == data["acomp"]
    assert event.event_data["agent_signature_uploaded_at"]
    assert event.event_data["companion_signature_uploaded_at"]

    # Repetida: rechazada. Quitar acompañante después de confirmar: rechazado
    status, _ = admin.post_json(f"/api/v1/visits/{visit_id}/confirm-agent-signatures", {"confirmed": True})
    assert status == 409
    status, _, headers = admin.post(f"/visits/{visit_id}/remove-companion", {})
    assert status == 302 and _flash(headers).get("category") == "error"
    assert _load_visit(visit_id).companion_agent_id == data["acomp"]

    # La página muestra el resumen y deja continuar
    status, body, _ = admin.get(f"/visits/agent-signatures/{visit_id}")
    assert status == 200 and "Firmas confirmadas" in body and "Confirmado por" in body

    status, _, _ = admin.get(f"/visits/complete/{visit_id}")
    assert status == 200
    status, payload = admin.post_json(f"/api/v1/visits/{visit_id}/finalize")
    assert status == 200, payload
    visit = _load_visit(visit_id)
    assert visit.visit_status == "completed"
    assert visit.companion_agent_id == data["acomp"]


def test_acompanante_sin_firma_bloquea_y_se_puede_quitar(data):
    visit_id = _new_visit(data["property_id"], data["principal"], data["sinfirma"], name="SIN FIRMA")
    admin = _Client(ADMIN_EMAIL, "MOYZA")
    _sign_as_client(admin, visit_id)

    status, body, _ = admin.get(f"/visits/agent-signatures/{visit_id}")
    assert status == 200
    assert "Sin firma registrada" in body
    assert f"Falta la firma registrada de {TAG} SINFIRMA" in body

    status, payload = admin.post_json(f"/api/v1/visits/{visit_id}/confirm-agent-signatures", {"confirmed": True})
    assert status == 400
    assert f"{TAG} SINFIRMA no tiene firma registrada" in payload["detail"]
    assert _load_visit(visit_id).agent_signatures_confirmed_at is None

    status, _, headers = admin.post(f"/visits/{visit_id}/remove-companion", {})
    assert status == 302 and headers.get("location") == f"/visits/complete/{visit_id}"
    assert _flash(headers).get("category") == "success"

    visit = _load_visit(visit_id)
    assert visit.companion_agent_id is None
    assert not visit.requires_agent_confirmation
    [event] = _audit_events(visit_id, "companion_removed_before_confirmation")
    assert event.event_data["companion_agent_id"] == data["sinfirma"]
    assert event.event_data["agent_id"] == data["principal"]

    # Ya es individual: se finaliza sin confirmación
    status, _, _ = admin.get(f"/visits/complete/{visit_id}")
    assert status == 200
    status, payload = admin.post_json(f"/api/v1/visits/{visit_id}/finalize")
    assert status == 200, payload
    assert _load_visit(visit_id).visit_status == "completed"
