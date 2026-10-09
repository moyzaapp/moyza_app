"""
Tests de ruta del Inicio y las notificaciones (PLAN_DASHBOARD_INICIO.md, fase 5).

Integración contra la app levantada (se omiten si no responde), patrón de
test_commercial_results.py:

- /dashboard para admin y agente en las dos empresas; el agente ya no
  recibe "Acceso denegado"; usuario sin ficha de agente -> vista mínima.
- Aislamiento: el admin cambia de empresa y el Inicio cambia por completo.
- Flujo de visita cruzada: un agente registra una visita en la propiedad
  de otro -> el captador tiene una notificación sin leer (solo en esa
  empresa) -> la abre y queda leída.
- API de la campana: 401 sin sesión, contador, recientes y marcar leídas.

Crea agentes, usuarios, propiedades y visitas con la etiqueta del TAG y lo
borra todo al final.

    docker exec moyza_backend python -m pytest tests/test_dashboard_routes.py -q
"""
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

import pytest

BASE_URL = os.getenv("MOYZA_TEST_BASE_URL", "http://localhost:8000")
ADMIN_EMAIL = os.getenv("MOYZA_TEST_ADMIN_EMAIL", "admin@moyza.com")
TAG = "PYTEST-INICIO"
OWNER_EMAIL = "pytest.inicio.captador@example.com"
VISITOR_EMAIL = "pytest.inicio.visitante@example.com"
NO_AGENT_EMAIL = "pytest.inicio.sinficha@example.com"


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


