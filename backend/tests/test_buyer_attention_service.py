"""
Compradores que requieren atención en horas hábiles (PLAN_ALERTAS_DIAS_HABILES.md §2.2, fase 2).

- Unitarios (sin base de datos, alertas de mentira): R1 «sin gestión» con fin
  de semana y lunes festivo por medio, R2 «sin avance» solo en Primera
  llamada con «sin respuesta» repetidos, reasignación que arranca de cero,
  nota REASIGNADA que no cuenta, una fila por alerta y alertas cerradas.
- Con base de datos (transacción que se deshace al terminar): la consulta
  vigila PENDING e IN_PROGRESS, deja fuera las cerradas, aísla por empresa y
  agente, y el envoltorio `get_pending_buyers_by_agent` conserva su forma.

    docker exec moyza_backend python -m pytest tests/test_buyer_attention_service.py -q
"""
from datetime import datetime
from itertools import count
from types import SimpleNamespace

import pytest

from app.core import business_calendar as bc
from app.core.constants import AlertStatus
from app.services import buyer_attention_service as svc
from app.services.buyer_attention_service import RULE_NO_ACTION
from app.services.buyer_attention_service import RULE_STAGE_STALL


def L(*args) -> datetime:
    """Hora local de Madrid -> UTC naive."""
    return bc.to_utc(datetime(*args))


_ids = count(1)


def _fu(action_type, when):
    return SimpleNamespace(id=next(_ids), action_type=action_type, created_at=when)


def _alert(assigned, follow_ups=(), status=AlertStatus.IN_PROGRESS, created=None, agent_id=1):
    return SimpleNamespace(
        id=next(_ids), status=status, agent_id=agent_id, company_id=1,
        created_at=created or assigned, assigned_at=assigned,
        follow_ups=list(follow_ups), lead_name="Comprador", lead_phone=None,
    )


def _eval(alert, now):
    return svc.evaluate_alert(alert, now=now, no_action_hours=48, stall_hours=48)


# ---------------------------------------------------------------------------
# R1 · Sin gestión
# ---------------------------------------------------------------------------

def test_r1_con_fin_de_semana_por_medio():
    alert = _alert(L(2026, 10, 16, 12, 0))   # viernes 12:00
    assert _eval(alert, L(2026, 10, 19, 12, 0)) is None          # lunes: 24 h hábiles
    assert _eval(alert, L(2026, 10, 20, 11, 59)) is None
    item = _eval(alert, L(2026, 10, 20, 12, 0))                  # martes 12:00
    assert item.rule == RULE_NO_ACTION
    assert bc.to_madrid(item.due_at) == datetime(2026, 10, 20, 12, 0)
    assert item.due_label == "martes 20/10 a las 12:00"
    assert item.text == "2 d hábiles sin gestión"
    assert item.badge == "Sin gestión · 2 d hábiles"


def test_r1_con_lunes_festivo():
    alert = _alert(L(2026, 10, 30, 12, 0))   # viernes; lunes 2/11 festivo
    assert _eval(alert, L(2026, 11, 3, 12, 0)) is None
    assert _eval(alert, L(2026, 11, 4, 12, 0)).rule == RULE_NO_ACTION


def test_abrir_la_alerta_no_la_silencia():
    # PENDING e IN_PROGRESS se vigilan igual
    for status in (AlertStatus.PENDING, AlertStatus.IN_PROGRESS):
        assert _eval(_alert(L(2026, 10, 13, 9, 0), status=status), L(2026, 10, 16, 9, 0)) is not None


def test_alerta_cerrada_no_tiene_relojes():
    for status in (AlertStatus.COMPLETED, AlertStatus.CANCELLED):
        alert = _alert(L(2026, 9, 1, 9, 0), status=status)
        assert svc.alert_clocks(alert, now=L(2026, 10, 16, 9, 0)) == []


def test_cualquier_gestion_real_reinicia_r1_incluido_sin_respuesta():
    alert = _alert(L(2026, 10, 13, 9, 0), [_fu("SIN_RESPUESTA", L(2026, 10, 15, 16, 0))])
    r1 = svc.alert_clocks(alert, now=L(2026, 10, 16, 11, 0), no_action_hours=48, stall_hours=48)[0]
    assert r1.rule == RULE_NO_ACTION
    assert r1.since == L(2026, 10, 15, 16, 0)
    assert not r1.overdue


def test_nota_reasignada_no_cuenta_como_gestion():
    alert = _alert(L(2026, 10, 13, 9, 0), [_fu("REASIGNADA", L(2026, 10, 15, 9, 0))])
    item = _eval(alert, L(2026, 10, 15, 9, 0))
    assert item.rule == RULE_NO_ACTION and item.since == L(2026, 10, 13, 9, 0)


