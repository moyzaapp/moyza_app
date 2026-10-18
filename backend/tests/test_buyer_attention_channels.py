"""
Canales de los avisos de compradores en horas hábiles (PLAN_ALERTAS_DIAS_HABILES.md §2.3, fase 3).

- Unitario: tramos de la cadencia in-app (al cruzar y cada 2 días hábiles).
- Con base de datos (transacción deshecha al terminar):
  - notificaciones `buyer_no_action` / `buyer_stage_stall`: una al cruzar,
    sin duplicados en el mismo tramo (aunque se lea), otra al abrir el tramo
    siguiente, y se marcan leídas cuando dejan de aplicar;
  - job del email con un GmailService falso: no envía en sábado ni en lunes
    festivo; en día hábil, un email por agente con las dos secciones.
- Integración contra la app levantada (se omite si no responde): el listado
  /alerts muestra el badge y el detalle el vencimiento.

Ningún test envía emails reales ni WhatsApp.

    docker exec moyza_backend python -m pytest tests/test_buyer_attention_channels.py -q
"""
import os
import urllib.error
import urllib.request
from datetime import datetime
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.core import business_calendar as bc
from app.core.constants import AlertStatus
from app.models.notification import Notification
from app.services import notification_service as ns
from app.services.notification_service import NotificationKind


def L(*args) -> datetime:
    """Hora local de Madrid -> UTC naive."""
    return bc.to_utc(datetime(*args))


# ---------------------------------------------------------------------------
# Unitario: cadencia
# ---------------------------------------------------------------------------

def test_tramos_de_aviso_cada_dos_dias_habiles():
    due = L(2026, 10, 15, 9, 0)   # jueves
    assert ns.buyer_reminder_slot(due, L(2026, 10, 16, 8, 0), 2) == due
    assert ns.buyer_reminder_slot(due, L(2026, 10, 19, 8, 0), 2) == due
    # jueves 9:00 + 2 días hábiles = lunes 9:00
    assert ns.buyer_reminder_slot(due, L(2026, 10, 20, 8, 0), 2) == L(2026, 10, 19, 9, 0)
    # lunes 9:00 + 2 = miércoles 9:00
    assert ns.buyer_reminder_slot(due, L(2026, 10, 22, 8, 0), 2) == L(2026, 10, 21, 9, 0)


# ---------------------------------------------------------------------------
# Base de datos
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    from sqlalchemy.orm import Session
    from app.db.session import engine
    try:
        connection = engine.connect()
    except Exception as e:  # pragma: no cover - depende del entorno
        pytest.skip(f"Sin base de datos: {e}")
    transaction = connection.begin()
    session = Session(bind=connection, autoflush=False, join_transaction_mode="create_savepoint")
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def ctx(db):
    from app.models.agent import Agent
    from app.models.company import Company
    from app.models.property_alert import PropertyAlert
    from app.models.user import User

    moyza = db.query(Company).filter_by(code="MOYZA").one()
    agent = Agent(name="PYTEST-CANAL ANA", email="pytest.canal.ana@example.com")
    agent.companies.append(moyza)
    user = User(email="pytest.canal.ana@example.com", full_name="Ana", hashed_password="x", is_active=True)
    admin = User(email="pytest.canal.admin@example.com", full_name="Admin", hashed_password="x", is_active=True)
    db.add_all([agent, user, admin])
    db.flush()
    assigned = L(2026, 10, 13, 9, 0)   # martes
    alert = PropertyAlert(company_id=moyza.id, agent_id=agent.id, lead_name="PYTEST-CANAL Comprador",
                          lead_phone="600000000", status=AlertStatus.IN_PROGRESS, created_by=admin.id,
                          created_at=assigned, assigned_at=assigned, origin="search", business_type="Venta")
    db.add(alert)
    db.flush()
    return SimpleNamespace(db=db, moyza=moyza, agent=agent, user=user, admin=admin, alert=alert)


def _items(ctx, now):
    from app.services.buyer_attention_service import find_buyers_needing_attention
    return find_buyers_needing_attention(ctx.db, agent_id=ctx.agent.id, now=now)


def _run(ctx, now):
    return ns.run_buyer_attention(ctx.db, _items(ctx, now), now=now, repeat_business_days=2)


def _mine(ctx, kind=None):
    query = ctx.db.query(Notification).filter(Notification.user_id == ctx.user.id)
    if kind:
        query = query.filter(Notification.kind == kind)
    return query.order_by(Notification.created_at, Notification.id).all()


def _follow_up(ctx, action_type, when):
    from app.models.alert_follow_up import AlertFollowUp
    ctx.db.add(AlertFollowUp(alert_id=ctx.alert.id, action_type=action_type, created_at=when, created_by=ctx.user.id))
    ctx.db.flush()
    ctx.db.expire(ctx.alert, ["follow_ups"])


