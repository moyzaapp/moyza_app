"""
Cierres registrados a mano (PLAN_CIERRES_MANUALES_Y_DIRECCIONES.md, fase A).

La métrica "Cierres" cuenta los registros de `closings` (agente, empresa y
fecha de cierre del período) con desglose por su operación, y ya no los
seguimientos «Cerrado» de las alertas. Al registrar o borrar un cierre en un
mes o año congelado, `refresh_closings_snapshot` recalcula solo las columnas
de cierres de esos snapshots.

Con base de datos (se omiten si no hay conexión), dentro de una transacción
externa que se deshace al terminar (los commit del servicio solo cierran
savepoints): no dejan datos.

Ejecución dentro del contenedor:
    docker exec moyza_backend python -m pytest tests/test_closings_metric.py -q
"""
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.core.constants import PeriodType
from app.models.agent import Agent
from app.models.agent_performance_report import AgentPerformanceReport
from app.models.alert_follow_up import AlertFollowUp
from app.models.closing import Closing
from app.models.property import Property
from app.models.property_alert import PropertyAlert
from app.services.dashboard_service import DashboardService
from app.services.performance_report_service import PerformanceReportService


MARCH = (datetime(2025, 3, 1), datetime(2025, 3, 31, 23, 59, 59))
YEAR_2025 = (datetime(2025, 1, 1), datetime(2025, 12, 31, 23, 59, 59))


# ---------------------------------------------------------------------------
# Sin base de datos
# ---------------------------------------------------------------------------

def test_csv_de_cierres():
    from app.web.routes.commercial_results import METRIC_CSV_COLUMNS

    columns = METRIC_CSV_COLUMNS["cierres"]
    with_prop = {"date": date(2025, 3, 31), "kind": "venta", "notes": "Notaría",
                 "property_id": 7, "property_ref": "REF-7", "property_title": "Piso Centro", "property_city": "Jaén"}
    without = {"date": date(2025, 3, 1), "kind": "alquiler", "notes": None,
               "property_id": None, "property_ref": None, "property_title": None, "property_city": None}

    assert [header for header, _ in columns] == ["Fecha de cierre", "Operación", "Propiedad", "Ciudad", "Nota", "Enlace"]
    assert [value(with_prop) for _, value in columns] == [
        "31/03/2025", "Venta", "REF-7 · Piso Centro", "Jaén", "Notaría", "/properties/7",
    ]
    assert [value(without) for _, value in columns] == ["01/03/2025", "Alquiler", "", "", "", ""]


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
    """MOYZA y MOES, un usuario para `created_by`, Laura (en las dos) y Carlos (MOYZA)."""
    from app.models.company import Company
    from app.models.user import User

    moyza = db.query(Company).filter_by(code="MOYZA").one()
    moes = db.query(Company).filter_by(code="MOES").one()
    user = db.query(User).order_by(User.id).first()
    if user is None:
        pytest.skip("Sin usuarios en la base de datos")

    laura = Agent(name="PYTEST-CIERRES LAURA", email="pytest.cierres.laura@example.com")
    laura.companies.extend([moyza, moes])
    carlos = Agent(name="PYTEST-CIERRES CARLOS", email="pytest.cierres.carlos@example.com")
    carlos.companies.append(moyza)
    db.add_all([laura, carlos])
    db.flush()
    return SimpleNamespace(db=db, moyza=moyza, moes=moes, user=user, laura=laura, carlos=carlos)


def _prop(ctx, company, title="PYTEST-CIERRES PROP", business_type="Venta"):
    prop = Property(title=title, referencia="PYT-CIE", company_id=company.id, agent_id=ctx.laura.id,
                    business_type=business_type, market_entry_date=datetime(2020, 1, 1))
    ctx.db.add(prop)
    ctx.db.flush()
    return prop


def _closing(ctx, closed_on, business_type="Venta", agent=None, company=None, prop=None, notes=None, created_at=None):
    closing = Closing(company_id=(company or ctx.moyza).id, agent_id=(agent or ctx.laura).id,
                      business_type=business_type, closed_on=closed_on,
                      property_id=prop.id if prop else None, notes=notes, created_by=ctx.user.id,
                      created_at=created_at or datetime.utcnow())
    ctx.db.add(closing)
    ctx.db.flush()
    return closing


