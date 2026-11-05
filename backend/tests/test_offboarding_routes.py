"""
Rutas de la baja lógica (PLAN_BAJA_USUARIOS.md §6, §8) contra la app
levantada (patrón de test_alert_assignment_routes.py; se omite si la app no
responde).

Datos propios `PYTEST-BAJA` en MOYZA (usuarios con ficha de agente, fichas sin
usuario, propiedades y alertas). Todo se borra al empezar y al terminar
(alertas, seguimientos, historial de asignaciones, notificaciones,
propiedades, usuarios, agentes y sus empresas).

    docker exec moyza_backend python -m pytest tests/test_offboarding_routes.py -q
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
TAG = "PYTEST-BAJA RUTAS"
EMAIL = "pytest.baja.rutas.{}@example.com"
PASSWORD = "PytestBaja-2026!"


def _server_up() -> bool:
    try:
        urllib.request.urlopen(BASE_URL + "/", timeout=3)
        return True
    except Exception:
        return False


class _Client:
    """Peticiones con cookies de sesión y empresa, sin seguir redirecciones.

    Sin `email`: navegador sin sesión (para el login).
    """

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    def __init__(self, email=None, company="MOYZA"):
        if email:
            from app.core.security import create_access_token
            token = create_access_token({"sub": email})
            self.cookie = f"access_token={token}; active_company={company}"
        else:
            self.cookie = f"active_company={company}"
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


def _select(body, select_id) -> str:
    """HTML del `<select id=...>` hasta su cierre."""
    match = re.search(rf'<select[^>]*id="{select_id}".*?</select>', body, re.S)
    assert match, f"No está el select {select_id}"
    return match.group(0)


def _session():
    from app.db.session import SessionLocal
    return SessionLocal()


# ---------------------------------------------------------------------------
# Datos
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def data():
    if not _server_up():
        pytest.skip(f"La app no responde en {BASE_URL}; tests de integración omitidos")

    from datetime import datetime

    from app.core.password import hash_password
    from app.models.agent import Agent
    from app.models.client import Client
    from app.models.company import Company
    from app.models.property import Property
    from app.models.property_alert import PropertyAlert
    from app.models.role import Role
    from app.models.user import User
    from app.services.company_scope import scope_clients

    db = _session()
    _cleanup(db)
    moyza = db.query(Company).filter_by(code="MOYZA").one()
    role = db.query(Role).filter(Role.name.ilike("agent")).first()
    admin = db.query(User).filter_by(email=ADMIN_EMAIL).one()
    hashed = hash_password(PASSWORD)

    def person(key, *, with_user=True, active=True):
        when = None if active else datetime.utcnow()
        ag = Agent(name=f"{TAG} {key.upper()}", email=EMAIL.format(key), is_active=active, deactivated_at=when)
        ag.companies.append(moyza)
        db.add(ag)
        user = None
        if with_user:
            user = User(email=EMAIL.format(key), full_name=f"{TAG} {key.upper()}", hashed_password=hashed,
                        role_id=role.id if role else None, is_active=active, deactivated_at=when)
            user.companies.append(moyza)
            db.add(user)
        return user, ag

    users, agents = {}, {}
    for key, kwargs in (
        ("bloqueado", {}),             # propiedad Activa: la baja se bloquea
        ("saliente", {}),              # alerta abierta: se reasigna en la baja
        ("destino", {}),               # recibe las alertas del saliente
        ("baja", {"active": False}),   # ya dado de baja, con historial
        ("limpio", {}),                # sin historial: se puede eliminar
        ("fichahist", {"with_user": False}),   # ficha sin usuario con historial
        ("fichalimpia", {"with_user": False}), # ficha sin usuario sin historial
    ):
        users[key], agents[key] = person(key, **kwargs)
    db.flush()

    live = Property(title=f"{TAG} PISO ACTIVO", address="Calle Test 1", city="Jaen",
                    company_id=moyza.id, agent_id=agents["bloqueado"].id, status="Activa")
    db.add(live)
    db.flush()

    def alert(agent_key, status, name):
        db.add(PropertyAlert(company_id=moyza.id, origin="search", agent_id=agents[agent_key].id,
                             lead_name=f"{TAG} {name}", status=status, created_by=admin.id,
                             business_type="Venta"))

    alert("saliente", "PENDING", "ABIERTA SALIENTE")
    alert("baja", "COMPLETED", "CERRADA BAJA")
    alert("fichahist", "COMPLETED", "CERRADA FICHA")
    db.commit()

    client = scope_clients(db.query(Client), moyza.id).order_by(Client.id).first()

    out = {f"{k}_agent": a.id for k, a in agents.items()}
    out.update({f"{k}_user": u.id for k, u in users.items() if u is not None})
    out.update(moyza_id=moyza.id, live_property_id=live.id, client_id=client.id if client else None,
               role_id=role.id if role else None)
    yield out

    _cleanup(db)
    db.close()


def _cleanup(db):
    from sqlalchemy import delete
    from sqlalchemy import or_
    from sqlalchemy import select

    from app.models.agent import Agent
    from app.models.alert_assignment_log import AlertAssignmentLog
    from app.models.alert_follow_up import AlertFollowUp
    from app.models.company import agent_companies
    from app.models.company import user_companies
    from app.models.notification import Notification
    from app.models.property import Property
    from app.models.property_alert import PropertyAlert
    from app.models.property_price_history import PropertyPriceHistory
    from app.models.property_status_history import PropertyStatusHistory
    from app.models.user import User

    db.rollback()
    users = select(User.id).where(User.email.like(EMAIL.format("%")))
    agents = select(Agent.id).where(Agent.email.like(EMAIL.format("%")))
    props = select(Property.id).where(Property.title.like(f"{TAG}%"))
    alerts = select(PropertyAlert.id).where(or_(
        PropertyAlert.property_id.in_(props),
        PropertyAlert.agent_id.in_(agents),
        PropertyAlert.lead_name.like(f"{TAG}%"),
    ))

    db.query(Notification).filter(or_(
        Notification.user_id.in_(users), Notification.title.like(f"%{TAG}%"),
    )).delete(synchronize_session=False)
    db.query(AlertFollowUp).filter(or_(
        AlertFollowUp.alert_id.in_(alerts), AlertFollowUp.created_by.in_(users),
    )).delete(synchronize_session=False)
    db.query(AlertAssignmentLog).filter(or_(
        AlertAssignmentLog.alert_id.in_(alerts),
        AlertAssignmentLog.from_agent_id.in_(agents),
        AlertAssignmentLog.to_agent_id.in_(agents),
    )).delete(synchronize_session=False)
    db.query(PropertyAlert).filter(PropertyAlert.id.in_(alerts)).delete(synchronize_session=False)
    db.query(PropertyPriceHistory).filter(
        PropertyPriceHistory.property_id.in_(props)).delete(synchronize_session=False)
    db.query(PropertyStatusHistory).filter(
        PropertyStatusHistory.property_id.in_(props)).delete(synchronize_session=False)
    db.query(Property).filter(Property.title.like(f"{TAG}%")).delete(synchronize_session=False)
    db.execute(delete(agent_companies).where(agent_companies.c.agent_id.in_(agents)))
    db.execute(delete(user_companies).where(user_companies.c.user_id.in_(users)))
    db.query(User).filter(User.email.like(EMAIL.format("%"))).delete(synchronize_session=False)
    db.query(Agent).filter(Agent.email.like(EMAIL.format("%"))).delete(synchronize_session=False)
    db.commit()


def _admin():
    return _Client(ADMIN_EMAIL, "MOYZA")


# ---------------------------------------------------------------------------
# Acceso del inactivo
# ---------------------------------------------------------------------------

def test_login_de_inactivo_muestra_el_mensaje(data):
    anon = _Client()
    status, body, headers = anon.post("/login", {"username": EMAIL.format("baja"), "password": PASSWORD})
    assert status == 200
    assert "Tu usuario está dado de baja. Contacta con un administrador." in body
    assert "access_token=" not in headers.get("set-cookie", "")

    # Contraseña mala: el mensaje genérico (no revela que existe ni que está de baja)
    status, body, _ = anon.post("/login", {"username": EMAIL.format("baja"), "password": "otra"})
    assert status == 200 and "Credenciales inválidas" in body and "dado de baja" not in body

    # Un activo con las mismas credenciales entra
    status, _, headers = anon.post("/login", {"username": EMAIL.format("limpio"), "password": PASSWORD})
    assert status == 302 and headers.get("location") == "/dashboard"


def test_sesion_viva_de_inactivo_redirige_al_login(data):
    inactive = _Client(EMAIL.format("baja"))
    for path in ("/dashboard", "/alerts", "/properties"):
        status, _, headers = inactive.get(path)
        assert status == 302 and headers.get("location") == "/", path


# ---------------------------------------------------------------------------
# JSON del modal
# ---------------------------------------------------------------------------

def test_offboarding_json(data):
    admin = _admin()
    status, body, _ = admin.get(f"/auth/users/{data['saliente_user']}/offboarding")
    assert status == 200
    summary = json.loads(body)
    assert summary["name"] == f"{TAG} SALIENTE" and summary["blocked"] is False
    assert summary["has_history"] is True
    [moyza] = [c for c in summary["companies"] if c["id"] == data["moyza_id"]]
    assert moyza["open_alerts"] == 1 and moyza["live_properties"] == 0
    assert moyza["properties_url"].startswith("/properties?search=")
    target_ids = {t["id"] for t in moyza["targets"]}
    assert data["destino_agent"] in target_ids
    assert data["saliente_agent"] not in target_ids and data["baja_agent"] not in target_ids

    status, body, _ = admin.get(f"/auth/users/{data['bloqueado_user']}/offboarding")
    assert status == 200 and json.loads(body)["blocked"] is True

    assert admin.get("/auth/users/999999999/offboarding")[0] == 404

    # Un agente no puede pedirlo
    status, body, _ = _Client(EMAIL.format("destino")).get(f"/auth/users/{data['saliente_user']}/offboarding")
    assert status == 403 and "administrador" in json.loads(body)["detail"]

    # Ficha sin usuario: por /agents; con usuario, se remite a Usuarios
    status, body, _ = admin.get(f"/agents/{data['fichalimpia_agent']}/offboarding")
    assert status == 200 and json.loads(body)["name"] == f"{TAG} FICHALIMPIA"
    status, body, _ = admin.get(f"/agents/{data['saliente_agent']}/offboarding")
    assert status == 400 and "desde Usuarios" in json.loads(body)["detail"]
    assert admin.get("/agents/999999999/offboarding")[0] == 404
    assert _Client(EMAIL.format("destino")).get(f"/agents/{data['fichalimpia_agent']}/offboarding")[0] == 403


# ---------------------------------------------------------------------------
# Dar de baja y reactivar
# ---------------------------------------------------------------------------

def test_deactivate_bloqueado_por_propiedad_activa(data):
    from app.models.user import User

    status, _, headers = _admin().post(f"/auth/users/{data['bloqueado_user']}/deactivate", {})
    assert status == 303 and headers.get("location") == "/auth"
    flash = _flash(headers)
    assert flash.get("category") == "error"
    assert "1 propiedad activa en MOYZA" in flash["message"] and "Reasígnalas desde Propiedades" in flash["message"]

    db = _session()
    assert db.get(User, data["bloqueado_user"]).is_active is True
    db.close()


def test_deactivate_sin_destino_y_correcto(data):
    from app.models.agent import Agent
    from app.models.property_alert import PropertyAlert
    from app.models.user import User

    admin = _admin()
    path = f"/auth/users/{data['saliente_user']}/deactivate"

    status, _, headers = admin.post(path, {"reason": ""})
    flash = _flash(headers)
    assert status == 303 and flash.get("category") == "error"
    assert "Elige a quién reasignar sus compradores abiertos de MOYZA" in flash["message"]

    status, _, headers = admin.post(path, {f"reassign_to_{data['moyza_id']}": data["baja_agent"]})
    assert _flash(headers).get("category") == "error"
    assert "no es un agente activo" in _flash(headers)["message"]

    db = _session()
    assert db.get(User, data["saliente_user"]).is_active is True
    db.close()

    status, _, headers = admin.post(path, {
        f"reassign_to_{data['moyza_id']}": data["destino_agent"], "reason": "Deja la empresa",
    })
    flash = _flash(headers)
    assert status == 303 and flash.get("category") == "success", flash
    assert flash["message"] == (
        f"{TAG} SALIENTE dado de baja. 1 comprador reasignado a {TAG} DESTINO (MOYZA)."
    )

    db = _session()
    user = db.get(User, data["saliente_user"])
    agent = db.get(Agent, data["saliente_agent"])
    assert user.is_active is False and user.deactivated_at is not None
    assert agent.is_active is False and agent.deactivated_at is not None
    alert = db.query(PropertyAlert).filter_by(lead_name=f"{TAG} ABIERTA SALIENTE").one()
    assert alert.agent_id == data["destino_agent"] and alert.assignment_reason == "Deja la empresa"
    db.close()

    # Ya dado de baja: no se repite
    status, _, headers = admin.post(path, {f"reassign_to_{data['moyza_id']}": data["destino_agent"]})
    assert "ya está dado de baja" in _flash(headers).get("message", "")


def test_deactivate_y_reactivate_solo_admin(data):
    from app.models.user import User

    agent_client = _Client(EMAIL.format("destino"))
    status, _, headers = agent_client.post(f"/auth/users/{data['limpio_user']}/deactivate", {})
    assert status in (302, 303) and headers.get("location") != "/auth"
    status, _, headers = agent_client.post(f"/auth/users/{data['baja_user']}/reactivate", {})
    assert status in (302, 303) and headers.get("location") != "/auth"

    db = _session()
    assert db.get(User, data["limpio_user"]).is_active is True
    assert db.get(User, data["baja_user"]).is_active is False
    db.close()


def test_no_puede_darse_de_baja_a_si_mismo(data):
    from app.models.user import User
    db = _session()
    admin_id = db.query(User).filter_by(email=ADMIN_EMAIL).one().id
    db.close()

    status, _, headers = _admin().post(f"/auth/users/{admin_id}/deactivate", {})
    assert _flash(headers).get("category") == "error" and "a ti mismo" in _flash(headers)["message"]


def test_reactivate(data):
    from app.models.agent import Agent
    from app.models.user import User

    # Se reactiva y se vuelve a dar de baja para no afectar a los demás tests
    admin = _admin()
    status, _, headers = admin.post(f"/auth/users/{data['baja_user']}/reactivate", {})
    flash = _flash(headers)
    assert status == 303 and flash.get("category") == "success"
    assert flash["message"].startswith(f"{TAG} BAJA reactivado.")

    db = _session()
    user = db.get(User, data["baja_user"])
    agent = db.get(Agent, data["baja_agent"])
    assert user.is_active is True and user.deactivated_at is None
    assert agent.is_active is True and agent.deactivated_at is None
    db.close()

    # Ya puede entrar
    status, _, headers = _Client().post("/login", {"username": EMAIL.format("baja"), "password": PASSWORD})
    assert status == 302 and headers.get("location") == "/dashboard"

    status, _, headers = admin.post(f"/auth/users/{data['baja_user']}/deactivate", {})
    assert _flash(headers).get("category") == "success", _flash(headers)
    db = _session()
    assert db.get(User, data["baja_user"]).is_active is False
    db.close()


def test_fichas_sin_usuario_baja_y_reactivacion(data):
    from app.models.agent import Agent

    admin = _admin()
    status, _, headers = admin.post(f"/agents/{data['fichalimpia_agent']}/deactivate", {})
    assert status == 303 and headers.get("location") == "/agents"
    assert _flash(headers) == {"category": "success", "message": f"{TAG} FICHALIMPIA dado de baja."}
    db = _session()
    assert db.get(Agent, data["fichalimpia_agent"]).is_active is False
    db.close()

    status, _, headers = admin.post(f"/agents/{data['fichalimpia_agent']}/reactivate", {})
    assert _flash(headers).get("category") == "success"
    db = _session()
    assert db.get(Agent, data["fichalimpia_agent"]).is_active is True
    db.close()

    # Ficha con usuario: se remite a Usuarios
    status, _, headers = admin.post(f"/agents/{data['destino_agent']}/deactivate", {})
    assert _flash(headers).get("category") == "error" and "desde Usuarios" in _flash(headers)["message"]


# ---------------------------------------------------------------------------
# Alta y borrado
# ---------------------------------------------------------------------------

def test_create_user_con_email_de_inactivo(data):
    from app.models.user import User

    status, _, headers = _admin().post("/auth/users/create", {
        "email": EMAIL.format("baja"), "full_name": f"{TAG} DUPLICADO", "password": PASSWORD,
        "role_id": data["role_id"], "phone": "", "company_ids": data["moyza_id"],
    })
    assert status == 303
    assert _flash(headers) == {
        "category": "error",
        "message": "Ese usuario está dado de baja. Reactívalo desde la lista de usuarios.",
    }
    db = _session()
    assert db.query(User).filter(User.email == EMAIL.format("baja")).count() == 1
    db.close()


def test_delete_user_con_historial_da_error_sin_500(data):
    from app.models.user import User

    status, _, headers = _admin().post(f"/auth/users/delete/{data['baja_user']}", {})
    assert status == 303
    assert _flash(headers) == {
        "category": "error", "message": "Tiene historial: dale de baja en lugar de eliminarlo.",
    }
    db = _session()
    assert db.get(User, data["baja_user"]) is not None
    db.close()


def test_agents_delete_una_empresa_con_historial_pide_baja(data):
    from app.models.agent import Agent

    admin = _admin()
    status, _, headers = admin.post(f"/agents/delete/{data['fichahist_agent']}", {})
    assert status == 302 and headers.get("location") == "/agents?error=use_offboarding"
    # Con usuario (aunque sin historial) tampoco se borra desde Agentes
    status, _, headers = admin.post(f"/agents/delete/{data['limpio_agent']}", {})
    assert headers.get("location") == "/agents?error=use_offboarding"

    db = _session()
    assert db.get(Agent, data["fichahist_agent"]) is not None
    assert db.get(Agent, data["limpio_agent"]) is not None
    db.close()

    status, body, _ = admin.get("/agents?error=use_offboarding")
    assert status == 200 and "Dale de baja en lugar de eliminarlo" in body


# ---------------------------------------------------------------------------
# Listados y selectores
# ---------------------------------------------------------------------------

def test_auth_muestra_reactivar_para_el_inactivo(data):
    status, body, _ = _admin().get("/auth")
    assert status == 200
    assert f'action="/auth/users/{data["baja_user"]}/reactivate"' in body
    assert f'/auth/users/{data["baja_user"]}/deactivate' not in body
    # Activo: botón de baja y no reactivar
    assert f'/auth/users/{data["destino_user"]}/deactivate' in body
    assert f'action="/auth/users/{data["destino_user"]}/reactivate"' not in body
    # Eliminar solo sin historial
    assert f'action="/auth/users/delete/{data["limpio_user"]}"' in body
    assert f'action="/auth/users/delete/{data["baja_user"]}"' not in body
    assert 'id="userDeactivateModal"' in body


def test_agents_botones_nuevos(data):
    status, body, _ = _admin().get("/agents?search=" + urllib.parse.quote(TAG))
    assert status == 200
    # Ficha con usuario: a Usuarios
    assert f'aria-label="Gestionar a {TAG} DESTINO en Usuarios"' in body
    # Fichas sin usuario: dar de baja; sin historial, además eliminar
    assert f'/agents/{data["fichahist_agent"]}/deactivate' in body
    assert f'/agents/{data["fichalimpia_agent"]}/deactivate' in body
    assert f'action="/agents/delete/{data["fichalimpia_agent"]}"' in body
    assert f'action="/agents/delete/{data["fichahist_agent"]}"' not in body
    assert 'id="userDeactivateModal"' in body


def test_inactivo_fuera_de_los_selectores_de_asignacion(data):
    from app.services.alert_assignment_service import assignable_agents

    admin = _admin()
    baja_id = data["baja_agent"]
    baja_name = f"{TAG} BAJA"

    # Captador de Propiedades
    status, body, _ = admin.get("/properties")
    assert status == 200
    captador = _select(body, "agent_id")
    assert f'value="{baja_id}"' not in captador and baja_name not in captador
    assert f'value="{data["destino_agent"]}"' in captador

    # "Agente asignado" del alta de alertas
    status, body, _ = admin.get("/alerts")
    assert status == 200
    alta = _select(body, "caAgentSelect")
    assert f'value="{baja_id}"' not in alta and f'value="{data["destino_agent"]}"' in alta

    db = _session()
    groups = assignable_agents(db, data["moyza_id"])
    db.close()
    ids = {a.id for g in groups for a in g["agents"]}
    assert baja_id not in ids and data["destino_agent"] in ids


def test_inactivo_en_filtro_del_historial_de_cesiones_con_baja(data):
    status, body, _ = _admin().get("/alerts/assignments")
    assert status == 200
    filtro = _select(body, "hAgent")
    assert re.search(rf'value="{data["baja_agent"]}"[^>]*>{re.escape(TAG)} BAJA \(baja\)</option>', filtro)
    assert re.search(rf'value="{data["destino_agent"]}"[^>]*>{re.escape(TAG)} DESTINO</option>', filtro)


def test_crear_propiedad_con_captador_inactivo(data):
    from app.models.property import Property

    if data["client_id"] is None:
        pytest.skip("No hay ningún cliente en MOYZA para el formulario de propiedad")

    title = f"{TAG} NUEVA CON BAJA"
    status, _, headers = _admin().post("/properties/create", {
        "title": title, "address": "Calle Test 9", "city": "Jaen", "price": "100000",
        "description": "Prueba", "client_id": data["client_id"], "agent_id": data["baja_agent"],
    })
    assert status == 302 and headers.get("location") == "/properties"
    assert _flash(headers) == {
        "category": "error",
        "message": f"{TAG} BAJA está dado de baja y no puede ser el captador",
    }
    db = _session()
    assert db.query(Property).filter(Property.title == title).count() == 0
    db.close()
