"""
Alerta reasignada "como nueva" para el agente y bloqueo real de la cola
(PLAN_ALERTA_COMO_NUEVA.md).

- Los unitarios de la ventana de asignación (sin base de datos) están en
  test_alert_assignment.py, junto a los del servicio de asignación.
- Rutas y servicios en proceso contra una SQLite en memoria con los modelos
  reales (patrón de test_alerts_pagination.py): no necesitan la app levantada
  ni PostgreSQL. Cada test parte de una base nueva.

    cd backend && python -m pytest tests/test_alert_view.py -q
"""
import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from app.core.constants import AlertStatus
from app.services import alert_view
from app.web.utils.flash import FLASH_COOKIE_NAME
from app.web.utils.flash import decode_flash


T0 = datetime(2026, 10, 1, 9, 0)
REASSIGNED_AT = datetime(2026, 10, 10, 11, 30)
LOCKED_TEXT = "Esta alerta está en tu cola. Gestiona primero las anteriores para verla."


# ---------------------------------------------------------------------------
# SQLite en memoria
# ---------------------------------------------------------------------------

@pytest.fixture
def env():
    """MOYZA con un admin, y Ana y Bea (agentes con usuario). Propiedad de Ana."""
    import app.db.base as db_base
    from app.models.agent import Agent
    from app.models.company import Company
    from app.models.property import Property
    from app.models.role import Role
    from app.models.user import User

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    db_base.Base.metadata.create_all(engine)
    # Como SessionLocal de la app: sin autoflush (assign consulta antes de fijar el agente)
    db = sessionmaker(bind=engine, autoflush=False)()

    company = Company(code="MOYZA", name="MOYZA", primary_color="#000000")
    admin_role, agent_role = Role(name="admin"), Role(name="agent")
    admin = User(email="admin@example.com", full_name="Admin Uno", hashed_password="x", role=admin_role)
    users = {
        key: User(email=f"{key}@example.com", full_name=key.title(), hashed_password="x", role=agent_role)
        for key in ("ana", "bea")
    }
    agents = {key: Agent(name=f"Agente {key.title()}", email=f"{key}@example.com") for key in ("ana", "bea")}
    for obj in [admin, *users.values(), *agents.values()]:
        obj.companies.append(company)
    db.add_all([company, admin, *users.values(), *agents.values()])
    db.flush()

    prop = Property(title="Piso Centro", address="Calle Real 1", city="Jaen",
                    company_id=company.id, agent_id=agents["ana"].id)
    db.add(prop)
    db.commit()

    yield SimpleNamespace(db=db, company=company, admin=admin, users=users, agents=agents, prop=prop)

    db.close()
    engine.dispose()


def _new_alert(env, agent_key, name, created_at, buyer=None):
    """Alta como la hace create_alert: assigned_at = created_at."""
    from app.models.property_alert import PropertyAlert
    from app.services import alert_assignment_service as svc

    alert = PropertyAlert(property=env.prop, lead_name=name, lead_phone="600111222", status=AlertStatus.PENDING,
                          priority="NORMAL", created_by=env.admin.id, created_at=created_at,
                          buyer_id=buyer.id if buyer else None)
    env.db.add(alert)
    svc.assign(env.db, alert, env.agents[agent_key], env.admin, None, is_new=True, now=created_at)
    env.db.commit()
    return alert


def _follow_up(env, alert, user, action, created_at, notes=None, next_action_date=None):
    from app.models.alert_follow_up import AlertFollowUp
    env.db.add(AlertFollowUp(alert_id=alert.id, action_type=action, notes=notes, created_at=created_at,
                             created_by=user.id, next_action_date=next_action_date))
    env.db.commit()


def _reassign(env, alert, to_key, reason="Carga de trabajo", now=REASSIGNED_AT):
    from app.services import alert_assignment_service as svc
    result = svc.assign(env.db, alert, env.agents[to_key], env.admin, reason, is_new=False, now=now)
    env.db.commit()
    return result


@pytest.fixture
def reassigned(env):
    """Alerta de Ana con un seguimiento suyo, reasignada a Bea con motivo."""
    alert = _new_alert(env, "ana", "Comprador Reasignado", T0)
    alert.status = AlertStatus.IN_PROGRESS
    alert.read_at = T0 + timedelta(minutes=30)
    _follow_up(env, alert, env.users["ana"], "PRIMERA_LLAMADA", T0 + timedelta(days=1),
               notes="Nota privada de Ana", next_action_date=T0 + timedelta(days=2))
    _reassign(env, alert, "bea")
    return alert