def test_notifica_al_cruzar_y_cada_dos_dias_habiles(ctx):
    # Jueves 8:00: aún no ha vencido (vence el jueves 9:00)
    assert _run(ctx, L(2026, 10, 15, 8, 0)) == 0
    # Viernes 8:00: una
    assert _run(ctx, L(2026, 10, 16, 8, 0)) == 1
    [first] = _mine(ctx, NotificationKind.BUYER_NO_ACTION)
    assert first.title == "Comprador sin gestión · PYTEST-CANAL Comprador"
    assert "hábiles sin gestión" in first.body and "venció el jueves 15/10 a las 09:00" in first.body
    assert first.url == f"/alerts/{ctx.alert.id}"
    assert (first.entity_type, first.entity_id) == ("alert", ctx.alert.id)
    # Mismo tramo: no se repite, ni aunque la haya leído
    assert _run(ctx, L(2026, 10, 16, 15, 0)) == 0
    ns.mark_read(ctx.db, ctx.user.id, ctx.moyza.id, ids=[first.id], now=L(2026, 10, 16, 16, 0))
    assert _run(ctx, L(2026, 10, 19, 8, 0)) == 0
    # Martes 8:00: tramo siguiente (lunes 9:00) -> otra
    assert _run(ctx, L(2026, 10, 20, 8, 0)) == 1
    assert _run(ctx, L(2026, 10, 21, 8, 0)) == 0
    # Jueves 8:00 (tramo del miércoles 9:00): otra, y la del martes sin leer queda superada
    assert _run(ctx, L(2026, 10, 22, 8, 0)) == 1
    notes = _mine(ctx, NotificationKind.BUYER_NO_ACTION)
    assert len(notes) == 3
    assert [n.read_at is None for n in notes] == [False, False, True]
    assert ns.unread_count(ctx.db, ctx.user.id, ctx.moyza.id) == 1


def test_gestion_resuelve_r1_y_avance_resuelve_r2(ctx):
    assert _run(ctx, L(2026, 10, 16, 8, 0)) == 1
    # «Sin respuesta»: R1 deja de aplicar (se marca leída); R2 sigue corriendo y ya venció
    _follow_up(ctx, "SIN_RESPUESTA", L(2026, 10, 16, 10, 0))
    assert ns.resolve_buyer_notifications(ctx.db, alert_ids=[ctx.alert.id], now=L(2026, 10, 16, 10, 5)) == 1
    assert ns.unread_count(ctx.db, ctx.user.id, ctx.moyza.id) == 0
    assert _run(ctx, L(2026, 10, 19, 8, 0)) == 1
    [stall] = _mine(ctx, NotificationKind.BUYER_STAGE_STALL)
    assert stall.title == "Comprador sin avanzar · PYTEST-CANAL Comprador"
    assert "sin pasar de Primera Llamada" in stall.body
    # Pasa a Contactado: R2 ya no aplica
    _follow_up(ctx, "CONTACTADO", L(2026, 10, 19, 10, 0))
    assert ns.resolve_buyer_notifications(ctx.db, alert_ids=[ctx.alert.id], now=L(2026, 10, 19, 10, 5)) == 1
    assert ns.unread_count(ctx.db, ctx.user.id, ctx.moyza.id) == 0


def test_alerta_cerrada_se_resuelve_en_la_pasada_del_job(ctx):
    assert _run(ctx, L(2026, 10, 16, 8, 0)) == 1
    ctx.alert.status = AlertStatus.COMPLETED
    ctx.db.flush()
    now = L(2026, 10, 19, 8, 0)
    resolved = ns.resolve_buyer_notifications(ctx.db, items=_items(ctx, now), now=now)
    assert resolved >= 1
    assert ns.unread_count(ctx.db, ctx.user.id, ctx.moyza.id) == 0


class FakeGmail:
    """GmailService de mentira: guarda lo que se habría enviado."""

    def __init__(self):
        self.sent = []

    def send_email(self, to, subject, html_body):
        self.sent.append(SimpleNamespace(to=to, subject=subject, body=html_body))
        return True


def _job(ctx, now):
    from app.services.buyer_reminder_service import run_buyer_reminders
    gmail = FakeGmail()
    summary = run_buyer_reminders(ctx.db, gmail, 48, now=now)
    return summary, [m for m in gmail.sent if m.to == ctx.agent.email]


@pytest.mark.parametrize("now", [L(2026, 10, 17, 8, 0), L(2026, 11, 2, 8, 0)], ids=["sabado", "lunes-festivo"])
def test_job_no_envia_en_dia_no_habil(ctx, now):
    summary, mine = _job(ctx, now)
    assert summary["business_day"] is False
    assert summary["emails"] == [] and mine == []
    assert _mine(ctx) == []


