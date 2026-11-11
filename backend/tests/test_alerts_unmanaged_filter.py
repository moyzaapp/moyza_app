"""
Listado de compradores sin gestionar (PLAN_VENTANA_SIN_GESTION.md, fase B),
contra la app levantada (se omite si no responde).

- `/alerts?attention=sin_gestion` (admin): solo las alertas sin ninguna
  gestión desde la asignación, de la más antigua a la más nueva; fuera las
  gestionadas ("paradas"), las "volver a llamar" y las que aún no han
  vencido; la reasignada sin gestión sale con "Reasignada el dd/mm · antes
  Nombre"; el filtro de estado no aplica; chip para quitarlo y el filtro se
  conserva en los formularios.
- Un agente que manda el parámetro ve su listado de siempre.
- Aislamiento por empresa.
- La reasignación de fila desde el listado filtrado vuelve a ese listado.

Datos propios con el prefijo del TAG (agentes, usuarios y alertas de
búsqueda general); se borran al terminar.

    docker exec moyza_backend python -m pytest tests/test_alerts_unmanaged_filter.py -q
"""
import base64
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from datetime import timedelta

import pytest

BASE_URL = os.getenv("MOYZA_TEST_BASE_URL", "http://localhost:8000")
ADMIN_EMAIL = os.getenv("MOYZA_TEST_ADMIN_EMAIL", "admin@moyza.com")
TAG = "PYTEST-SINGESTION"
EMAIL = "pytest.singestion.{}@example.com"


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
        self.cookie = f"access_token={create_access_token({'sub': email})}; active_company={company}"
        self.opener = urllib.request.build_opener(self._NoRedirect)

    def _request(self, method, path, data=None):
        body = urllib.parse.urlencode(data, doseq=True).encode() if data is not None else None
        req = urllib.request.Request(BASE_URL + path, data=body, method=method)
        req.add_header("Cookie", self.cookie)
        try:
            resp = self.opener.open(req, timeout=30)
            return resp.status, resp.read().decode("utf-8", "replace"), dict(resp.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace"), dict(e.headers)

    def get(self, path):
        return self._request("GET", path)

    def post(self, path, data):
        return self._request("POST", path, data)


def _flashes(headers) -> list:
    """Mensajes del flash (cookie `moyza_flash`, lista JSON en base64 urlsafe)."""
    match = re.search(r'moyza_flash="?([^";]+)', headers.get("set-cookie", ""))
    if not match:
        return []
    return json.loads(base64.urlsafe_b64decode(match.group(1)).decode("utf-8"))


def _alerts_table(body: str) -> str:
    """HTML de la tabla de alertas (sin la de compradores ni los modales)."""
    start = body.find('id="panel-alerts"')
    end = body.find('id="compradores"', start)
    return body[start:end]


def _cleanup(db):
    from sqlalchemy import select
    from app.models.agent import Agent
    from app.models.alert_follow_up import AlertFollowUp
    from app.models.notification import Notification
    from app.models.property_alert import PropertyAlert
    from app.models.user import User

    db.rollback()
    users = select(User.id).where(User.email.like(EMAIL.format("%")))
    db.query(Notification).filter(Notification.user_id.in_(users)).delete(synchronize_session=False)
    alerts = select(PropertyAlert.id).where(PropertyAlert.lead_name.like(f"{TAG}%"))
    db.query(AlertFollowUp).filter(AlertFollowUp.alert_id.in_(alerts)).delete(synchronize_session=False)
    # alert_assignment_logs se borra en cascada (FK ON DELETE CASCADE)
    db.query(PropertyAlert).filter(PropertyAlert.lead_name.like(f"{TAG}%")).delete(synchronize_session=False)
    db.query(User).filter(User.email.like(EMAIL.format("%"))).delete(synchronize_session=False)
    db.query(Agent).filter(Agent.email.like(EMAIL.format("%"))).delete(synchronize_session=False)
    db.commit()


def _add_alert(db, data, name, agent_key, assigned, company="moyza", previous=None, follow_ups=()):
    """Alerta de búsqueda general asignada a `agent_key` en `assigned` (UTC naive)."""
    from app.models.alert_follow_up import AlertFollowUp
    from app.models.property_alert import PropertyAlert

    alert = PropertyAlert(
        company_id=data[f"{company}_id"], agent_id=data[agent_key], lead_name=f"{TAG} {name}",
        status="PENDING", created_by=data["admin_user_id"], created_at=assigned, assigned_at=assigned,
        origin="search", business_type="Venta", previous_agent_id=data[previous] if previous else None,
    )
    db.add(alert)
    db.flush()
    for action, when in follow_ups:
        db.add(AlertFollowUp(alert_id=alert.id, action_type=action, created_at=when,
                             created_by=data["admin_user_id"]))
    db.flush()
    return alert


@pytest.fixture(scope="module")
def data():
    if not _server_up():
        pytest.skip(f"La app no responde en {BASE_URL}; tests de integración omitidos")

    from app.db.session import SessionLocal
    from app.models.agent import Agent
    from app.models.company import Company
    from app.models.role import Role
    from app.models.user import User

    db = SessionLocal()
    _cleanup(db)
    moyza = db.query(Company).filter_by(code="MOYZA").one()
    moes = db.query(Company).filter_by(code="MOES").one()
    role = db.query(Role).filter(Role.name.ilike("agent")).first()
    admin_user_id = db.query(User.id).filter(User.email == ADMIN_EMAIL).scalar()

    out = {"moyza_id": moyza.id, "moes_id": moes.id, "admin_user_id": admin_user_id}
    for key, companies in (("ana", [moyza]), ("bea", [moyza]), ("carla", [moyza]), ("moes", [moes])):
        agent = Agent(name=f"{TAG} {key.upper()}", email=EMAIL.format(key))
        agent.companies.extend(companies)
        user = User(email=EMAIL.format(key), full_name=f"{TAG} {key}", hashed_password="pytest-sin-login",
                    role_id=role.id if role else None, is_active=True)
        user.companies.extend(companies)
        db.add_all([agent, user])
        db.flush()
        out[key] = agent.id

    # Tras el corte de avisos (BUYER_ATTENTION_SINCE) y con más de 48 h hábiles
    now = datetime.utcnow()
    oldest = _add_alert(db, out, "NUNCA ANTIGUA", "ana", now - timedelta(days=10))
    reassigned = _add_alert(db, out, "REASIGNADA", "ana", now - timedelta(days=8), previous="bea",
                            follow_ups=[("CONTACTADO", now - timedelta(days=12)),       # del agente anterior
                                        ("REASIGNADA", now - timedelta(days=8))])     # nota del sistema
    newest = _add_alert(db, out, "NUNCA NUEVA", "ana", now - timedelta(days=6))
    _add_alert(db, out, "PARADA", "ana", now - timedelta(days=9),
               follow_ups=[("CONTACTADO", now - timedelta(days=8))])
    _add_alert(db, out, "VOLVER A LLAMAR", "ana", now - timedelta(days=9),
               follow_ups=[("SIN_RESPUESTA", now - timedelta(days=4))])
    _add_alert(db, out, "RECIENTE", "ana", now - timedelta(hours=1))
    _add_alert(db, out, "OTRA EMPRESA", "moes", now - timedelta(days=10), company="moes")
    db.commit()
    out.update(oldest=oldest.id, reassigned=reassigned.id, newest=newest.id,
               reassigned_at=reassigned.assigned_at)
    yield out

    _cleanup(db)
    db.close()


def _unmanaged_url(data, **extra):
    params = {"agent_id": data["ana"], "attention": "sin_gestion", **extra}
    return "/alerts?" + urllib.parse.urlencode(params, doseq=True)


def test_filtro_solo_sin_gestionar_en_orden_ascendente(data):
    status, body, _ = _Client(ADMIN_EMAIL, "MOYZA").get(_unmanaged_url(data))
    assert status == 200
    table = _alerts_table(body)
    names = [f"{TAG} NUNCA ANTIGUA", f"{TAG} REASIGNADA", f"{TAG} NUNCA NUEVA"]
    for name in names:
        assert name in table, name
    for name in ("PARADA", "VOLVER A LLAMAR", "RECIENTE", "OTRA EMPRESA"):
        assert f"{TAG} {name}" not in table, name
    # De la más antigua a la más nueva
    positions = [table.index(name) for name in names]
    assert positions == sorted(positions)
    # Chip con el total y enlace para quitarlo (conserva el agente)
    assert "Sin gestionar · 3" in body
    assert f'href="/alerts?agent_id={data["ana"]}#alertas"' in body


def test_marca_de_reasignada_solo_en_el_listado_filtrado(data):
    from app.core.business_calendar import to_madrid
    day = to_madrid(data["reassigned_at"]).strftime("%d/%m")
    mark = f"Reasignada el {day} · antes {TAG} BEA"

    _, body, _ = _Client(ADMIN_EMAIL, "MOYZA").get(_unmanaged_url(data))
    table = _alerts_table(body)
    assert table.count("Reasignada el ") == 1
    assert mark in table
    # Va en la fila de la reasignada
    row = table[table.index(f"{TAG} REASIGNADA"):]
    assert row.index(mark) < row.index("</tr>")

    _, body, _ = _Client(ADMIN_EMAIL, "MOYZA").get(f"/alerts?agent_id={data['ana']}")
    assert mark not in body


def test_filtro_ignora_el_estado_y_se_conserva_en_los_formularios(data):
    status, body, _ = _Client(ADMIN_EMAIL, "MOYZA").get(_unmanaged_url(data, status_filter="COMPLETED"))
    assert status == 200
    table = _alerts_table(body)
    assert f"{TAG} NUNCA ANTIGUA" in table and f"{TAG} NUNCA NUEVA" in table
    # Filtros (agente) y buscador de compradores lo llevan oculto; sin casillas de estado
    assert body.count('<input type="hidden" name="attention" value="sin_gestion">') == 2
    assert 'name="status_filter" value="COMPLETED"' not in body
    # La paginación conserva el filtro (enlace de tamaño / página construido con la query actual)
    assert "attention=sin_gestion" in body


def test_sin_agente_aisla_por_empresa(data):
    _, moyza_body, _ = _Client(ADMIN_EMAIL, "MOYZA").get("/alerts?attention=sin_gestion&per_page=300")
    moyza_table = _alerts_table(moyza_body)
    assert f"{TAG} NUNCA ANTIGUA" in moyza_table
    assert f"{TAG} OTRA EMPRESA" not in moyza_table

    _, moes_body, _ = _Client(ADMIN_EMAIL, "MOES").get(
        f"/alerts?attention=sin_gestion&agent_id={data['moes']}")
    moes_table = _alerts_table(moes_body)
    assert f"{TAG} OTRA EMPRESA" in moes_table
    assert f"{TAG} NUNCA ANTIGUA" not in moes_table
    # Un agente de MOYZA no filtra en MOES: el agente se combina con la empresa activa
    _, cross, _ = _Client(ADMIN_EMAIL, "MOES").get(_unmanaged_url(data))
    assert f"{TAG} NUNCA ANTIGUA" not in _alerts_table(cross)


def test_agente_ignora_el_parametro(data):
    status, body, _ = _Client(EMAIL.format("ana"), "MOYZA").get("/alerts?attention=sin_gestion")
    assert status == 200
    assert "Sin gestionar ·" not in body
    assert 'name="attention"' not in body
    # Vista por defecto de siempre (abiertas, con las casillas de estado)
    assert "Mostrando alertas pendientes y en proceso" in body


def test_reasignar_de_fila_vuelve_al_listado_filtrado(data):
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        alert = _add_alert(db, data, "FILA", "ana", datetime.utcnow() - timedelta(days=7))
        db.commit()
        alert_id = alert.id
    finally:
        db.close()

    back = _unmanaged_url(data, page=1)
    status, _, headers = _Client(ADMIN_EMAIL, "MOYZA").post(
        f"/alerts/{alert_id}/reassign", {"agent_id": data["carla"], "next": back})
    assert status == 302
    assert headers.get("location") == back
    assert _flashes(headers)[0]["category"] == "success"