def _request(env, user, path, method="GET"):
    return Request({
        "type": "http", "method": method, "scheme": "http", "server": ("testserver", 80),
        "path": path, "root_path": "", "query_string": b"", "headers": [(b"host", b"testserver")],
        "state": {"user": user, "company": env.company, "allowed_companies": [env.company]},
    })


def _flash(response):
    cookie = response.headers.get("set-cookie", "")
    raw = cookie.split(f"{FLASH_COOKIE_NAME}=", 1)[1].split(";", 1)[0].strip('"')
    return decode_flash(raw)[0]


def _detail(env, user, alert):
    from app.web.routes.alerts import alert_detail
    response = asyncio.run(alert_detail(alert.id, _request(env, user, f"/alerts/{alert.id}"), db=env.db))
    return response, response.body.decode("utf-8")


def _madrid(value, fmt="%d/%m/%Y %H:%M"):
    from app.web.template_env import madrid_dt
    return madrid_dt(value, fmt)


# ---------------------------------------------------------------------------
# Cola: los seguimientos del agente anterior no la desbloquean
# ---------------------------------------------------------------------------

def test_seguimientos_del_agente_anterior_no_desbloquean_la_cola(env, reassigned):
    later = _new_alert(env, "bea", "Comprador Posterior", REASSIGNED_AT + timedelta(hours=1))

    # La reasignada es la primera de la cola de Bea y no tiene gestión suya
    assert [a.id for a in alert_view.agent_open_alerts_ordered(env.agents["bea"].id, env.db, env.company.id)] == [
        reassigned.id, later.id
    ]
    assert alert_view.get_locked_alert_ids(env.agents["bea"].id, env.db, env.company.id) == {later.id}

    # En cuanto Bea registra un seguimiento, la siguiente se desbloquea
    _follow_up(env, reassigned, env.users["bea"], "CONTACTADO", REASSIGNED_AT + timedelta(hours=2))
    assert alert_view.get_locked_alert_ids(env.agents["bea"].id, env.db, env.company.id) == set()


def test_get_locked_alert_ids_dos_consultas(env, reassigned):
    from sqlalchemy import event

    for i in range(5):
        _new_alert(env, "bea", f"Cola {i}", REASSIGNED_AT + timedelta(hours=i + 1))
    # Ids antes de escuchar: tras el commit, leerlos recarga las filas
    agent_id, company_id = env.agents["bea"].id, env.company.id
    statements = []
    listener = lambda *args: statements.append(args[2])  # noqa: E731
    event.listen(env.db.get_bind(), "before_cursor_execute", listener)
    try:
        locked = alert_view.get_locked_alert_ids(agent_id, env.db, company_id)
    finally:
        event.remove(env.db.get_bind(), "before_cursor_execute", listener)
    assert len(locked) == 5
    assert len(statements) == 2, statements


# ---------------------------------------------------------------------------
# Detalle de la alerta
# ---------------------------------------------------------------------------

def test_agente_no_puede_abrir_una_alerta_bloqueada(env, reassigned):
    from app.models.property_alert import PropertyAlert

    locked = _new_alert(env, "bea", "Comprador En Cola", REASSIGNED_AT + timedelta(hours=1))
    response, _ = _detail(env, env.users["bea"], locked)

    assert response.status_code == 302
    assert response.headers["location"] == "/alerts"
    assert _flash(response) == {"category": "warning", "message": LOCKED_TEXT}
    env.db.expire_all()
    stored = env.db.get(PropertyAlert, locked.id)
    assert stored.read_at is None and stored.status == AlertStatus.PENDING

    # El admin sí la abre (nunca está bloqueado) y no la marca como leída
    response, _ = _detail(env, env.admin, locked)
    assert response.status_code == 200
    env.db.expire_all()
    assert env.db.get(PropertyAlert, locked.id).read_at is None