def test_job_en_dia_habil_un_email_con_dos_secciones(ctx):
    from app.models.property_alert import PropertyAlert
    # Segundo comprador con «sin respuesta» repetidos: va a la sección de R2
    stalled = PropertyAlert(company_id=ctx.moyza.id, agent_id=ctx.agent.id, lead_name="PYTEST-CANAL Sin avance",
                            status=AlertStatus.IN_PROGRESS, created_by=ctx.admin.id,
                            created_at=L(2026, 10, 13, 9, 0), assigned_at=L(2026, 10, 13, 9, 0), origin="search")
    ctx.db.add(stalled)
    ctx.db.flush()
    from app.models.alert_follow_up import AlertFollowUp
    ctx.db.add(AlertFollowUp(alert_id=stalled.id, action_type="SIN_RESPUESTA",
                             created_at=L(2026, 10, 15, 17, 0), created_by=ctx.user.id))
    ctx.db.flush()

    summary, mine = _job(ctx, L(2026, 10, 16, 8, 0))   # viernes
    assert summary["business_day"] is True
    assert len(mine) == 1
    email = mine[0]
    assert email.subject.endswith("2 comprador(es) requieren atención")
    assert "Sin gestión (1)" in email.body and "Sin avance de etapa (1)" in email.body
    assert "PYTEST-CANAL Comprador" in email.body and "PYTEST-CANAL Sin avance" in email.body
    assert "horas hábiles" in email.body
    [entry] = [e for e in summary["emails"] if e["to"] == ctx.agent.email]
    assert entry["no_action"] == ["PYTEST-CANAL Comprador"]
    assert entry["stage_stall"] == ["PYTEST-CANAL Sin avance"]
    # En la misma pasada, los avisos in-app (uno por alerta)
    kinds = sorted(n.kind for n in _mine(ctx))
    assert kinds == [NotificationKind.BUYER_NO_ACTION, NotificationKind.BUYER_STAGE_STALL]


def test_email_escapa_el_nombre():
    from app.services.buyer_reminder_service import _build_email_body
    body = _build_email_body("Ana", [{
        "buyer_name": "<b>X</b>", "buyer_phone": "600", "rule": "no_action", "business_hours_elapsed": 50,
        "elapsed_label": "2 d 2 h", "due_label": "martes 20/10 a las 12:00",
    }], 48)
    assert "&lt;b&gt;X&lt;/b&gt;" in body and "<b>X</b>" not in body
    assert "Sin avance de etapa" not in body


# ---------------------------------------------------------------------------
# Integración: listado y detalle (app levantada)
# ---------------------------------------------------------------------------

BASE_URL = os.getenv("MOYZA_TEST_BASE_URL", "http://localhost:8000")
ADMIN_EMAIL = os.getenv("MOYZA_TEST_ADMIN_EMAIL", "admin@moyza.com")
TAG = "PYTEST-AVISO-HABIL"


def _server_up() -> bool:
    try:
        urllib.request.urlopen(BASE_URL + "/", timeout=3)
        return True
    except Exception:
        return False


def _get(path, company="MOYZA"):
    from app.core.security import create_access_token
    token = create_access_token({"sub": ADMIN_EMAIL})
    req = urllib.request.Request(BASE_URL + path)
    req.add_header("Cookie", f"access_token={token}; active_company={company}")
    try:
        resp = urllib.request.urlopen(req, timeout=20)
        return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


@pytest.fixture
def live_alert():
    if not _server_up():
        pytest.skip(f"La app no responde en {BASE_URL}; tests de integración omitidos")
    from app.db.session import SessionLocal
    from app.models.agent import Agent
    from app.models.company import Company
    from app.models.property_alert import PropertyAlert
    from app.models.user import User
    from app.services.company_scope import scope_agents

    session = SessionLocal()
    moyza = session.query(Company).filter_by(code="MOYZA").one()
    agent = scope_agents(session.query(Agent), moyza.id).order_by(Agent.id).first()
    admin = session.query(User).filter(User.email == ADMIN_EMAIL).first()
    if agent is None or admin is None:
        session.close()
        pytest.skip("Sin agente en MOYZA o sin admin")
    # Asignada hace un mes: vencida seguro, sea cual sea el día
    assigned = datetime.utcnow().replace(microsecond=0) - timedelta(days=30)
    alert = PropertyAlert(company_id=moyza.id, agent_id=agent.id, lead_name=f"{TAG} Comprador",
                          status=AlertStatus.IN_PROGRESS, created_by=admin.id, created_at=assigned,
                          assigned_at=assigned, origin="search", business_type="Venta")
    session.add(alert)
    session.commit()
    yield alert
    session.delete(session.get(PropertyAlert, alert.id))
    session.commit()
    session.close()


def test_listado_y_detalle_muestran_horas_habiles(live_alert):
    status, html = _get(f"/alerts?q={TAG}")
    assert status == 200
    assert f"{TAG} Comprador" in html
    assert "Sin gestión · " in html and " hábiles" in html
    assert "Venció el " in html

    status, html = _get(f"/alerts/{live_alert.id}")
    assert status == 200
    assert "Sin gestión · " in html
    assert "Venció el " in html
