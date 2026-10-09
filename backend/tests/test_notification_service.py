"""
Tests de las notificaciones in-app (PLAN_DASHBOARD_INICIO.md §4, fase 5).

Con base de datos, dentro de una transacción externa que se deshace al
terminar (los commit del servicio solo cierran savepoints): deduplicación,
nunca al actor, resolución agente -> usuario, aislamiento por empresa,
marcado como leídas, retención de 90 días, eventos de visita y job de
seguimientos. Ninguno envía emails ni WhatsApp (el servicio no tiene esa
capacidad).

    docker exec moyza_backend python -m pytest tests/test_notification_service.py -q
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.models.notification import Notification
from app.services import notification_service as ns
from app.services.notification_service import NotificationKind


NOW = datetime(2026, 10, 8, 10, 0)   # UTC: 12:00 en Madrid


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
    """Empresas, dos agentes con su usuario (Laura en MOYZA y MOES) y un admin actor."""
    from app.models.agent import Agent
    from app.models.company import Company
    from app.models.user import User

    moyza = db.query(Company).filter_by(code="MOYZA").one()
    moes = db.query(Company).filter_by(code="MOES").one()

    laura_agent = Agent(name="PYTEST-NOTIF LAURA", email="pytest.notif.laura@example.com")
    carlos_agent = Agent(name="PYTEST-NOTIF CARLOS", email="pytest.notif.carlos@example.com")
    laura_agent.companies.extend([moyza, moes])
    carlos_agent.companies.append(moyza)
    # El email del usuario con otras mayúsculas: la resolución no las distingue
    laura = User(email="Pytest.Notif.Laura@example.com", full_name="Laura", hashed_password="x", is_active=True)
    carlos = User(email="pytest.notif.carlos@example.com", full_name="Carlos", hashed_password="x", is_active=True)
    admin = User(email="pytest.notif.admin@example.com", full_name="Admin", hashed_password="x", is_active=True)
    db.add_all([laura_agent, carlos_agent, laura, carlos, admin])
    db.flush()
    return SimpleNamespace(db=db, moyza=moyza, moes=moes, laura_agent=laura_agent, carlos_agent=carlos_agent,
                           laura=laura, carlos=carlos, admin=admin)


def _notify(ctx, users, company=None, entity=("visit", 1), actor=None, now=NOW, kind=NotificationKind.VISIT_ON_MY_PROPERTY):
    return ns.notify(ctx.db, users=users, company_id=(company or ctx.moyza).id, kind=kind,
                     title="PYTEST aviso", url="/properties/1", actor=actor, entity=entity, now=now)


# ---------------------------------------------------------------------------
# Destinatarios
# ---------------------------------------------------------------------------

def test_resolucion_agente_usuario_por_email_sin_mayusculas(ctx):
    assert [u.id for u in ns.users_for_agent(ctx.db, ctx.laura_agent)] == [ctx.laura.id]
    assert ns.users_for_agent(ctx.db, None) == []


def test_usuario_inactivo_no_recibe(ctx):
    ctx.carlos.is_active = False
    ctx.db.flush()
    assert ns.users_for_agent(ctx.db, ctx.carlos_agent) == []


# ---------------------------------------------------------------------------
# notify: actor, deduplicación y empresa
# ---------------------------------------------------------------------------

def test_nunca_al_actor(ctx):
    created = _notify(ctx, [ctx.laura, ctx.carlos], actor=ctx.laura)
    assert [n.user_id for n in created] == [ctx.carlos.id]


def test_deduplica_24h_sin_leer(ctx):
    assert len(_notify(ctx, [ctx.laura])) == 1
    # Mismo tipo y entidad, sin leer, dentro de 24 h -> no se repite
    assert _notify(ctx, [ctx.laura], now=NOW + timedelta(hours=23)) == []
    # Otra entidad sí
    assert len(_notify(ctx, [ctx.laura], entity=("visit", 2))) == 1
    # Pasadas 24 h, sí
    assert len(_notify(ctx, [ctx.laura], now=NOW + timedelta(hours=25))) == 1


def test_leida_no_bloquea_una_nueva(ctx):
    [first] = _notify(ctx, [ctx.laura])
    ns.mark_read(ctx.db, ctx.laura.id, ctx.moyza.id, ids=[first.id], now=NOW)
    assert len(_notify(ctx, [ctx.laura], now=NOW + timedelta(hours=1))) == 1


def test_aislamiento_por_empresa(ctx):
    _notify(ctx, [ctx.laura], company=ctx.moyza)
    _notify(ctx, [ctx.laura], company=ctx.moes, entity=("visit", 99))
    assert ns.unread_count(ctx.db, ctx.laura.id, ctx.moyza.id) == 1
    assert ns.unread_count(ctx.db, ctx.laura.id, ctx.moes.id) == 1
    # La misma entidad en otra empresa no cuenta como duplicado
    assert len(_notify(ctx, [ctx.laura], company=ctx.moes)) == 1
    # Marcar todas en MOYZA no toca las de MOES
    assert ns.mark_read(ctx.db, ctx.laura.id, ctx.moyza.id, all_=True) == 1
    assert ns.unread_count(ctx.db, ctx.laura.id, ctx.moes.id) == 2
    # Ni se pueden leer por id desde otra empresa
    moes_ids = [n.id for n in ns.recent(ctx.db, ctx.laura.id, ctx.moes.id)]
    assert ns.mark_read(ctx.db, ctx.laura.id, ctx.moyza.id, ids=moes_ids) == 0
    assert ns.get_for_user(ctx.db, moes_ids[0], ctx.laura.id, ctx.moyza.id) is None


def test_mark_read_solo_del_usuario(ctx):
    [mine] = _notify(ctx, [ctx.laura])
    assert ns.mark_read(ctx.db, ctx.carlos.id, ctx.moyza.id, ids=[mine.id]) == 0
    assert ns.unread_count(ctx.db, ctx.laura.id, ctx.moyza.id) == 1


def test_recent_no_leidas_primero(ctx):
    [old] = _notify(ctx, [ctx.laura], entity=("visit", 1), now=NOW - timedelta(hours=2))
    [new] = _notify(ctx, [ctx.laura], entity=("visit", 2), now=NOW)
    ns.mark_read(ctx.db, ctx.laura.id, ctx.moyza.id, ids=[new.id])
    assert [n.id for n in ns.recent(ctx.db, ctx.laura.id, ctx.moyza.id)][:2] == [old.id, new.id]


def test_limpieza_de_leidas_a_90_dias(ctx):
    [old] = _notify(ctx, [ctx.laura], entity=("visit", 1))
    [recent_read] = _notify(ctx, [ctx.laura], entity=("visit", 2))
    [unread] = _notify(ctx, [ctx.laura], entity=("visit", 3), now=NOW - timedelta(days=200))
    old.read_at = NOW - timedelta(days=91)
    recent_read.read_at = NOW - timedelta(days=10)
    ctx.db.flush()
    old_id, keep_ids = old.id, {recent_read.id, unread.id}
    ns.cleanup_read(ctx.db, now=NOW)
    remaining = {n_id for (n_id,) in ctx.db.query(Notification.id).filter(Notification.user_id == ctx.laura.id)}
    assert old_id not in remaining
    assert keep_ids <= remaining


@pytest.mark.parametrize("url, expected", [
    ("/properties/1", "/properties/1"),
    ("//evil.example.com", "/notifications"),
    ("https://evil.example.com", "/notifications"),
    (None, "/notifications"),
])
def test_redireccion_solo_interna(url, expected):
    assert ns.safe_redirect_url(url) == expected


# ---------------------------------------------------------------------------
# Eventos
# ---------------------------------------------------------------------------

def _prop(ctx, company, agent):
    from app.models.property import Property
    prop = Property(title="PYTEST-NOTIF PROP", company_id=company.id, agent_id=agent.id)
    ctx.db.add(prop)
    ctx.db.flush()
    return prop


def _visit(ctx, prop, agent, companion=None):
    from app.models.property_visit import PropertyVisit
    visit = PropertyVisit(property_id=prop.id, visitor_name="PYTEST", agent_id=agent.id,
                          companion_agent_id=companion.id if companion else None)
    ctx.db.add(visit)
    ctx.db.flush()
    ctx.db.refresh(visit)
    return visit


def test_visita_de_otro_agente_avisa_al_captador(ctx):
    prop = _prop(ctx, ctx.moyza, ctx.laura_agent)
    visit = _visit(ctx, prop, ctx.carlos_agent)
    created = ns.notify_visit_created(ctx.db, visit, actor=ctx.carlos)
    assert [(n.user_id, n.kind) for n in created] == [(ctx.laura.id, NotificationKind.VISIT_ON_MY_PROPERTY)]
    assert created[0].title == "PYTEST-NOTIF CARLOS visitó tu inmueble"
    assert created[0].company_id == ctx.moyza.id


def test_visita_con_acompanante_y_captador_presente(ctx):
    prop = _prop(ctx, ctx.moyza, ctx.laura_agent)
    # Carlos visita con Laura (la captadora) de acompañante: solo "acompañante"
    visit = _visit(ctx, prop, ctx.carlos_agent, companion=ctx.laura_agent)
    created = ns.notify_visit_created(ctx.db, visit, actor=ctx.carlos)
    assert [(n.user_id, n.kind) for n in created] == [(ctx.laura.id, NotificationKind.VISIT_AS_COMPANION)]


def test_visita_propia_no_avisa_a_nadie(ctx):
    prop = _prop(ctx, ctx.moyza, ctx.laura_agent)
    visit = _visit(ctx, prop, ctx.laura_agent)
    assert ns.notify_visit_created(ctx.db, visit, actor=ctx.laura) == []


def test_visita_completada_y_envio_fallido(ctx):
    prop = _prop(ctx, ctx.moyza, ctx.laura_agent)
    visit = _visit(ctx, prop, ctx.carlos_agent, companion=ctx.laura_agent)
    # Carlos finaliza: solo se avisa a Laura (acompañante); nunca al actor
    done = ns.notify_visit_completed(ctx.db, visit, actor=ctx.carlos, sent=True)
    assert [n.user_id for n in done] == [ctx.laura.id]
    # El fallo de WhatsApp va al agente principal (aquí, sin actor: lo recibe Carlos)
    failed = ns.notify_visit_sheet_failed(ctx.db, visit, actor=None)
    assert [(n.user_id, n.kind) for n in failed] == [(ctx.carlos.id, NotificationKind.VISIT_SHEET_SEND_FAILED)]


def test_observacion_del_admin(ctx):
    from app.services.dashboard_service import DashboardService
    period = DashboardService.period("WEEKLY", "", now=NOW)
    created = ns.notify_admin_note(ctx.db, agent=ctx.laura_agent, company_id=ctx.moes.id, period=period, actor=ctx.admin)
    assert len(created) == 1
    assert created[0].company_id == ctx.moes.id
    assert created[0].url == f"/dashboard?period_type=WEEKLY&period_start={period.start_str}"


def test_job_de_seguimientos_uno_por_alerta_y_dia(ctx):
    from app.models.alert_follow_up import AlertFollowUp
    from app.models.property_alert import PropertyAlert

    prop = _prop(ctx, ctx.moyza, ctx.laura_agent)
    alert = PropertyAlert(property_id=prop.id, agent_id=ctx.laura_agent.id, lead_name="PYTEST COMPRADOR",
                          created_by=ctx.admin.id, status="IN_PROGRESS")
    closed = PropertyAlert(property_id=prop.id, agent_id=ctx.laura_agent.id, lead_name="PYTEST CERRADA",
                           created_by=ctx.admin.id, status="COMPLETED")
    ctx.db.add_all([alert, closed])
    ctx.db.flush()
    for a in (alert, closed):
        ctx.db.add(AlertFollowUp(alert_id=a.id, action_type="CONTACTADO", created_by=ctx.admin.id,
                                 created_at=NOW - timedelta(days=2), next_action_date=NOW - timedelta(days=1)))
    ctx.db.flush()

    ns.run_follow_up_due(ctx.db, now=NOW)
    ns.run_follow_up_due(ctx.db, now=NOW + timedelta(hours=1))   # mismo día: no repite

    mine = ctx.db.query(Notification).filter(
        Notification.user_id == ctx.laura.id, Notification.kind == NotificationKind.FOLLOW_UP_DUE
    ).all()
    assert len(mine) == 1
    assert mine[0].entity_id == alert.id
    assert mine[0].title == "Seguimiento vencido · PYTEST COMPRADOR"
