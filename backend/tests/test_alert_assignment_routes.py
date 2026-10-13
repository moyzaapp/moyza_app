"""
Rutas de asignación de alertas (PLAN_ASIGNACION_ALERTAS.md), contra la app
levantada (patrón de test_visit_agents.py; se omite si la app no responde).

Datos propios en MOYZA: una propiedad captada por CAPTADOR, otra sin captador,
dos agentes más de MOYZA (OTRO; NUEVO, con la cola vacía para ver la alerta
reasignada sin bloqueo) y uno solo de MOES (MOES), cada uno con su usuario. Todo se borra al terminar (alertas, seguimientos, historial,
notificaciones, compradores, propiedades, usuarios y agentes).

    docker exec moyza_backend python -m pytest tests/test_alert_assignment_routes.py -q
"""
import base64
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

import pytest

BASE_URL = os.getenv("MOYZA_TEST_BASE_URL", "http://localhost:8000")
ADMIN_EMAIL = os.getenv("MOYZA_TEST_ADMIN_EMAIL", "admin@moyza.com")
TAG = "PYTEST-ASIGNACION"
EMAIL = "pytest.asignacion.{}@example.com"


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

    def __init__(self, email: str, company: str):
        from app.core.security import create_access_token
        token = create_access_token({"sub": email})
        self.cookie = f"access_token={token}; active_company={company}"
        self.opener = urllib.request.build_opener(self._NoRedirect)

    def _request(self, method, path, data=None):
        body = urllib.parse.urlencode(data).encode() if data is not None else None
        req = urllib.request.Request(BASE_URL + path, data=body, method=method)
        req.add_header("Cookie", self.cookie)
        try:
            resp = self.opener.open(req, timeout=20)
            return resp.status, resp.read().decode("utf-8", "replace"), dict(resp.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace"), dict(e.headers)

    def get(self, path):
        return self._request("GET", path)

    def post(self, path, data):
        return self._request("POST", path, data)


def _flash(headers) -> dict:
    """Primer mensaje del flash (cookie `moyza_flash`, lista JSON en base64 urlsafe)."""
    match = re.search(r'moyza_flash="?([^";]+)', headers.get("set-cookie", ""))
    if not match:
        return {}
    messages = json.loads(base64.urlsafe_b64decode(match.group(1)).decode("utf-8"))
    return messages[0] if messages else {}


@pytest.fixture(scope="module")
def data():
    if not _server_up():
        pytest.skip(f"La app no responde en {BASE_URL}; tests de integración omitidos")

    from app.db.session import SessionLocal
    from app.models.agent import Agent
    from app.models.company import Company
    from app.models.property import Property
    from app.models.role import Role
    from app.models.user import User

    db = SessionLocal()
    _cleanup(db)
    moyza = db.query(Company).filter_by(code="MOYZA").one()
    moes = db.query(Company).filter_by(code="MOES").one()
    role = db.query(Role).filter(Role.name.ilike("agent")).first()

    agents = {}
    for key, companies in (("captador", [moyza]), ("otro", [moyza]), ("nuevo", [moyza]), ("moes", [moes])):
        ag = Agent(name=f"{TAG} {key.upper()}", email=EMAIL.format(key))
        ag.companies.extend(companies)
        user = User(email=EMAIL.format(key), full_name=f"{TAG} {key}", hashed_password="pytest-sin-login",
                    role_id=role.id if role else None, is_active=True)
        user.companies.extend(companies)
        db.add_all([ag, user])
        agents[key] = ag
    db.flush()

    prop = Property(title=f"{TAG} PISO", address="Calle Test 3", city="Jaen",
                    company_id=moyza.id, agent_id=agents["captador"].id)
    orphan = Property(title=f"{TAG} SIN CAPTADOR", address="Calle Test 4", city="Jaen",
                      company_id=moyza.id, agent_id=None)
    db.add_all([prop, orphan])
    db.commit()

    out = {key: ag.id for key, ag in agents.items()}
    out.update(property_id=prop.id, orphan_id=orphan.id, moyza_id=moyza.id, moes_id=moes.id)
    yield out

    _cleanup(db)
    db.close()


def _cleanup(db):
    from app.models.agent import Agent
    from app.models.alert_follow_up import AlertFollowUp
    from app.models.buyer import Buyer
    from app.models.notification import Notification
    from app.models.property import Property
    from app.models.property_alert import PropertyAlert
    from app.models.user import User

    from sqlalchemy import select

    db.rollback()
    users = select(User.id).where(User.email.like(EMAIL.format("%")))
    db.query(Notification).filter(Notification.user_id.in_(users)).delete(synchronize_session=False)
    props = select(Property.id).where(Property.title.like(f"{TAG}%"))
    alerts = select(PropertyAlert.id).where(PropertyAlert.property_id.in_(props))
    db.query(AlertFollowUp).filter(AlertFollowUp.alert_id.in_(alerts)).delete(synchronize_session=False)
    # alert_assignment_logs se borra en cascada (FK ON DELETE CASCADE)
    db.query(PropertyAlert).filter(PropertyAlert.property_id.in_(props)).delete(synchronize_session=False)
    db.query(Buyer).filter(Buyer.name.like(f"{TAG}%")).delete(synchronize_session=False)
    db.query(Property).filter(Property.title.like(f"{TAG}%")).delete(synchronize_session=False)
    db.query(User).filter(User.email.like(EMAIL.format("%"))).delete(synchronize_session=False)
    db.query(Agent).filter(Agent.email.like(EMAIL.format("%"))).delete(synchronize_session=False)
    db.commit()


def _session():
    from app.db.session import SessionLocal
    return SessionLocal()


def _alerts_of_buyer(db, name):
    from app.models.buyer import Buyer
    db.expire_all()
    buyer = db.query(Buyer).filter(Buyer.name == name).first()
    return list(buyer.alerts) if buyer else []


def _assigned_notifications(db, agent_key):
    from app.models.notification import Notification
    from app.models.user import User
    user = db.query(User).filter(User.email == EMAIL.format(agent_key)).one()
    return db.query(Notification).filter(
        Notification.user_id == user.id, Notification.kind == "alert_assigned"
    ).all()


def _create(client, property_id, name, **extra):
    form = {
        "property_id": property_id,
        "buyer_name": name,
        "buyer_phone": "",
        "confirm_new_buyer": "1",
        "business_type": "Venta",
    }
    form.update(extra)
    return client.post("/alerts/create", form)


# ---------------------------------------------------------------------------
# Fase 2: elegir agente al crear
# ---------------------------------------------------------------------------

def test_autocompletado_devuelve_agente_y_sin_captador_solo_admin(data):
    admin = _Client(ADMIN_EMAIL, "MOYZA")
    status, body, _ = admin.get("/alerts/search-properties?q=" + urllib.parse.quote(TAG))
    results = {r["id"]: r for r in json.loads(body)["results"]}
    assert results[data["property_id"]]["agent_id"] == data["captador"]
    assert results[data["orphan_id"]]["agent_id"] is None

    agent = _Client(EMAIL.format("otro"), "MOYZA")
    status, body, _ = agent.get("/alerts/search-properties?q=" + urllib.parse.quote(TAG))
    ids = {r["id"] for r in json.loads(body)["results"]}
    assert data["property_id"] in ids and data["orphan_id"] not in ids


def test_alta_por_defecto_va_al_captador_sin_aviso(data):
    admin = _Client(ADMIN_EMAIL, "MOYZA")
    name = f"{TAG} DEFECTO"
    status, _, headers = _create(admin, data["property_id"], name)
    assert status == 302
    flash = _flash(headers)
    assert flash.get("category") == "success" and f"asignada a {TAG} CAPTADOR" in flash.get("message", "")

    db = _session()
    [alert] = _alerts_of_buyer(db, name)
    assert alert.agent_id == data["captador"]
    assert alert.assigned_at == alert.created_at and alert.assignment_reason is None
    assert [(log.from_agent_id, log.to_agent_id) for log in alert.assignment_logs] == [(None, data["captador"])]
    assert _assigned_notifications(db, "captador") == []
    db.close()


def test_alta_con_otro_agente_con_y_sin_motivo(data):
    admin = _Client(ADMIN_EMAIL, "MOYZA")
    db = _session()

    name = f"{TAG} OTRO CON MOTIVO"
    status, _, headers = _create(admin, data["property_id"], name,
                                 agent_id=data["otro"], assignment_reason="Carga de trabajo")
    assert status == 302 and _flash(headers).get("category") == "success"
    [alert] = _alerts_of_buyer(db, name)
    assert alert.agent_id == data["otro"] and alert.assignment_reason == "Carga de trabajo"
    notes = [n for n in _assigned_notifications(db, "otro") if n.entity_id == alert.id]
    assert len(notes) == 1 and "Carga de trabajo" in notes[0].body
    assert _assigned_notifications(db, "captador") == []

    # El motivo es opcional (decisión §4-8)
    name = f"{TAG} OTRO SIN MOTIVO"
    status, _, headers = _create(admin, data["property_id"], name, agent_id=data["otro"])
    assert status == 302 and _flash(headers).get("category") == "success"
    [alert] = _alerts_of_buyer(db, name)
    assert alert.agent_id == data["otro"] and alert.assignment_reason is None
    db.close()


def test_propiedad_sin_captador_exige_elegir_agente(data):
    admin = _Client(ADMIN_EMAIL, "MOYZA")
    db = _session()

    name = f"{TAG} HUERFANA"
    status, _, headers = _create(admin, data["orphan_id"], name)
    assert status == 302 and _flash(headers).get("category") == "error"
    assert "elige el agente" in _flash(headers).get("message", "")
    assert _alerts_of_buyer(db, name) == []

    status, _, headers = _create(admin, data["orphan_id"], name, agent_id=data["otro"])
    assert status == 302 and _flash(headers).get("category") == "success"
    [alert] = _alerts_of_buyer(db, name)
    assert alert.agent_id == data["otro"]
    db.close()

    # Aparece en el listado del admin aunque la propiedad no tenga captador
    status, body, _ = admin.get("/alerts")
    assert status == 200 and name in body


def test_agente_no_puede_elegir_agente(data):
    agent = _Client(EMAIL.format("otro"), "MOYZA")
    db = _session()

    name = f"{TAG} AGENTE ELIGE"
    status, _, headers = _create(agent, data["property_id"], name, agent_id=data["otro"])
    assert status == 302 and _flash(headers).get("category") == "error"
    assert "Solo un administrador" in _flash(headers).get("message", "")
    assert _alerts_of_buyer(db, name) == []

    # Sin agent_id, la alerta va al captador (y se le dice a quién)
    name = f"{TAG} AGENTE DEFECTO"
    status, _, headers = _create(agent, data["property_id"], name)
    assert status == 302
    assert f"asignada a {TAG} CAPTADOR, agente de la propiedad" in _flash(headers).get("message", "")
    [alert] = _alerts_of_buyer(db, name)
    assert alert.agent_id == data["captador"]
    db.close()


def test_formulario_select_solo_para_admin(data):
    status, body, _ = _Client(ADMIN_EMAIL, "MOYZA").get("/alerts")
    assert status == 200 and 'id="caAgentSelect"' in body and '<optgroup label="MOES PREMIUM">' in body

    status, body, _ = _Client(EMAIL.format("otro"), "MOYZA").get("/alerts")
    assert status == 200
    assert 'id="caAgentSelect"' not in body and "Se asignará a" in body


# ---------------------------------------------------------------------------
# Fase 3: reasignar alertas existentes
# ---------------------------------------------------------------------------

def _new_alert_for(data, name, agent_key=None):
    admin = _Client(ADMIN_EMAIL, "MOYZA")
    extra = {"agent_id": data[agent_key]} if agent_key else {}
    status, _, headers = _create(admin, data["property_id"], name, **extra)
    assert status == 302 and _flash(headers).get("category") == "success", _flash(headers)
    db = _session()
    [alert] = _alerts_of_buyer(db, name)
    db.close()
    return alert.id


def test_reasignar_desde_detalle(data):
    from app.models.property_alert import PropertyAlert

    alert_id = _new_alert_for(data, f"{TAG} REASIGNAR DETALLE")
    captador = _Client(EMAIL.format("captador"), "MOYZA")
    nuevo = _Client(EMAIL.format("nuevo"), "MOYZA")

    # El captador la abre (queda en proceso y leída)
    status, body, _ = captador.get(f"/alerts/{alert_id}")
    assert status == 200 and 'id="reassignModal"' not in body and "Reasignar" not in body

    admin = _Client(ADMIN_EMAIL, "MOYZA")
    status, body, _ = admin.get(f"/alerts/{alert_id}")
    assert status == 200 and 'id="reassignModal"' in body and 'id="raAgentSelect"' in body

    status, _, headers = admin.post(f"/alerts/{alert_id}/reassign", {
        "agent_id": data["nuevo"], "assignment_reason": "Sin respuesta", "next": f"/alerts/{alert_id}",
    })
    assert status == 302 and headers.get("location") == f"/alerts/{alert_id}"
    flash = _flash(headers)
    assert flash.get("category") == "success"
    assert f"reasignada de {TAG} CAPTADOR a {TAG} NUEVO" in flash.get("message", "")

    db = _session()
    alert = db.get(PropertyAlert, alert_id)
    assert alert.agent_id == data["nuevo"] and alert.previous_agent_id == data["captador"]
    assert alert.status == "PENDING" and alert.read_at is None
    assert alert.assignment_reason == "Sin respuesta"
    assert [f.action_type for f in alert.follow_ups] == ["REASIGNADA"]
    assert len([n for n in _assigned_notifications(db, "nuevo") if n.entity_id == alert_id]) == 1
    db.close()

    # El anterior deja de verla y el nuevo la ve
    assert captador.get(f"/alerts/{alert_id}")[0] == 302
    assert f"{TAG} REASIGNAR DETALLE" not in captador.get("/alerts")[1]
    status, body, _ = nuevo.get("/alerts")
    assert status == 200 and f"{TAG} REASIGNAR DETALLE" in body
    status, body, _ = nuevo.get(f"/alerts/{alert_id}")
    assert status == 200 and "Antes: " + f"{TAG} CAPTADOR" in body and "Motivo: Sin respuesta" in body
    assert "Historial de asignaciones (2)" in body

    # La campana del Inicio del nuevo agente tiene el aviso
    status, body, _ = nuevo.get("/dashboard")
    assert status == 200 and f"Te han asignado un comprador: {TAG} REASIGNAR DETALLE" in body


def test_reasignar_desde_listado_vuelve_al_listado(data):
    alert_id = _new_alert_for(data, f"{TAG} REASIGNAR LISTADO")
    admin = _Client(ADMIN_EMAIL, "MOYZA")

    status, body, _ = admin.get("/alerts")
    assert f'data-alert-id="{alert_id}"' in body and 'id="reassignForm"' in body

    status, _, headers = admin.post(f"/alerts/{alert_id}/reassign", {
        "agent_id": data["otro"], "next": "/alerts?q=PYTEST",
    })
    assert status == 302 and headers.get("location") == "/alerts?q=PYTEST"
    assert _flash(headers).get("category") == "success"

    # `next` externo: se ignora y vuelve al detalle
    status, _, headers = admin.post(f"/alerts/{alert_id}/reassign", {
        "agent_id": data["captador"], "next": "https://evil.example.com/",
    })
    assert headers.get("location") == f"/alerts/{alert_id}"


def test_reasignar_rechazos(data):
    from app.models.property_alert import PropertyAlert

    alert_id = _new_alert_for(data, f"{TAG} REASIGNAR RECHAZOS")
    admin = _Client(ADMIN_EMAIL, "MOYZA")

    # Un agente no puede (ni siendo el asignado)
    agent = _Client(EMAIL.format("captador"), "MOYZA")
    status, _, headers = agent.post(f"/alerts/{alert_id}/reassign", {"agent_id": data["otro"]})
    assert status == 302 and "Solo un administrador" in _flash(headers).get("message", "")

    # Al mismo agente, a uno inexistente o sin agente
    for agent_id, text in ((data["captador"], "ya está asignada"), (999999, "no existe"), ("", "no existe")):
        status, _, headers = admin.post(f"/alerts/{alert_id}/reassign", {"agent_id": agent_id})
        assert _flash(headers).get("category") == "error" and text in _flash(headers).get("message", "")

    db = _session()
    assert db.get(PropertyAlert, alert_id).agent_id == data["captador"]

    # Cerrada: no se puede reasignar ni se ofrece el botón
    alert = db.get(PropertyAlert, alert_id)
    alert.status = "COMPLETED"
    db.commit()
    db.close()
    status, _, headers = admin.post(f"/alerts/{alert_id}/reassign", {"agent_id": data["otro"]})
    assert "abiertas" in _flash(headers).get("message", "")
    status, body, _ = admin.get(f"/alerts/{alert_id}")
    assert 'id="reassignModal"' not in body


def test_nota_de_reasignacion_no_permite_cerrar(data):
    alert_id = _new_alert_for(data, f"{TAG} CERRAR TRAS REASIGNAR")
    admin = _Client(ADMIN_EMAIL, "MOYZA")
    admin.post(f"/alerts/{alert_id}/reassign", {"agent_id": data["otro"]})

    status, _, headers = admin.post(f"/alerts/{alert_id}/complete", {})
    assert "al menos un seguimiento" in _flash(headers).get("message", "")


# ---------------------------------------------------------------------------
# Fase 4: agente de la otra empresa (decisión §4-1 B)
# ---------------------------------------------------------------------------

def test_agente_solo_moes_recibe_alerta_moyza(data):
    from app.models.agent import Agent
    from app.models.user import User

    admin = _Client(ADMIN_EMAIL, "MOYZA")
    name = f"{TAG} PARA MOES"

    # El formulario avisa antes de enviar: la opción lleva sus empresas
    status, body, _ = admin.get("/alerts")
    assert f'data-companies="{data["moes_id"]}">{TAG} MOES</option>' in body

    status, _, headers = _create(admin, data["property_id"], name, agent_id=data["moes"])
    flash = _flash(headers)
    assert flash.get("category") == "success" and f"{TAG} MOES ahora tiene acceso a MOYZA" in flash["message"]

    db = _session()
    agent = db.get(Agent, data["moes"])
    assert {c.code for c in agent.companies} == {"MOYZA", "MOES"}
    user = db.query(User).filter(User.email == EMAIL.format("moes")).one()
    assert [c.code for c in user.companies] == ["MOES"]   # basta la ficha de agente
    [alert] = _alerts_of_buyer(db, name)
    db.close()

    # Con MOES activa: banner con el cambio de empresa, y la alerta no sale en la lista
    moes_view = _Client(EMAIL.format("moes"), "MOES")
    status, body, _ = moes_view.get("/alerts")
    assert status == 200 and "Tienes 1 comprador asignado en MOYZA" in body
    assert 'action="/switch-company"' in body and 'name="code" value="MOYZA"' in body
    assert name not in body
    # El aviso in-app vive en MOYZA: con MOES activa no está en la campana
    assert f"Te han asignado un comprador: {name}" not in moes_view.get("/dashboard")[1]

    # Puede cambiar a MOYZA
    status, _, headers = moes_view.post("/switch-company", {"code": "MOYZA", "next": "/alerts"})
    assert status == 303 and "active_company=MOYZA" in headers.get("set-cookie", "")

    # Con MOYZA activa: ve y trabaja su alerta, la campana tiene el aviso y no el banner
    moyza_view = _Client(EMAIL.format("moes"), "MOYZA")
    status, body, _ = moyza_view.get("/alerts")
    assert status == 200 and name in body and "comprador asignado en" not in body
    # Solo sus alertas: no ve las de otros agentes de MOYZA
    assert f"{TAG} DEFECTO" not in body and f"{TAG} OTRO CON MOTIVO" not in body
    assert moyza_view.get(f"/alerts/{alert.id}")[0] == 200
    status, _, headers = moyza_view.post(f"/alerts/{alert.id}/follow-up", {
        "action_type": "PRIMERA_LLAMADA", "notes": "Llamada desde MOES",
    })
    assert _flash(headers).get("category") == "success"
    assert f"Te han asignado un comprador: {name}" in moyza_view.get("/dashboard")[1]

    # Una alerta de MOYZA de otro agente sigue fuera de su alcance
    db = _session()
    [other] = _alerts_of_buyer(db, f"{TAG} DEFECTO")
    db.close()
    assert moyza_view.get(f"/alerts/{other.id}")[0] == 302
