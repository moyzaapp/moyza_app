"""
Tests para el scheduler de tareas automáticas.
"""
import pytest
from unittest.mock import Mock, patch
from datetime import datetime

from app.jobs.scheduler import check_automatic_reports


@pytest.fixture
def mock_db_session():
    """Mock de la sesión de base de datos."""
    with patch("app.jobs.scheduler.SessionLocal") as mock_session:
        yield mock_session


def test_check_automatic_reports_sin_propiedades(mock_db_session):
    """Verifica que funciona correctamente cuando no hay propiedades."""
    # Setup
    mock_db = Mock()
    mock_db_session.return_value = mock_db
    mock_db.query.return_value.filter.return_value.all.return_value = []

    # Execute
    check_automatic_reports()

    # Verify
    mock_db.query.assert_called_once()
    mock_db.close.assert_called_once()


def test_check_automatic_reports_con_propiedad_activa(mock_db_session):
    """Verifica la generación de informe para propiedad configurada."""
    # Setup
    mock_db = Mock()
    mock_db_session.return_value = mock_db

    # Crear mock de propiedad
    mock_property = Mock()
    mock_property.id = 1
    mock_property.name = "Test Property"
    mock_property.report_frequency = "MONTHLY"
    mock_property.report_day = datetime.now().day
    mock_property.report_hour = datetime.now().hour
    mock_property.auto_send_report = True
    mock_property.status = "ACTIVA"

    mock_db.query.return_value.filter.return_value.all.return_value = [mock_property]

    # Execute
    check_automatic_reports()

    # Verify
    mock_db.query.assert_called_once()
    mock_db.close.assert_called_once()


def test_check_automatic_reports_con_propiedad_inactiva(mock_db_session):
    """Verifica que no procesa propiedades con hora diferente."""
    # Setup
    mock_db = Mock()
    mock_db_session.return_value = mock_db

    # Crear mock de propiedad con hora diferente
    mock_property = Mock()
    mock_property.id = 1
    mock_property.name = "Test Property"
    mock_property.report_frequency = "MONTHLY"
    mock_property.report_day = datetime.now().day
    mock_property.report_hour = (datetime.now().hour + 1) % 24  # Hora diferente
    mock_property.auto_send_report = True
    mock_property.status = "ACTIVA"

    mock_db.query.return_value.filter.return_value.all.return_value = [mock_property]

    # Execute
    check_automatic_reports()

    # Verify - no debería generar informe
    mock_db.query.assert_called_once()
    mock_db.close.assert_called_once()


def test_check_automatic_reports_maneja_errores(mock_db_session):
    """Verifica que los errores se manejan correctamente."""
    # Setup
    mock_db = Mock()
    mock_db_session.return_value = mock_db
    mock_db.query.side_effect = Exception("Database error")

    # Execute - no debería lanzar excepción
    check_automatic_reports()

    # Verify
    mock_db.close.assert_called_once()


# ---------------------------------------------------------------------------
# Congelación de reportes de rendimiento (PLAN_RESULTADOS_COMERCIALES fase 3)
# Fechas fijas: no dependen del día en que se ejecuten los tests.
# ---------------------------------------------------------------------------

from app.jobs.scheduler import freeze_monthly_reports  # noqa: E402
from app.jobs.scheduler import freeze_weekly_reports  # noqa: E402
from app.jobs.scheduler import freeze_yearly_reports  # noqa: E402


@pytest.mark.parametrize("job, now, expected", [
    # Lunes 00:01 -> semana anterior completa
    (freeze_weekly_reports, datetime(2026, 10, 12, 0, 1),
     ("WEEKLY", datetime(2026, 10, 5), datetime(2026, 10, 11, 23, 59, 59))),
    # Semana que cruza el año
    (freeze_weekly_reports, datetime(2026, 1, 5, 0, 1),
     ("WEEKLY", datetime(2025, 12, 29), datetime(2026, 1, 4, 23, 59, 59))),
    (freeze_monthly_reports, datetime(2026, 10, 1, 0, 1),
     ("MONTHLY", datetime(2026, 9, 1), datetime(2026, 9, 30, 23, 59, 59))),
    # Enero congela diciembre del año anterior
    (freeze_monthly_reports, datetime(2026, 1, 1, 0, 1),
     ("MONTHLY", datetime(2025, 12, 1), datetime(2025, 12, 31, 23, 59, 59))),
    # Febrero bisiesto
    (freeze_monthly_reports, datetime(2028, 3, 1, 0, 1),
     ("MONTHLY", datetime(2028, 2, 1), datetime(2028, 2, 29, 23, 59, 59))),
    (freeze_yearly_reports, datetime(2027, 1, 1, 0, 1),
     ("YEARLY", datetime(2026, 1, 1), datetime(2026, 12, 31, 23, 59, 59))),
])
def test_freeze_congela_el_periodo_anterior(mock_db_session, job, now, expected):
    with patch(
        "app.services.performance_report_service.PerformanceReportService.freeze_all_for_period"
    ) as freeze_all:
        assert job(now=now) == expected[1:]

    freeze_all.assert_called_once_with(*expected)
    mock_db_session.return_value.close.assert_called_once()