class Client:
    """Peticiones con cookies de sesión y empresa, sin seguir redirecciones."""

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    def __init__(self, email, company):
        from app.core.security import create_access_token
        self.cookie = f"access_token={create_access_token({'sub': email})}; active_company={company}" if email \
            else f"active_company={company}"
        self.opener = urllib.request.build_opener(self._NoRedirect)

    def request(self, method, path, data=None, json_body=None):
        req = urllib.request.Request(BASE_URL + path, method=method)
        if data is not None:
            req.data = urllib.parse.urlencode(data).encode()
        if json_body is not None:
            req.data = json.dumps(json_body).encode()
            req.add_header("Content-Type", "application/json")
        req.add_header("Cookie", self.cookie)
        try:
            resp = self.opener.open(req, timeout=20)
            return resp.status, resp.read().decode("utf-8", "replace"), dict(resp.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace"), dict(e.headers)

    def get(self, path):
        return self.request("GET", path)


def _text(html):
    html = re.sub(r"<script.*?</script>", " ", html, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


@pytest.fixture(scope="module")
def setup():
    """Captador (MOYZA y MOES) y visitante (MOYZA) con sus usuarios; un usuario sin ficha."""
    from app.db.session import SessionLocal
    from app.models.agent import Agent
    from app.models.company import Company
    from app.models.property import Property
    from app.models.role import Role
    from app.models.user import User

    db = SessionLocal()
    moyza = db.query(Company).filter_by(code="MOYZA").one()
    moes = db.query(Company).filter_by(code="MOES").one()
    role = db.query(Role).filter(Role.name.ilike("agent")).first()
    role_id = role.id if role else None

    owner = Agent(name=f"{TAG} CAPTADOR", email=OWNER_EMAIL)
    owner.companies.extend([moyza, moes])
    visitor = Agent(name=f"{TAG} VISITANTE", email=VISITOR_EMAIL)
    visitor.companies.append(moyza)
    users = [
        User(email=email, full_name=f"{TAG} {email.split('@')[0]}", hashed_password="pytest-sin-login",
             role_id=role_id, is_active=True)
        for email in (OWNER_EMAIL, VISITOR_EMAIL, NO_AGENT_EMAIL)
    ]
    for user in users:
        user.companies.append(moyza)
    db.add_all([owner, visitor, *users])
    db.flush()
    moyza_prop = Property(title=f"{TAG} PROP MOYZA", company_id=moyza.id, agent_id=owner.id,
                          business_type="Venta", market_entry_date=datetime(2020, 1, 1), status="Activa")
    moes_prop = Property(title=f"{TAG} PROP MOES", company_id=moes.id, agent_id=owner.id,
                         business_type="Alquiler", market_entry_date=datetime.utcnow(), status="Activa")
    db.add_all([moyza_prop, moes_prop])
    db.commit()

    data = {"owner_id": owner.id, "visitor_id": visitor.id, "moyza_prop": moyza_prop.id, "moes_prop": moes_prop.id,
            "moyza_id": moyza.id, "moes_id": moes.id, "owner_user_id": users[0].id}
    yield data

    from app.models.notification import Notification
    from app.models.property_visit import PropertyVisit
    from app.models.visit_audit_log import VisitAuditLog
    user_ids = [u.id for u in db.query(User).filter(User.email.in_([OWNER_EMAIL, VISITOR_EMAIL, NO_AGENT_EMAIL]))]
    db.query(Notification).filter(Notification.user_id.in_(user_ids)).delete(synchronize_session=False)
    prop_ids = [moyza_prop.id, moes_prop.id]
    visit_ids = [v.id for v in db.query(PropertyVisit.id).filter(PropertyVisit.property_id.in_(prop_ids))]
    if visit_ids:
        db.query(VisitAuditLog).filter(VisitAuditLog.visit_id.in_(visit_ids)).delete(synchronize_session=False)
        db.query(PropertyVisit).filter(PropertyVisit.id.in_(visit_ids)).delete(synchronize_session=False)
    db.query(Property).filter(Property.id.in_(prop_ids)).delete(synchronize_session=False)
    db.query(User).filter(User.id.in_(user_ids)).delete(synchronize_session=False)
    db.query(Agent).filter(Agent.email.in_([OWNER_EMAIL, VISITOR_EMAIL])).delete(synchronize_session=False)
    db.commit()
    db.close()


# ---------------------------------------------------------------------------
# Inicio por rol
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("company", ["MOYZA", "MOES"])
def test_admin_ve_el_inicio_del_equipo(setup, company):
    status, body, _ = Client(ADMIN_EMAIL, company).get("/dashboard")
    assert status == 200
    assert "Cumplimiento del equipo" in body and "Requiere atención" in body
    # Sin campana para el admin en v1 (decisión §6-3)
    assert 'id="notifBell"' not in body


def test_cambiar_de_empresa_cambia_el_inicio(setup):
    _, moyza_body, _ = Client(ADMIN_EMAIL, "MOYZA").get("/dashboard")
    _, moes_body, _ = Client(ADMIN_EMAIL, "MOES").get("/dashboard")
    # La captación de esta semana en MOES solo aparece en el Inicio de MOES
    assert f"{TAG} PROP MOES" in moes_body
    assert f"{TAG} PROP MOES" not in moyza_body
    assert "MOES PREMIUM ·" in _text(moes_body)
    assert "MOYZA ·" in _text(moyza_body)


@pytest.mark.parametrize("company", ["MOYZA", "MOES"])
def test_agente_aterriza_en_su_inicio_sin_errores(setup, company):
    status, body, _ = Client(OWNER_EMAIL, company).get("/dashboard")
    assert status == 200
    text = _text(body)
    assert "Acceso denegado" not in text
    assert "Hola," in text and "Mis resultados" in text
    assert "Novedades" in text and "Hoy y pendiente" in text
    assert 'id="notifBell"' in body
    # Solo lo suyo: sin la tabla del equipo
    assert "Cumplimiento del equipo" not in text


def test_periodos_del_agente(setup):
    client = Client(OWNER_EMAIL, "MOYZA")
    for query in ("period_type=MONTHLY", "period_type=YEARLY", "period_type=WEEKLY&period_start=2026-01-07",
                  "period_type=XXX&period_start=basura"):
        status, _, _ = client.get(f"/dashboard?{query}")
        assert status == 200, query


def test_usuario_sin_ficha_de_agente_ve_aviso(setup):
    status, body, _ = Client(NO_AGENT_EMAIL, "MOYZA").get("/dashboard")
    assert status == 200
    assert "no está vinculado a una ficha de agente" in _text(body)


# ---------------------------------------------------------------------------
# Visita cruzada -> notificación al captador
# ---------------------------------------------------------------------------

def test_visita_cruzada_notifica_al_captador_y_se_marca_leida(setup):
    owner_moyza = Client(OWNER_EMAIL, "MOYZA")
    owner_moes = Client(OWNER_EMAIL, "MOES")
    visitor = Client(VISITOR_EMAIL, "MOYZA")

    _, body, _ = owner_moyza.get("/api/notifications/unread-count")
    before = json.loads(body)["unread_count"]

    status, _, headers = visitor.request("POST", f"/visits/create/{setup['moyza_prop']}", data={
        "visitor_name": f"{TAG} Comprador", "phone_country_code": "34", "phone_number": "600123456",
        "purchase_fees": "2500", "notes": "Visita de prueba", "visit_mode": "solo",
    })
    assert status == 302 and headers.get("location") == f"/properties/{setup['moyza_prop']}"

    _, body, _ = owner_moyza.get("/api/notifications/unread-count")
    assert json.loads(body)["unread_count"] == before + 1
    # Aislada por empresa: con MOES activa no aparece
    _, body, _ = owner_moes.get("/api/notifications/unread-count")
    assert json.loads(body)["unread_count"] == 0
    # El actor no recibe nada
    _, body, _ = visitor.get("/api/notifications/unread-count")
    assert json.loads(body)["unread_count"] == 0

    _, body, _ = owner_moyza.get("/api/notifications/recent")
    item = next(i for i in json.loads(body)["items"] if i["kind"] == "visit_on_my_property")
    assert item["title"] == f"{TAG} VISITANTE visitó tu inmueble"
    assert not item["read"]

    # En el Inicio y en /notifications
    assert item["title"] in owner_moyza.get("/dashboard")[1]
    assert item["title"] in owner_moyza.get("/notifications?status=unread")[1]

    # Abrirla la marca como leída y lleva a la propiedad
    status, _, headers = owner_moyza.get(item["url"])
    assert status == 302 and headers.get("location") == f"/properties/{setup['moyza_prop']}"
    _, body, _ = owner_moyza.get("/api/notifications/unread-count")
    assert json.loads(body)["unread_count"] == before


def test_api_mark_read_y_sin_sesion(setup):
    from app.db.session import SessionLocal
    from app.services import notification_service as ns

    db = SessionLocal()
    try:
        ns.notify(db, users=[type("U", (), {"id": setup["owner_user_id"]})()], company_id=setup["moes_id"],
                  kind="admin_note_added", title=f"{TAG} nota MOES", url="/dashboard")
        db.commit()
    finally:
        db.close()

    client = Client(OWNER_EMAIL, "MOES")
    _, body, _ = client.get("/api/notifications/unread-count")
    assert json.loads(body)["unread_count"] == 1
    status, body, _ = client.request("POST", "/api/notifications/mark-read", json_body={"all": True})
    assert status == 200 and json.loads(body) == {"marked": 1, "unread_count": 0}

    anonymous = Client(None, "MOYZA")
    for path in ("/api/notifications/unread-count", "/api/notifications/recent"):
        assert anonymous.get(path)[0] == 401
    assert anonymous.request("POST", "/api/notifications/mark-read", json_body={"all": True})[0] == 401


def test_pagina_de_notificaciones(setup):
    for status_filter in ("all", "unread", "read", "otro"):
        status, body, _ = Client(OWNER_EMAIL, "MOYZA").get(f"/notifications?status={status_filter}")
        assert status == 200
        assert "Notificaciones" in body
    status, _, headers = Client(OWNER_EMAIL, "MOYZA").get("/notifications/999999999/open")
    assert status == 302 and headers.get("location") == "/notifications"
