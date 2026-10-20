"""
Compradores que requieren atención en horas hábiles.

PLAN_ALERTAS_DIAS_HABILES.md §2.2, ajustado por PLAN_RECORDATORIO_SIN_RESPUESTA.md §3.1:
R1 «sin gestión» (se mantiene) y R3 «volver a llamar» (nueva, con prioridad);
la antigua R2 «sin avance de Primera llamada» ya no existe.

- Unitarios (sin base de datos, alertas de mentira): R1 con fin de semana y
  lunes festivo; R3 con 1er, 2º y 3er intento, el 4º cae en R1 a las 48 h, un
  seguimiento posterior la resuelve, la reasignación reinicia los intentos,
  fin de semana y festivo de Jaén por medio; alertas cerradas; una sola regla
  por alerta.
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
from app.services.buyer_attention_service import RULE_CALLBACK
from app.services.buyer_attention_service import RULE_NO_ACTION


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


THRESHOLDS = dict(no_action_hours=48, callback_hours=24, max_attempts=3)


def _eval(alert, now):
    return svc.evaluate_alert(alert, now=now, **THRESHOLDS)


def _clock(alert, now):
    return svc.alert_clock(alert, now=now, **THRESHOLDS)


# ---------------------------------------------------------------------------
# R1 · Sin gestión (sin cambios)
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
    assert (item.attempts, item.max_attempts, item.is_last_attempt) == (0, 0, False)
    assert item.tone == "amber"


def test_r1_con_lunes_festivo():
    alert = _alert(L(2026, 10, 30, 12, 0))   # viernes; lunes 2/11 festivo
    assert _eval(alert, L(2026, 11, 3, 12, 0)) is None
    assert _eval(alert, L(2026, 11, 4, 12, 0)).rule == RULE_NO_ACTION


def test_abrir_la_alerta_no_la_silencia():
    # PENDING e IN_PROGRESS se vigilan igual
    for status in (AlertStatus.PENDING, AlertStatus.IN_PROGRESS):
        assert _eval(_alert(L(2026, 10, 13, 9, 0), status=status), L(2026, 10, 16, 9, 0)) is not None


def test_alerta_cerrada_no_tiene_reloj():
    for status in (AlertStatus.COMPLETED, AlertStatus.CANCELLED):
        alert = _alert(L(2026, 9, 1, 9, 0), [_fu("SIN_RESPUESTA", L(2026, 9, 2, 9, 0))], status=status)
        assert _clock(alert, L(2026, 10, 16, 9, 0)) is None
        assert _eval(alert, L(2026, 10, 16, 9, 0)) is None


def test_r1_con_otra_gestion_como_ultimo_seguimiento():
    # Contactado tras un «Sin respuesta»: ya no es R3, R1 desde Contactado
    alert = _alert(L(2026, 10, 13, 9, 0), [
        _fu("SIN_RESPUESTA", L(2026, 10, 13, 10, 0)),
        _fu("CONTACTADO", L(2026, 10, 14, 10, 0)),
    ])
    clock = _clock(alert, L(2026, 10, 15, 11, 0))
    assert clock.rule == RULE_NO_ACTION and not clock.overdue
    assert clock.since == L(2026, 10, 14, 10, 0)
    assert _eval(alert, L(2026, 10, 16, 10, 0)).rule == RULE_NO_ACTION


def test_perfil_guardado_y_propiedad_asociada_reinician_r1():
    for action in ("PERFIL_GUARDADO", "PROPIEDAD_ASOCIADA"):
        alert = _alert(L(2026, 10, 13, 9, 0), [_fu(action, L(2026, 10, 15, 9, 0))])
        assert _eval(alert, L(2026, 10, 16, 9, 0)) is None
        assert _eval(alert, L(2026, 10, 19, 9, 0)).rule == RULE_NO_ACTION


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


# ---------------------------------------------------------------------------
# R3 · Volver a llamar
# ---------------------------------------------------------------------------

def test_r3_primer_intento_viernes_vence_el_lunes():
    alert = _alert(L(2026, 10, 13, 9, 0), [_fu("SIN_RESPUESTA", L(2026, 10, 16, 17, 0))])   # viernes 17:00
    clock = _clock(alert, L(2026, 10, 19, 16, 59))
    assert clock.rule == RULE_CALLBACK and not clock.overdue
    assert bc.to_madrid(clock.due_at) == datetime(2026, 10, 19, 17, 0)                      # lunes 17:00
    assert _eval(alert, L(2026, 10, 19, 16, 59)) is None
    item = _eval(alert, L(2026, 10, 19, 17, 0))
    assert item.rule == RULE_CALLBACK
    assert (item.attempts, item.max_attempts, item.is_last_attempt) == (1, 3, False)
    assert item.since == L(2026, 10, 16, 17, 0)
    assert item.text == "Intento 1 de 3 sin respuesta · vuelve a llamar"
    assert item.badge == "Volver a llamar · intento 1 de 3"
    assert item.tone == "amber"


def test_r3_con_lunes_festivo_vence_el_martes():
    alert = _alert(L(2026, 10, 26, 9, 0), [_fu("SIN_RESPUESTA", L(2026, 10, 30, 17, 0))])   # viernes; lunes 2/11 festivo
    assert _eval(alert, L(2026, 11, 2, 17, 0)) is None
    assert _eval(alert, L(2026, 11, 3, 16, 59)) is None
    item = _eval(alert, L(2026, 11, 3, 17, 0))
    assert item.rule == RULE_CALLBACK
    assert bc.to_madrid(item.due_at) == datetime(2026, 11, 3, 17, 0)


def test_r3_segundo_y_tercer_intento():
    first, second, third = L(2026, 10, 13, 10, 0), L(2026, 10, 14, 11, 0), L(2026, 10, 15, 12, 0)
    alert = _alert(L(2026, 10, 13, 9, 0), [_fu("SIN_RESPUESTA", first)])
    alert.follow_ups.append(_fu("SIN_RESPUESTA", second))
    item = _eval(alert, L(2026, 10, 15, 11, 0))
    assert item.attempts == 2 and item.since == second
    assert item.text == "Intento 2 de 3 sin respuesta · vuelve a llamar"

    alert.follow_ups.append(_fu("SIN_RESPUESTA", third))
    assert _eval(alert, L(2026, 10, 16, 11, 59)) is None                 # el tercero vence el viernes 12:00
    item = _eval(alert, L(2026, 10, 16, 12, 0))
    assert (item.attempts, item.is_last_attempt) == (3, True)
    assert item.text == "Tercer intento sin respuesta · cierra la alerta (Sin interés)"
    assert item.badge == "Volver a llamar · intento 3 de 3"
    assert item.tone == "red"


def test_r3_cuarto_sin_respuesta_cae_en_r1_a_las_48_horas():
    follow_ups = [_fu("SIN_RESPUESTA", L(2026, 10, d, 10, 0)) for d in (12, 13, 14, 15)]
    alert = _alert(L(2026, 10, 12, 9, 0), follow_ups)
    clock = _clock(alert, L(2026, 10, 16, 10, 0))
    assert clock.rule == RULE_NO_ACTION and not clock.overdue           # 24 h: ya no hay R3
    assert clock.since == L(2026, 10, 15, 10, 0)
    item = _eval(alert, L(2026, 10, 19, 10, 0))                          # lunes: 48 h hábiles
    assert item.rule == RULE_NO_ACTION and item.attempts == 0


def test_r3_seguimiento_posterior_la_resuelve():
    alert = _alert(L(2026, 10, 13, 9, 0), [_fu("SIN_RESPUESTA", L(2026, 10, 13, 10, 0))])
    assert _eval(alert, L(2026, 10, 14, 10, 0)).rule == RULE_CALLBACK
    alert.follow_ups.append(_fu("CONTACTADO", L(2026, 10, 14, 10, 30)))
    assert _eval(alert, L(2026, 10, 14, 11, 0)) is None
    # Otro «Sin respuesta» abre el siguiente intento con su propio plazo
    alert.follow_ups.append(_fu("SIN_RESPUESTA", L(2026, 10, 14, 12, 0)))
    assert _eval(alert, L(2026, 10, 15, 11, 0)) is None
    assert _eval(alert, L(2026, 10, 15, 12, 0)).attempts == 2


def test_r3_reasignacion_reinicia_los_intentos():
    # Tres «Sin respuesta» del agente anterior y reasignada el lunes 19 a las 9:00
    alert = _alert(
        L(2026, 10, 19, 9, 0),
        [_fu("SIN_RESPUESTA", L(2026, 10, d, 10, 0)) for d in (13, 14, 15)]
        + [_fu("REASIGNADA", L(2026, 10, 19, 9, 0)), _fu("SIN_RESPUESTA", L(2026, 10, 19, 10, 0))],
        created=L(2026, 10, 12, 9, 0),
    )
    item = _eval(alert, L(2026, 10, 20, 10, 0))
    assert item.rule == RULE_CALLBACK and item.attempts == 1


def test_r3_sin_respuesta_en_viernes_no_vence_en_fin_de_semana():
    alert = _alert(L(2026, 10, 13, 9, 0), [_fu("SIN_RESPUESTA", L(2026, 10, 16, 9, 0))])
    assert _eval(alert, L(2026, 10, 18, 23, 0)) is None                  # domingo
    assert _eval(alert, L(2026, 10, 19, 9, 0)).rule == RULE_CALLBACK


def test_una_sola_regla_por_alerta():
    """R3 tiene prioridad aunque R1 también hubiera vencido."""
    # Asignada hace semanas sin tocar; un «Sin respuesta» antiguo: solo R3
    alert = _alert(L(2026, 9, 1, 9, 0), [_fu("SIN_RESPUESTA", L(2026, 9, 2, 9, 0))])
    now = L(2026, 10, 16, 9, 0)
    item = _eval(alert, now)
    assert item.rule == RULE_CALLBACK
    assert list(svc.evaluate_alerts([alert], now=now, **THRESHOLDS).values()) == [item]
    # Sin ninguna gestión: solo R1
    assert _eval(_alert(L(2026, 10, 13, 9, 0)), now).rule == RULE_NO_ACTION


def test_callback_state():
    assert svc.callback_state([]) == (0, None)
    last = _fu("SIN_RESPUESTA", L(2026, 10, 15, 9, 0))
    window = [_fu("SIN_RESPUESTA", L(2026, 10, 13, 9, 0)), _fu("CONTACTADO", L(2026, 10, 14, 9, 0)), last]
    assert svc.callback_state(window) == (2, last)
    assert svc.callback_state(window[:2]) == (0, None)


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
    _db_follow_up(ctx, managed, "SIN_RESPUESTA", L(2026, 10, 13, 10, 0))
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


def test_sin_respuesta_en_bd_da_r3_y_el_cuarto_r1(ctx):
    alert = _db_alert(ctx, ctx.ana, ctx.moyza, L(2026, 10, 13, 9, 0))
    for day in (14, 15, 16):
        _db_follow_up(ctx, alert, "SIN_RESPUESTA", L(2026, 10, day, 10, 0))
    [item] = svc.find_buyers_needing_attention(ctx.db, agent_id=ctx.ana.id, now=NOW)
    assert item.rule == RULE_CALLBACK and item.attempts == 3 and item.is_last_attempt
    # Cuarto «Sin respuesta» el lunes 10:00: R1 a las 48 h hábiles (miércoles 10:00)
    _db_follow_up(ctx, alert, "SIN_RESPUESTA", L(2026, 10, 19, 10, 0))
    ctx.db.expire(alert, ["follow_ups"])
    assert svc.find_buyers_needing_attention(ctx.db, agent_id=ctx.ana.id, now=NOW) == []
    [item] = svc.find_buyers_needing_attention(ctx.db, agent_id=ctx.ana.id, now=L(2026, 10, 21, 10, 0))
    assert item.rule == RULE_NO_ACTION


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
    assert row["rule"] == RULE_NO_ACTION and row["rule_label"] == "Sin gestión"
    assert row["attempts"] == 0 and row["is_last_attempt"] is False and row["tone"] == "amber"
    assert row["due_at"] == L(2026, 10, 15, 9, 0)