def _locked_report(ctx, period_type, start, end, company=None, **values):
    report = AgentPerformanceReport(
        agent_id=ctx.laura.id, company_id=(company or ctx.moyza).id, period_type=period_type,
        period_start=start, period_end=end, is_locked=True, locked_at=datetime(2025, 4, 1, 3, 0),
        **values,
    )
    ctx.db.add(report)
    ctx.db.flush()
    return report


def test_cuenta_cierres_manuales_y_no_seguimientos_cerrado(ctx):
    prop = _prop(ctx, ctx.moyza)
    # Un seguimiento «Cerrado» de una alerta de Laura en marzo: ya no es un cierre
    alert = PropertyAlert(property_id=prop.id, company_id=ctx.moyza.id, agent_id=ctx.laura.id,
                          lead_name="PYTEST", created_by=ctx.user.id, business_type="Venta",
                          created_at=datetime(2025, 3, 2))
    ctx.db.add(alert)
    ctx.db.flush()
    ctx.db.add(AlertFollowUp(alert_id=alert.id, action_type="CERRADO", created_by=ctx.user.id,
                             created_at=datetime(2025, 3, 3)))
    ctx.db.flush()

    svc = PerformanceReportService(ctx.db, ctx.moyza.id)
    assert svc.calculate_metrics(ctx.laura.id, *MARCH)["cierres"] == 0

    _closing(ctx, date(2025, 3, 15), "Venta", prop=prop, notes="Firma en notaría")
    m = svc.calculate_metrics(ctx.laura.id, *MARCH)
    assert (m["cierres"], m["cierres_venta"], m["cierres_alquiler"]) == (1, 1, 0)


def test_desglose_limites_de_dia_y_aislamiento(ctx):
    _closing(ctx, date(2025, 3, 1), "Venta")
    _closing(ctx, date(2025, 3, 31), "Alquiler")         # último día del mes: cuenta entero
    _closing(ctx, date(2025, 3, 20), "Alquiler")
    _closing(ctx, date(2025, 2, 28), "Venta")            # mes anterior
    _closing(ctx, date(2025, 4, 1), "Venta")             # mes siguiente
    _closing(ctx, date(2025, 3, 10), "Venta", company=ctx.moes)     # otra empresa
    _closing(ctx, date(2025, 3, 10), "Venta", agent=ctx.carlos)     # otro agente

    moyza = PerformanceReportService(ctx.db, ctx.moyza.id)
    m = moyza.calculate_metrics(ctx.laura.id, *MARCH)
    assert (m["cierres"], m["cierres_venta"], m["cierres_alquiler"]) == (3, 1, 2)
    assert moyza.breakdown(m, "cierres") == {"venta": 1, "alquiler": 2, "otros": 0}
    # La semana del 31/03/2025 (lunes) acaba el domingo 06/04: incluye el 31 y el 1 de abril
    week = moyza.week_bounds(datetime(2025, 3, 31))
    assert moyza.calculate_metrics(ctx.laura.id, *week)["cierres"] == 2

    moes = PerformanceReportService(ctx.db, ctx.moes.id).calculate_metrics(ctx.laura.id, *MARCH)
    assert (moes["cierres"], moes["cierres_venta"]) == (1, 1)
    assert moyza.calculate_metrics(ctx.carlos.id, *MARCH)["cierres"] == 1

    # Evolución anual: por mes y tipo
    evo = moyza.yearly_evolution(2025, [ctx.laura], now=datetime(2025, 6, 1))
    series = evo["agents"][0]["monthly"]["cierres"]
    assert (series["venta"][1], series["venta"][2], series["alquiler"][2], series["venta"][3]) == (1, 1, 2, 1)
    assert evo["agents"][0]["totals"]["cierres"]["total"] == 5