def test_agente_ve_la_reasignada_como_nueva(env, reassigned):
    from app.models.property_alert import PropertyAlert

    response, html = _detail(env, env.users["bea"], reassigned)
    assert response.status_code == 200
    ctx = response.context

    # Sin rastro de la reasignación ni del agente anterior
    for hidden in ("Antes:", "Reasignada", "Historial de asignaciones", "Motivo:", "Carga de trabajo",
                   "Nota privada de Ana", 'id="alertAssignment"', "Agente Ana", "Fecha creación"):
        assert hidden not in html, hidden
    assert ctx["follow_ups"] == [] and ctx["show_assignment"] is False
    assert "Aún no hay seguimientos. Registra el primero." in html

    # La fecha que ve es la de su asignación
    assert ctx["display_date"] == REASSIGNED_AT
    assert _madrid(REASSIGNED_AT) in html
    assert _madrid(T0) not in html

    # No puede cerrarla: el seguimiento de Ana no cuenta
    assert ctx["can_complete"] is False

    # Al abrirla queda leída y en proceso
    env.db.expire_all()
    stored = env.db.get(PropertyAlert, reassigned.id)
    assert stored.read_at is not None and stored.status == AlertStatus.IN_PROGRESS

    # Su propio seguimiento sí lo ve, y ya puede cerrarla
    _follow_up(env, reassigned, env.users["bea"], "CONTACTADO", REASSIGNED_AT + timedelta(hours=1),
               notes="Primera llamada de Bea")
    response, html = _detail(env, env.users["bea"], reassigned)
    assert "Primera llamada de Bea" in html and "Nota privada de Ana" not in html
    assert response.context["can_complete"] is True


def test_admin_lo_ve_todo(env, reassigned):
    response, html = _detail(env, env.admin, reassigned)
    assert response.status_code == 200
    for shown in ('id="alertAssignment"', "Antes: Agente Ana", "Motivo: Carga de trabajo",
                  "Historial de asignaciones (2)", "Reasignada de Agente Ana a Agente Bea",
                  "Nota privada de Ana", "Fecha creación", "Asignada"):
        assert shown in html, shown
    assert _madrid(T0) in html and _madrid(REASSIGNED_AT) in html
    assert len(response.context["follow_ups"]) == 2
    # Tampoco el admin puede cerrarla sin un seguimiento posterior a la reasignación
    assert response.context["can_complete"] is False


def test_complete_alert_exige_seguimiento_desde_la_asignacion(env, reassigned):
    from app.models.property_alert import PropertyAlert
    from app.web.routes.alerts import complete_alert

    def complete():
        request = _request(env, env.admin, f"/alerts/{reassigned.id}/complete", method="POST")
        return asyncio.run(complete_alert(reassigned.id, request, db=env.db))

    response = complete()
    assert response.headers["location"] == f"/alerts/{reassigned.id}"
    assert "al menos un seguimiento" in _flash(response)["message"]
    env.db.expire_all()
    assert env.db.get(PropertyAlert, reassigned.id).status == AlertStatus.PENDING

    _follow_up(env, reassigned, env.users["bea"], "CONTACTADO", REASSIGNED_AT + timedelta(hours=1))
    response = complete()
    assert _flash(response)["category"] == "success"
    env.db.expire_all()
    assert env.db.get(PropertyAlert, reassigned.id).status == AlertStatus.COMPLETED


# ---------------------------------------------------------------------------
# Listado y ficha del comprador
# ---------------------------------------------------------------------------

def _list(env, user):
    from app.web.routes.alerts import alerts_page
    response = asyncio.run(alerts_page(
        _request(env, user, "/alerts"), q="", status_filter=[], agent_id=None,
        page=None, per_page=None, b_q="", b_page=None, db=env.db,
    ))
    return response, response.body.decode("utf-8")


def test_listado_etapa_y_fecha_por_rol(env, reassigned):
    response, html = _list(env, env.users["bea"])
    ctx = response.context
    assert reassigned.id not in ctx["alert_stages"]          # "Sin iniciar" para Bea
    assert ctx["display_dates"][reassigned.id] == REASSIGNED_AT
    assert _madrid(REASSIGNED_AT) in html and _madrid(T0) not in html

    response, html = _list(env, env.admin)
    ctx = response.context
    assert ctx["alert_stages"][reassigned.id]["value"] == "PRIMERA_LLAMADA"
    assert ctx["display_dates"][reassigned.id] == T0
    assert _madrid(T0) in html


def test_listado_del_agente_ordena_por_asignacion(env, reassigned):
    # Creada después que la reasignada pero asignada antes de la reasignación
    middle = _new_alert(env, "bea", "Comprador Intermedio", T0 + timedelta(days=3))
    response, _ = _list(env, env.users["bea"])
    assert [a.id for a in response.context["alerts"]] == [reassigned.id, middle.id]
    response, _ = _list(env, env.admin)
    assert [a.id for a in response.context["alerts"]] == [middle.id, reassigned.id]


