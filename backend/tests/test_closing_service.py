"""
Cierres compartidos por dos agentes (PLAN_CIERRES_DOS_AGENTES.md, fase A).

`closing_service.create_closing` crea uno o dos registros (mismo `pair_key`,
`shared_with_agent_id` cruzado) y `delete_closing` borra la pareja entera;
los dos refrescan los snapshots congelados de cada agente. La métrica por
agente no cambia: un cierre compartido suma 1 a cada agente y 2 al equipo.

Con base de datos (se omiten si no hay conexión), dentro de una transacción
externa que se deshace al terminar (los commit del servicio solo cierran
savepoints): no dejan datos.

Ejecución dentro del contenedor:
    docker exec moyza_backend python -m pytest tests/test_closing_service.py -q
"""
from datetime import date, datetime
from types import SimpleNamespace

import pytest

from app.core.constants import PeriodType
from app.models.agent import Agent
from app.models.agent_performance_report import AgentPerformanceReport
from app.models.closing import Closing
from app.models.property import Property
from app.services import closing_service
from app.services.closing_service import ClosingError
from app.services.dashboard_service import DashboardService
from app.services.performance_report_service import PerformanceReportService


MARCH = (datetime(2025, 3, 1), datetime(2025, 3, 31, 23, 59, 59))


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
    """MOYZA y MOES; Ana y Bea en MOYZA, Inés de baja en MOYZA y Mía solo en MOES."""
    from app.models.company import Company
    from app.models.user import User

    moyza = db.query(Company).filter_by(code="MOYZA").one()
    moes = db.query(Company).filter_by(code="MOES").one()
    user = db.query(User).order_by(User.id).first()
    if user is None:
        pytest.skip("Sin usuarios en la base de datos")

    def agent(name, company, active=True):
        found = Agent(name=f"PYTEST-PAREJA {name}", email=f"pytest.pareja.{name.lower()}@example.com",
                      is_active=active)
        found.companies.append(company)
        db.add(found)
        return found

    ana, bea = agent("ANA", moyza), agent("BEA", moyza)
    ines, mia = agent("INES", moyza, active=False), agent("MIA", moes)
    db.flush()
    prop = Property(title="PYTEST-PAREJA PISO", company_id=moyza.id, agent_id=ana.id,
                    business_type="Venta", market_entry_date=datetime(2020, 1, 1))
    db.add(prop)
    db.flush()
    return SimpleNamespace(db=db, moyza=moyza, moes=moes, user=user, ana=ana, bea=bea, ines=ines, mia=mia,
                           prop=prop)


def _create(ctx, agent_ids, closed_on=date(2025, 3, 10), business_type="Venta", **kwargs):
    return closing_service.create_closing(ctx.db, ctx.moyza.id, agent_ids, business_type, closed_on,
                                          created_by=ctx.user.id, **kwargs)


def _stored(ctx, *agents):
    ids = [a.id for a in agents]
    return ctx.db.query(Closing).filter(Closing.agent_id.in_(ids)).order_by(Closing.id).all()


def _locked_month(ctx, agent):
    report = AgentPerformanceReport(
        agent_id=agent.id, company_id=ctx.moyza.id, period_type=PeriodType.MONTHLY,
        period_start=MARCH[0], period_end=MARCH[1], is_locked=True, locked_at=datetime(2025, 4, 1, 3, 0),
        cierres=0, cierres_venta=0, cierres_alquiler=0,
    )
    ctx.db.add(report)
    ctx.db.flush()
    return report


def test_alta_de_un_agente_sin_pareja(ctx):
    closings = _create(ctx, [ctx.ana.id], property_id=ctx.prop.id, notes="  Notaría  ")
    assert len(closings) == 1
    closing = closings[0]
    assert (closing.agent_id, closing.shared_with_agent_id, closing.pair_key) == (ctx.ana.id, None, None)
    assert (closing.property_id, closing.notes, closing.company_id) == (ctx.prop.id, "Notaría", ctx.moyza.id)


def test_alta_con_dos_agentes_crea_dos_registros_enlazados(ctx):
    first, second = _create(ctx, [ctx.ana.id, ctx.bea.id], business_type="Alquiler",
                            property_id=ctx.prop.id, notes="Entre dos")
    assert [c.id for c in _stored(ctx, ctx.ana, ctx.bea)] == [first.id, second.id]
    assert (first.agent_id, first.shared_with_agent_id) == (ctx.ana.id, ctx.bea.id)
    assert (second.agent_id, second.shared_with_agent_id) == (ctx.bea.id, ctx.ana.id)
    assert first.pair_key and first.pair_key == second.pair_key and len(first.pair_key) == 36
    for field in ("business_type", "closed_on", "property_id", "notes", "created_by", "created_at"):
        assert getattr(first, field) == getattr(second, field)
    assert first.shared_with_agent.name == "PYTEST-PAREJA BEA"

    # Otro cierre compartido de la misma pareja: otra clave
    other = _create(ctx, [ctx.bea.id, ctx.ana.id])
    assert other[0].pair_key != first.pair_key


