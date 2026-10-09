"""
Tests del servicio del Inicio (PLAN_DASHBOARD_INICIO.md).

- Unitarios (sin base de datos): período semana / mes / año, normalización
  al inicio del período, navegación y `show_next`; ranking y semáforo.
- Con base de datos (se omiten si no hay conexión), en una transacción que
  se deshace al terminar: KPIs con delta y objetivo, % global y puesto,
  hojas de visita por participación, tendencia y agenda.

Ejecución dentro del contenedor:
    docker exec moyza_backend python -m pytest tests/test_dashboard_service.py -q
"""
from datetime import datetime, timedelta

import pytest

from app.services.dashboard_service import DashboardService


NOW = datetime(2026, 10, 8, 10, 30)   # jueves


# ---------------------------------------------------------------------------
# Período (fase 1)
# ---------------------------------------------------------------------------

class TestPeriod:

    def test_por_defecto_es_la_semana_en_curso(self):
        p = DashboardService.period(now=NOW)
        assert p.period_type == "WEEKLY"
        assert p.start == datetime(2026, 10, 5)
        assert p.end == datetime(2026, 10, 11, 23, 59, 59)
        assert p.is_current and not p.show_next

    def test_semana_se_normaliza_al_lunes(self):
        p = DashboardService.period("WEEKLY", "2026-10-01", now=NOW)
        assert p.start == datetime(2026, 9, 28)
        assert not p.is_current
        assert p.show_next
        assert p.next_start == datetime(2026, 10, 5)

    def test_mes_se_normaliza_al_dia_1(self):
        p = DashboardService.period("MONTHLY", "2026-02-17", now=NOW)
        assert p.start == datetime(2026, 2, 1)
        assert p.end == datetime(2026, 2, 28, 23, 59, 59)
        assert p.label == "Febrero 2026"
        assert p.show_next

    def test_mes_en_curso_no_navega_al_futuro(self):
        p = DashboardService.period("MONTHLY", "", now=NOW)
        assert p.start == datetime(2026, 10, 1)
        assert p.is_current and not p.show_next

    def test_anio(self):
        p = DashboardService.period("YEARLY", "2025-07-01", now=NOW)
        assert p.start == datetime(2025, 1, 1)
        assert p.show_next and not p.is_current

    @pytest.mark.parametrize("period_type, start", [("DAILY", ""), ("", "x"), ("WEEKLY", "2026-99-01")])
    def test_valores_invalidos_vuelven_a_la_semana_en_curso(self, period_type, start):
        p = DashboardService.period(period_type, start, now=NOW)
        if period_type in ("DAILY", ""):
            assert p.period_type == "WEEKLY"
        assert p.start == datetime(2026, 10, 5)

    def test_fecha_futura_se_normaliza_y_no_ofrece_siguiente(self):
        p = DashboardService.period("WEEKLY", "2026-10-30", now=NOW)
        # Una semana futura se muestra, pero no ofrece seguir avanzando
        assert p.start == datetime(2026, 10, 26)
        assert not p.show_next

    def test_periodo_anterior(self):
        p = DashboardService.period("MONTHLY", "2026-01-10", now=NOW)
        prev = DashboardService.previous_period(p, now=NOW)
        assert prev.start == datetime(2025, 12, 1)
        assert prev.end == datetime(2025, 12, 31, 23, 59, 59)
        assert not prev.is_current


# ---------------------------------------------------------------------------
# Unitarios: ranking y semáforo
# ---------------------------------------------------------------------------

def test_ranking_sin_nombres_y_empates():
    completions = {1: 80, 2: 50, 3: 80, 4: None}
    assert DashboardService.ranking(1, completions) == {"position": 1, "total": 3}
    assert DashboardService.ranking(2, completions) == {"position": 3, "total": 3}
    # Sin % propio o único con objetivos: no hay puesto
    assert DashboardService.ranking(4, completions) is None
    assert DashboardService.ranking(1, {1: 80, 2: None}) is None


@pytest.mark.parametrize("pct, tone", [(None, "gray"), (0, "red"), (59, "red"), (60, "amber"), (99, "amber"), (100, "green"), (180, "green")])
def test_semaforo(pct, tone):
    from app.services.dashboard_service import semaphore
    assert semaphore(pct) == tone


# ---------------------------------------------------------------------------
# Base de datos (transacción externa deshecha al terminar)
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
    """MOYZA y MOES, un usuario para `created_by` y dos agentes de MOYZA (uno también en MOES)."""
    from types import SimpleNamespace
    from app.models.agent import Agent
    from app.models.company import Company
    from app.models.user import User

    moyza = db.query(Company).filter_by(code="MOYZA").one()
    moes = db.query(Company).filter_by(code="MOES").one()
    user = db.query(User).order_by(User.id).first()
    if user is None:
        pytest.skip("Sin usuarios en la base de datos")

    laura = Agent(name="PYTEST-DASH LAURA", email="pytest.dash.laura@example.com")
    carlos = Agent(name="PYTEST-DASH CARLOS", email="pytest.dash.carlos@example.com")
    laura.companies.extend([moyza, moes])
    carlos.companies.append(moyza)
    db.add_all([laura, carlos])
    db.flush()
    return SimpleNamespace(db=db, moyza=moyza, moes=moes, user=user, laura=laura, carlos=carlos)


def _prop(ctx, company, agent, business_type="Venta", entry=None, title="PYTEST-DASH PROP"):
    from app.models.property import Property
    prop = Property(title=title, company_id=company.id, agent_id=agent.id,
                    business_type=business_type, market_entry_date=entry or datetime(2020, 1, 1),
                    status="Activa")
    ctx.db.add(prop)
    ctx.db.flush()
    return prop