def test_ficha_del_comprador_por_rol(env):
    from app.models.buyer import Buyer
    from app.web.routes.alerts import buyer_detail

    buyer = Buyer(name="Comprador Ficha", company_id=env.company.id, created_by=env.admin.id)
    env.db.add(buyer)
    env.db.commit()
    # `queued` se reasigna dos veces y vuelve a Bea: entra al final de su cola,
    # detrás de `head`, que no tiene seguimiento → `queued` queda bloqueada.
    queued = _new_alert(env, "bea", "Comprador Ficha", T0, buyer=buyer)
    head = _new_alert(env, "bea", "Comprador Ficha", T0 + timedelta(days=1), buyer=buyer)
    others = _new_alert(env, "ana", "Comprador Ficha", T0 + timedelta(days=2), buyer=buyer)
    _reassign(env, queued, "ana", now=REASSIGNED_AT)
    _reassign(env, queued, "bea", now=REASSIGNED_AT + timedelta(hours=1))

    def render(user):
        response = asyncio.run(buyer_detail(buyer.id, _request(env, user, f"/buyers/{buyer.id}"),
                                            tab="alerts", db=env.db))
        return response, response.body.decode("utf-8")

    response, html = render(env.users["bea"])
    ctx = response.context
    # Solo las suyas (no la de Ana), ordenadas por fecha de asignación
    assert [a.id for a in ctx["buyer_alerts"]] == [queued.id, head.id]
    assert ctx["locked_alert_ids"] == {queued.id}
    panel = html[html.index('id="panel-alerts"'):]
    assert f'href="/alerts/{head.id}"' in panel
    assert f'href="/alerts/{queued.id}"' not in panel and f'href="/alerts/{others.id}"' not in panel
    assert "En cola" in panel and "Información oculta" in panel
    assert ctx["display_dates"][head.id] == T0 + timedelta(days=1)

    response, html = render(env.admin)
    ctx = response.context
    assert {a.id for a in ctx["buyer_alerts"]} == {queued.id, head.id, others.id}
    panel = html[html.index('id="panel-alerts"'):]
    assert "En cola" not in panel and f'href="/alerts/{queued.id}"' in panel
    assert ctx["display_dates"][queued.id] == T0


# ---------------------------------------------------------------------------
# Inicio del agente y notificación
# ---------------------------------------------------------------------------

def test_agenda_sin_seguimientos_del_anterior_ni_alertas_bloqueadas(env, reassigned):
    from app.services.dashboard_service import DashboardService

    now = REASSIGNED_AT + timedelta(days=5)
    svc = DashboardService(env.db, env.company.id)

    # La próxima acción de Ana (vencida) no entra en la agenda de Bea
    assert svc.agenda(env.agents["bea"], now=now)["due"] == []

    # Una alerta bloqueada no sale aunque tenga próxima acción (registrada por el admin)
    locked = _new_alert(env, "bea", "Comprador En Cola", REASSIGNED_AT + timedelta(hours=1))
    _follow_up(env, locked, env.admin, "CONTACTADO", REASSIGNED_AT + timedelta(hours=2),
               next_action_date=now - timedelta(days=1))
    assert alert_view.get_locked_alert_ids(env.agents["bea"].id, env.db, env.company.id) == {locked.id}
    agenda = svc.agenda(env.agents["bea"], now=now)
    assert agenda["due"] == [] and agenda["due_total"] == 0

    # Cuando Bea gestiona la reasignada, se desbloquea y aparecen ambas
    _follow_up(env, reassigned, env.users["bea"], "CONTACTADO", REASSIGNED_AT + timedelta(hours=3),
               next_action_date=now - timedelta(hours=1))
    agenda = svc.agenda(env.agents["bea"], now=now)
    assert {d["alert_id"] for d in agenda["due"]} == {reassigned.id, locked.id}


def test_notificacion_sin_motivo(env):
    from app.models.notification import Notification

    alert = _new_alert(env, "ana", "Comprador Aviso", T0)
    _reassign(env, alert, "bea", reason="Sin respuesta del anterior")
    [note] = env.db.query(Notification).filter(Notification.user_id == env.users["bea"].id).all()
    assert note.title == "Te han asignado un comprador: Comprador Aviso"
    assert note.body == "Piso Centro"
    assert note.url == f"/alerts/{alert.id}"
    # El motivo se sigue guardando (trazabilidad para el admin)
    assert alert.assignment_reason == "Sin respuesta del anterior"