def test_reasignada_arranca_de_cero():
    # Creada hace semanas, con gestión del agente anterior; reasignada el lunes 19 a las 9:00
    alert = _alert(
        L(2026, 10, 19, 9, 0),
        [_fu("CONTACTADO", L(2026, 9, 20, 10, 0)), _fu("REASIGNADA", L(2026, 10, 19, 9, 0))],
        status=AlertStatus.PENDING, created=L(2026, 9, 15, 10, 0),
    )
    assert _eval(alert, L(2026, 10, 20, 10, 0)) is None
    item = _eval(alert, L(2026, 10, 21, 9, 0))
    assert item.rule == RULE_NO_ACTION and item.since == L(2026, 10, 19, 9, 0)
    # La etapa del agente anterior tampoco cuenta: para el nuevo no tiene etapa y R2 corre
    rules = [c.rule for c in svc.alert_clocks(alert, now=L(2026, 10, 21, 9, 0))]
    assert rules == [RULE_NO_ACTION, RULE_STAGE_STALL]


# ---------------------------------------------------------------------------
# R2 · Sin avance (solo Primera llamada)
# ---------------------------------------------------------------------------

def test_r2_con_sin_respuesta_repetidos():
    alert = _alert(L(2026, 10, 13, 9, 0), [
        _fu("SIN_RESPUESTA", L(2026, 10, 14, 10, 0)),
        _fu("SIN_RESPUESTA", L(2026, 10, 15, 10, 0)),
        _fu("SIN_RESPUESTA", L(2026, 10, 16, 10, 0)),
    ])
    item = _eval(alert, L(2026, 10, 19, 9, 0))
    # R1 no salta (última gestión el viernes 10:00: 23 h hábiles); R2 sí
    assert item.rule == RULE_STAGE_STALL
    assert item.since == L(2026, 10, 13, 9, 0)
    assert item.stage_label == "Primera Llamada"
    assert item.text == "4 días hábiles sin pasar de Primera Llamada"
    assert item.badge == "Sin avance · 4 d hábiles en Primera Llamada"


def test_r2_cuenta_desde_la_primera_llamada():
    alert = _alert(L(2026, 10, 13, 9, 0), [
        _fu("PRIMERA_LLAMADA", L(2026, 10, 13, 10, 0)),
        _fu("SIN_RESPUESTA", L(2026, 10, 14, 10, 0)),
        _fu("PRIMERA_LLAMADA", L(2026, 10, 15, 9, 0)),   # repetirla no avanza
        _fu("SIN_RESPUESTA", L(2026, 10, 15, 16, 0)),
    ])
    item = _eval(alert, L(2026, 10, 16, 11, 0))
    assert item.rule == RULE_STAGE_STALL
    assert item.since == L(2026, 10, 13, 10, 0)


def test_r2_no_aplica_pasada_la_primera_etapa():
    alert = _alert(L(2026, 10, 13, 9, 0), [
        _fu("PRIMERA_LLAMADA", L(2026, 10, 13, 10, 0)),
        _fu("CONTACTADO", L(2026, 10, 13, 12, 0)),
        _fu("SIN_RESPUESTA", L(2026, 10, 14, 10, 0)),
    ])
    clocks = svc.alert_clocks(alert, now=L(2026, 10, 20, 9, 0))
    assert [c.rule for c in clocks] == [RULE_NO_ACTION]
    assert _eval(alert, L(2026, 10, 20, 9, 0)).rule == RULE_NO_ACTION


def test_propiedad_asociada_reinicia_r1_pero_no_r2():
    alert = _alert(L(2026, 10, 13, 9, 0), [_fu("PROPIEDAD_ASOCIADA", L(2026, 10, 15, 9, 0))])
    item = _eval(alert, L(2026, 10, 15, 10, 0))
    assert item.rule == RULE_STAGE_STALL


def test_una_sola_fila_con_la_causa_mas_grave():
    # Sin ninguna gestión vencen las dos a la vez: se muestra R1
    alert = _alert(L(2026, 10, 13, 9, 0))
    clocks = svc.alert_clocks(alert, now=L(2026, 10, 16, 9, 0), no_action_hours=48, stall_hours=48)
    assert [c.overdue for c in clocks] == [True, True]
    assert _eval(alert, L(2026, 10, 16, 9, 0)).rule == RULE_NO_ACTION
    assert list(svc.evaluate_alerts([alert], now=L(2026, 10, 16, 9, 0)).values())[0].rule == RULE_NO_ACTION


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
    from app.models.user import User

    moyza = db.query(Company).filter_by(code="MOYZA").one()
    moes = db.query(Company).filter_by(code="MOES").one()
    ana = Agent(name="PYTEST-ATN ANA", email="pytest.atn.ana@example.com")
    bea = Agent(name="PYTEST-ATN BEA", email="pytest.atn.bea@example.com")
    ana.companies.extend([moyza, moes])
    bea.companies.append(moyza)
    admin = User(email="pytest.atn.admin@example.com", full_name="Admin", hashed_password="x", is_active=True)
    db.add_all([ana, bea, admin])
    db.flush()
    return SimpleNamespace(db=db, moyza=moyza, moes=moes, ana=ana, bea=bea, admin=admin)