def _visit(ctx, prop, agent, created_at, companion=None):
    from app.models.property_visit import PropertyVisit
    visit = PropertyVisit(property_id=prop.id, visitor_name="PYTEST", agent_id=agent.id,
                          companion_agent_id=companion.id if companion else None, created_at=created_at)
    ctx.db.add(visit)
    ctx.db.flush()
    return visit


def _target(ctx, agent, company, period, **values):
    from app.models.agent_performance_target import AgentPerformanceTarget
    ctx.db.add(AgentPerformanceTarget(agent_id=agent.id, company_id=company.id, period_type=period.period_type,
                                      period_start=period.start, created_by=ctx.user.id, **values))
    ctx.db.flush()


def test_kpis_delta_objetivo_y_ranking(ctx):
    svc = DashboardService(ctx.db, ctx.moyza.id)
    week = svc.period("WEEKLY", "", now=NOW)
    prev = svc.previous_period(week, now=NOW)

    # Esta semana: 2 captaciones de Laura (venta + alquiler), 1 la semana anterior
    _prop(ctx, ctx.moyza, ctx.laura, "Venta", entry=week.start + timedelta(days=1))
    _prop(ctx, ctx.moyza, ctx.laura, "Alquiler", entry=week.start + timedelta(days=2))
    _prop(ctx, ctx.moyza, ctx.laura, "Venta", entry=prev.start + timedelta(days=1))
    # En MOES no cuenta en MOYZA
    _prop(ctx, ctx.moes, ctx.laura, "Venta", entry=week.start + timedelta(days=1))
    # Carlos: 1 captación
    _prop(ctx, ctx.moyza, ctx.carlos, "Venta", entry=week.start + timedelta(days=1))

    _target(ctx, ctx.laura, ctx.moyza, week, target_captaciones_crm=4, target_bajadas=2)
    _target(ctx, ctx.carlos, ctx.moyza, week, target_captaciones_crm=1, target_bajadas=1)

    home = svc.agent_home(ctx.laura, week, now=NOW)
    kpis = {k.key: k for k in home["objective_kpis"] + home["activity_kpis"]}

    capt = kpis["captaciones_crm"]
    assert capt.value == 2 and capt.previous == 1 and capt.delta == 1
    assert capt.is_objective and capt.target == 4 and capt.pct == 50 and capt.tone == "red"
    assert capt.breakdown == {"venta": 1, "alquiler": 1, "otros": 0}
    # Cierres no es objetivo en semana: sin anillo ni tono
    assert not kpis["cierres"].is_objective and kpis["cierres"].tone == "gray"
    # % global = media(50, 0) = 25; Carlos = media(100, 0) = 50 -> Laura segunda de 2
    assert home["completion"] == 25
    assert home["ranking"] == {"position": 2, "total": 2}


def test_hojas_de_visita_por_participacion_y_tendencia(ctx):
    svc = DashboardService(ctx.db, ctx.moyza.id)
    week = svc.period("WEEKLY", "", now=NOW)
    prop = _prop(ctx, ctx.moyza, ctx.carlos)
    _visit(ctx, prop, ctx.laura, week.start + timedelta(hours=10), companion=ctx.carlos)
    _visit(ctx, prop, ctx.laura, week.start - timedelta(days=3))   # semana anterior

    metrics = svc.team_metrics([ctx.laura.id, ctx.carlos.id], week)
    assert metrics[ctx.laura.id]["hojas_visita"] == 1
    assert metrics[ctx.carlos.id]["hojas_visita"] == 1

    trend = svc.agent_trend(ctx.laura, week, now=NOW)
    visits = trend.series[0].data
    assert len(visits) == 8
    assert visits[-1] == 1 and visits[-2] == 1


def test_agenda_proxima_accion_vencida_y_sin_respuesta(ctx):
    from app.models.alert_follow_up import AlertFollowUp
    from app.models.property_alert import PropertyAlert

    svc = DashboardService(ctx.db, ctx.moyza.id)
    prop = _prop(ctx, ctx.moyza, ctx.laura)

    def alert(status="IN_PROGRESS", read=True):
        a = PropertyAlert(property_id=prop.id, agent_id=ctx.laura.id, lead_name="PYTEST", created_by=ctx.user.id,
                          status=status, read_at=NOW if read else None, created_at=NOW - timedelta(days=10))
        ctx.db.add(a)
        ctx.db.flush()
        return a

    due = alert()
    # Un seguimiento antiguo con fecha vencida que ya no es el último no cuenta
    ctx.db.add(AlertFollowUp(alert_id=due.id, action_type="CONTACTADO", created_by=ctx.user.id,
                             created_at=NOW - timedelta(days=5), next_action_date=NOW - timedelta(days=4)))
    ctx.db.flush()
    ctx.db.add(AlertFollowUp(alert_id=due.id, action_type="CALIFICADO", created_by=ctx.user.id,
                             created_at=NOW - timedelta(days=2), next_action_date=NOW - timedelta(days=1)))
    future = alert()
    ctx.db.add(AlertFollowUp(alert_id=future.id, action_type="CONTACTADO", created_by=ctx.user.id,
                             created_at=NOW - timedelta(days=1), next_action_date=NOW + timedelta(days=3)))
    silent = alert()
    ctx.db.add(AlertFollowUp(alert_id=silent.id, action_type="SIN_RESPUESTA", created_by=ctx.user.id,
                             created_at=NOW - timedelta(days=4)))
    alert(status="PENDING", read=False)
    ctx.db.flush()

    agenda = svc.agenda(ctx.laura, now=NOW)
    assert agenda["due_total"] == 1
    assert agenda["due"][0]["alert_id"] == due.id
    assert agenda["due"][0]["overdue"] is True
    assert agenda["unread"] == 1
    assert agenda["no_response"] == 1