def test_refresca_snapshot_congelado_del_mes_y_del_anio(ctx):
    month = _locked_report(ctx, PeriodType.MONTHLY, *MARCH, captaciones_crm=4, captaciones_venta=4,
                           captaciones_alquiler=0, cierres=7, cierres_venta=7, cierres_alquiler=0,
                           admin_notes="Buen mes")
    year = _locked_report(ctx, PeriodType.YEARLY, *YEAR_2025, captaciones_crm=9, cierres=0)
    # Abril sin congelar y MOES congelado: no se tocan
    april = AgentPerformanceReport(agent_id=ctx.laura.id, company_id=ctx.moyza.id, period_type=PeriodType.MONTHLY,
                                   period_start=datetime(2025, 4, 1), period_end=datetime(2025, 4, 30, 23, 59, 59),
                                   cierres=5, is_locked=False)
    ctx.db.add(april)
    moes_month = _locked_report(ctx, PeriodType.MONTHLY, *MARCH, company=ctx.moes, cierres=3)

    _closing(ctx, date(2025, 3, 31), "Venta")
    _closing(ctx, date(2025, 3, 5), "Alquiler")
    _closing(ctx, date(2025, 6, 2), "Venta")

    svc = PerformanceReportService(ctx.db, ctx.moyza.id)
    touched = svc.refresh_closings_snapshot(ctx.laura.id, date(2025, 3, 31))

    assert {r.id for r in touched} == {month.id, year.id}
    assert (month.cierres, month.cierres_venta, month.cierres_alquiler) == (2, 1, 1)
    assert (year.cierres, year.cierres_venta, year.cierres_alquiler) == (3, 2, 1)
    # Solo las columnas de cierres: el resto del snapshot se conserva
    assert (month.captaciones_crm, month.captaciones_venta, month.admin_notes) == (4, 4, "Buen mes")
    assert month.is_locked and month.locked_at == datetime(2025, 4, 1, 3, 0)
    assert year.captaciones_crm == 9
    assert april.cierres == 5 and moes_month.cierres == 3

    # La tarjeta del mes cerrado (snapshot) refleja el cierre metido tarde
    period = svc.period(PeriodType.MONTHLY, "2025-03-01")
    metrics, _report = svc.metrics_for_period(ctx.laura.id, period)
    assert metrics["cierres"] == 2

    # Borrar el cierre y refrescar: vuelve a contar uno menos
    ctx.db.query(Closing).filter(Closing.agent_id == ctx.laura.id, Closing.closed_on == date(2025, 3, 5)).delete()
    ctx.db.flush()
    svc.refresh_closings_snapshot(ctx.laura.id, date(2025, 3, 5))
    assert (month.cierres, month.cierres_alquiler) == (1, 0)
    assert (year.cierres, year.cierres_alquiler) == (2, 0)


def test_refresco_sin_snapshot_no_hace_nada(ctx):
    _closing(ctx, date(2025, 3, 31), "Venta")
    svc = PerformanceReportService(ctx.db, ctx.moyza.id)
    assert svc.refresh_closings_snapshot(ctx.laura.id, date(2025, 3, 31)) == []
    assert svc.get_report(ctx.laura.id, PeriodType.MONTHLY, MARCH[0]) is None


def test_inicio_admin_actividad_y_equipo(ctx):
    now = datetime.utcnow()
    today = now.date()
    prop = _prop(ctx, ctx.moyza, title="PYTEST-CIERRES PISO")
    _closing(ctx, today, "Venta", prop=prop, created_at=now - timedelta(minutes=5))
    _closing(ctx, today - timedelta(days=40), "Alquiler", agent=ctx.carlos, created_at=now - timedelta(minutes=2))
    _closing(ctx, today, "Venta", company=ctx.moes, created_at=now - timedelta(minutes=1))

    svc = DashboardService(ctx.db, ctx.moyza.id)
    feed = [e for e in svc.activity_feed(now=now) if e["kind"] == "closing" and "PYTEST-CIERRES" in e["text"]]
    assert len(feed) == 2                      # el de MOES no sale
    late, with_prop = feed                     # orden por fecha de registro
    assert with_prop["title"] == "Cierre · PYTEST-CIERRES PISO"
    assert with_prop["text"].startswith("PYTEST-CIERRES LAURA · Venta · firmado el ")
    # Sin propiedad, el título lleva la operación; se registra hoy aunque se firmó hace 40 días
    assert late["title"] == "Cierre · Alquiler"
    assert late["text"] == f"PYTEST-CIERRES CARLOS · firmado el {(today - timedelta(days=40)).strftime('%d/%m/%Y')}"
    assert late["href"].startswith("/commercial-results?tab=cierres")

    # Tabla del equipo / anillos: misma métrica
    month = svc.period(PeriodType.MONTHLY, "", now=now)
    metrics = svc.team_metrics([ctx.laura.id, ctx.carlos.id], month)
    assert (metrics[ctx.laura.id]["cierres"], metrics[ctx.laura.id]["cierres_venta"]) == (1, 1)