@pytest.mark.parametrize("who, message", [
    (lambda c: [c.ana.id, c.ana.id], "distintos"),
    (lambda c: [], "agente activo"),
    (lambda c: [c.ana.id, c.mia.id], "agente activo"),       # de otra empresa
    (lambda c: [c.ines.id], "agente activo"),                # de baja
    (lambda c: [c.ana.id, c.bea.id, c.ines.id], "dos agentes como máximo"),
])
def test_alta_rechaza_agentes_no_validos(ctx, who, message):
    with pytest.raises(ClosingError, match=message):
        _create(ctx, who(ctx))
    assert _stored(ctx, ctx.ana, ctx.bea, ctx.ines, ctx.mia) == []


def test_alta_rechaza_operacion_y_propiedad_ajena(ctx):
    moes_prop = Property(title="PYTEST-PAREJA MOES", company_id=ctx.moes.id, agent_id=ctx.mia.id,
                         business_type="Venta", market_entry_date=datetime(2020, 1, 1))
    ctx.db.add(moes_prop)
    ctx.db.flush()
    with pytest.raises(ClosingError, match="Venta o de Alquiler"):
        _create(ctx, [ctx.ana.id, ctx.bea.id], business_type="Traspaso")
    with pytest.raises(ClosingError, match="no pertenece"):
        _create(ctx, [ctx.ana.id, ctx.bea.id], property_id=moes_prop.id)
    assert _stored(ctx, ctx.ana, ctx.bea) == []


def test_borrar_uno_borra_la_pareja(ctx):
    single = _create(ctx, [ctx.ana.id])[0]
    first, second = _create(ctx, [ctx.ana.id, ctx.bea.id])
    first_id, second_id, single_id = first.id, second.id, single.id

    deleted = closing_service.delete_closing(ctx.db, ctx.moyza.id, second_id)
    assert deleted.shared and sorted(deleted.agent_ids) == sorted([ctx.ana.id, ctx.bea.id])
    assert deleted.closed_on == date(2025, 3, 10)
    assert [c.id for c in _stored(ctx, ctx.ana, ctx.bea)] == [single_id]
    assert first_id not in [c.id for c in ctx.db.query(Closing.id)]

    # Uno suelto solo se borra a sí mismo
    deleted = closing_service.delete_closing(ctx.db, ctx.moyza.id, single_id)
    assert not deleted.shared and deleted.agent_ids == [ctx.ana.id]
    assert _stored(ctx, ctx.ana, ctx.bea) == []


def test_borrar_de_otra_empresa_o_inexistente(ctx):
    closing = _create(ctx, [ctx.ana.id, ctx.bea.id])[0]
    with pytest.raises(ClosingError, match="no encontrado"):
        closing_service.delete_closing(ctx.db, ctx.moes.id, closing.id)
    assert len(_stored(ctx, ctx.ana, ctx.bea)) == 2


def test_alta_y_borrado_refrescan_los_snapshots_de_los_dos(ctx):
    ana_month, bea_month = _locked_month(ctx, ctx.ana), _locked_month(ctx, ctx.bea)

    first, _second = _create(ctx, [ctx.ana.id, ctx.bea.id], closed_on=date(2025, 3, 20))
    assert (ana_month.cierres, ana_month.cierres_venta) == (1, 1)
    assert (bea_month.cierres, bea_month.cierres_venta) == (1, 1)

    closing_service.delete_closing(ctx.db, ctx.moyza.id, first.id)
    assert (ana_month.cierres, bea_month.cierres) == (0, 0)


def test_metrica_cuenta_uno_por_agente_y_dos_en_el_equipo(ctx):
    _create(ctx, [ctx.ana.id, ctx.bea.id], closed_on=date(2025, 3, 10))
    _create(ctx, [ctx.ana.id], closed_on=date(2025, 3, 12), business_type="Alquiler")

    svc = PerformanceReportService(ctx.db, ctx.moyza.id)
    ana = svc.calculate_metrics(ctx.ana.id, *MARCH)
    bea = svc.calculate_metrics(ctx.bea.id, *MARCH)
    assert (ana["cierres"], ana["cierres_venta"], ana["cierres_alquiler"]) == (2, 1, 1)
    assert (bea["cierres"], bea["cierres_venta"], bea["cierres_alquiler"]) == (1, 1, 0)

    counts = svc.grouped_counts("cierres", *MARCH, [ctx.ana.id, ctx.bea.id])
    team = sum(sum(c.values()) for c in counts.values())
    assert team == 3                       # 2 del compartido + 1 suelto

    # Inicio del admin (tabla del equipo y anillos): suma de los agentes
    dash = DashboardService(ctx.db, ctx.moyza.id)
    month = dash.period(PeriodType.MONTHLY, "2025-03-01", now=datetime(2025, 3, 31, 12, 0))
    metrics = dash.team_metrics([ctx.ana.id, ctx.bea.id], month)
    assert metrics[ctx.ana.id]["cierres"] + metrics[ctx.bea.id]["cierres"] == 3