def test_freeze_error_no_propaga(mock_db_session):
    with patch(
        "app.services.performance_report_service.PerformanceReportService.freeze_all_for_period",
        side_effect=Exception("DB caída"),
    ):
        assert freeze_yearly_reports(now=datetime(2027, 1, 1, 0, 1)) is None
    mock_db_session.return_value.close.assert_called_once()


def test_job_anual_registrado(monkeypatch):
    from app.jobs import scheduler as sched

    monkeypatch.setenv("WORKER_ID", "0")
    monkeypatch.setenv("WORKER_HEARTBEAT_ENABLED", "false")
    fake = Mock()
    with patch.object(sched, "scheduler", fake), patch.object(sched, "update_worker_heartbeat"):
        sched.start_scheduler()

    jobs = {c.kwargs["id"]: c for c in fake.add_job.call_args_list}
    yearly = jobs["freeze_yearly_reports"]
    assert yearly.args == (sched.freeze_yearly_reports, "cron")
    assert {k: yearly.kwargs[k] for k in ("month", "day", "hour", "minute")} == \
        {"month": 1, "day": 1, "hour": 0, "minute": 1}
    # Los jobs semanal y mensual siguen igual
    assert jobs["freeze_weekly_reports"].kwargs["day_of_week"] == "mon"
    assert jobs["freeze_monthly_reports"].kwargs["day"] == 1
    fake.start.assert_called_once()


@pytest.fixture
def db_connection():
    """Conexión con transacción externa: todo lo que congela el job se deshace."""
    from app.db.session import engine
    try:
        connection = engine.connect()
    except Exception as e:  # pragma: no cover - depende del entorno
        pytest.skip(f"Sin base de datos: {e}")
    transaction = connection.begin()
    yield connection
    transaction.rollback()
    connection.close()


def test_freeze_semanal_real_por_empresa(db_connection):
    """El job semanal congela, con fecha fija, un snapshot por empresa con su desglose."""
    from sqlalchemy.orm import Session

    from app.models.agent import Agent
    from app.models.agent_performance_report import AgentPerformanceReport
    from app.models.company import Company
    from app.models.property import Property
    from app.services.performance_report_service import PerformanceReportService

    def session():
        return Session(bind=db_connection, autoflush=False, join_transaction_mode="create_savepoint")

    db = session()
    moyza = db.query(Company).filter_by(code="MOYZA").one()
    moes = db.query(Company).filter_by(code="MOES").one()
    agent = Agent(name="PYTEST-FREEZE", email="pytest.freeze@example.com")
    agent.companies.extend([moyza, moes])
    db.add(agent)
    db.flush()
    db.add_all([
        Property(title="PYTEST-FREEZE V", company_id=moyza.id, agent_id=agent.id,
                 business_type="Venta", market_entry_date=datetime(2025, 3, 4)),
        Property(title="PYTEST-FREEZE A", company_id=moyza.id, agent_id=agent.id,
                 business_type="Alquiler", market_entry_date=datetime(2025, 3, 9, 23, 0)),
        Property(title="PYTEST-FREEZE MOES", company_id=moes.id, agent_id=agent.id,
                 business_type="Venta", market_entry_date=datetime(2025, 3, 5)),
        # Fuera de la semana (lunes siguiente)
        Property(title="PYTEST-FREEZE FUERA", company_id=moyza.id, agent_id=agent.id,
                 business_type="Venta", market_entry_date=datetime(2025, 3, 10)),
    ])
    db.commit()
    agent_id, moyza_id, moes_id = agent.id, moyza.id, moes.id
    expected_moyza = PerformanceReportService(db, moyza_id).calculate_metrics(
        agent_id, datetime(2025, 3, 3), datetime(2025, 3, 9, 23, 59, 59))
    db.close()

    with patch("app.jobs.scheduler.SessionLocal", session):
        freeze_weekly_reports(now=datetime(2025, 3, 10, 0, 1))

    db = session()
    reports = {
        r.company_id: r
        for r in db.query(AgentPerformanceReport).filter_by(agent_id=agent_id, period_type="WEEKLY")
    }
    assert set(reports) == {moyza_id, moes_id}
    r = reports[moyza_id]
    assert r.period_start == datetime(2025, 3, 3) and r.is_locked
    assert (r.captaciones_crm, r.captaciones_venta, r.captaciones_alquiler) == (2, 1, 1)
    assert PerformanceReportService.report_metrics(r) == expected_moyza
    assert reports[moes_id].captaciones_crm == 1
    db.close()