def _db_alert(ctx, agent, company, assigned, status=AlertStatus.IN_PROGRESS, name="PYTEST-ATN Comprador"):
    from app.models.property_alert import PropertyAlert
    alert = PropertyAlert(company_id=company.id, agent_id=agent.id, lead_name=name, lead_phone="600000000",
                          status=status, created_by=ctx.admin.id, created_at=assigned, assigned_at=assigned,
                          origin="search", business_type="Venta")
    ctx.db.add(alert)
    ctx.db.flush()
    return alert


def _db_follow_up(ctx, alert, action_type, when):
    from app.models.alert_follow_up import AlertFollowUp
    ctx.db.add(AlertFollowUp(alert_id=alert.id, action_type=action_type, created_at=when, created_by=ctx.admin.id))
    ctx.db.flush()


NOW = L(2026, 10, 20, 12, 0)   # martes


def _ids_for(items, agents):
    agent_ids = {a.id for a in agents}
    return {i.alert.id for i in items if i.alert.agent_id in agent_ids}


def test_consulta_vigila_abiertas_y_aisla(ctx):
    pending = _db_alert(ctx, ctx.ana, ctx.moyza, L(2026, 10, 13, 9, 0), status=AlertStatus.PENDING)
    opened = _db_alert(ctx, ctx.ana, ctx.moyza, L(2026, 10, 13, 9, 0))
    closed = _db_alert(ctx, ctx.ana, ctx.moyza, L(2026, 10, 13, 9, 0), status=AlertStatus.COMPLETED)
    recent = _db_alert(ctx, ctx.ana, ctx.moyza, L(2026, 10, 19, 9, 0))
    managed = _db_alert(ctx, ctx.ana, ctx.moyza, L(2026, 10, 13, 9, 0))
    _db_follow_up(ctx, managed, "PRIMERA_LLAMADA", L(2026, 10, 13, 10, 0))
    _db_follow_up(ctx, managed, "CONTACTADO", L(2026, 10, 19, 10, 0))
    in_moes = _db_alert(ctx, ctx.ana, ctx.moes, L(2026, 10, 13, 9, 0))
    of_bea = _db_alert(ctx, ctx.bea, ctx.moyza, L(2026, 10, 13, 9, 0))

    agents = (ctx.ana, ctx.bea)
    everything = _ids_for(svc.find_buyers_needing_attention(ctx.db, now=NOW), agents)
    assert everything == {pending.id, opened.id, in_moes.id, of_bea.id}
    assert closed.id not in everything and recent.id not in everything and managed.id not in everything

    moyza = _ids_for(svc.find_buyers_needing_attention(ctx.db, company_id=ctx.moyza.id, now=NOW), agents)
    assert moyza == {pending.id, opened.id, of_bea.id}
    ana_moes = svc.find_buyers_needing_attention(ctx.db, company_id=ctx.moes.id, agent_id=ctx.ana.id, now=NOW)
    assert [i.alert.id for i in ana_moes] == [in_moes.id]


def test_sin_respuesta_en_bd_da_r2(ctx):
    alert = _db_alert(ctx, ctx.ana, ctx.moyza, L(2026, 10, 13, 9, 0))
    for day in (14, 15, 16, 19):
        _db_follow_up(ctx, alert, "SIN_RESPUESTA", L(2026, 10, day, 10, 0))
    [item] = svc.find_buyers_needing_attention(ctx.db, agent_id=ctx.ana.id, now=NOW)
    assert item.rule == RULE_STAGE_STALL and item.stage_label == "Primera Llamada"


def test_envoltorio_conserva_la_forma(ctx):
    from app.services.buyer_reminder_service import REMINDER_STATUSES
    from app.services.buyer_reminder_service import get_pending_buyers_by_agent

    assert set(REMINDER_STATUSES) == {AlertStatus.PENDING, AlertStatus.IN_PROGRESS}
    alert = _db_alert(ctx, ctx.ana, ctx.moyza, L(2026, 10, 13, 9, 0))
    pending = get_pending_buyers_by_agent(ctx.db, 48, now=NOW)
    [row] = pending[(ctx.ana.id, ctx.moyza.id)]
    assert row["alert_id"] == alert.id
    assert row["buyer_name"] == "PYTEST-ATN Comprador"
    assert row["alert_status"] == AlertStatus.IN_PROGRESS
    assert row["last_action_at"] == L(2026, 10, 13, 9, 0)
    assert row["hours_elapsed"] == 123   # mar 15 + mié 24 + jue 24 + vie 24 + lun 24 + mar 12
    assert row["rule"] == RULE_NO_ACTION and row["stage_label"] is None
    assert row["due_at"] == L(2026, 10, 15, 9, 0)
