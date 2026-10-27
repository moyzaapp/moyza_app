"""
Tests de la trazabilidad de indicadores (PLAN_TRAZABILIDAD_INDICADORES.md, fase 1).

La garantía del panel de detalle: para cada indicador, las filas que devuelve
`indicator_rows` son exactamente las que cuenta la tarjeta
(`len(filas) == metric_value(calculate_metrics(), indicador)`), con datos de
venta y alquiler, dentro y fuera del período, de otra empresa y de otro
agente. Además, la frase de la regla nombra agente, empresa y fechas.

Los tests con base de datos van dentro de una transacción externa que se
deshace al terminar (no dejan datos). Se omiten si no hay conexión.

Ejecución dentro del contenedor:
    docker exec moyza_backend python -m pytest tests/test_indicator_rows.py -q
"""
from datetime import datetime
from types import SimpleNamespace

import pytest

from app.models.agent import Agent
from app.models.agent_performance_report import AgentPerformanceReport
from app.models.alert_follow_up import AlertFollowUp
from app.models.property import Property
from app.models.property_alert import PropertyAlert
from app.models.property_price_history import PropertyPriceHistory
from app.models.property_visit import PropertyVisit
from app.services.performance_report_service import PerformanceReportService
from app.services.performance_report_service import RESULT_METRICS


svc_cls = PerformanceReportService
MARCH = (datetime(2025, 3, 1), datetime(2025, 3, 31, 23, 59, 59))
IN = datetime(2025, 3, 10, 12, 0)
IN_LATE = datetime(2025, 3, 31, 23, 59, 59)
BEFORE = datetime(2025, 2, 28, 23, 59, 59)
AFTER = datetime(2025, 4, 1, 0, 0, 0)


# ---------------------------------------------------------------------------
# Sin base de datos
# ---------------------------------------------------------------------------

class TestDateRangeText:

    def test_mismo_mes(self):
        assert svc_cls.date_range_text(*MARCH) == "entre el 1 y el 31 de marzo de 2025"

    def test_semana_que_cruza_mes(self):
        start, end = svc_cls.week_bounds(datetime(2026, 9, 28))
        assert svc_cls.date_range_text(start, end) == "entre el 28 de septiembre y el 4 de octubre de 2026"

    def test_semana_que_cruza_anio(self):
        start, end = svc_cls.week_bounds(datetime(2025, 12, 29))
        assert svc_cls.date_range_text(start, end) == "entre el 29 de diciembre de 2025 y el 4 de enero de 2026"

    def test_anio(self):
        start, end = svc_cls.year_bounds(datetime(2026, 1, 1))
        assert svc_cls.date_range_text(start, end) == "entre el 1 de enero y el 31 de diciembre de 2026"


def test_indicador_desconocido():
    svc = PerformanceReportService(db=None, company_id=1)
    with pytest.raises(ValueError):
        svc.indicator_rows("calidad_cartera", 1, *MARCH)
    with pytest.raises(ValueError):
        svc_cls.indicator_rule_text("otro", SimpleNamespace(name="X"), *MARCH, SimpleNamespace(name="Y"))


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
    """Agente en las dos empresas, otro agente en MOYZA y un juego de datos de marzo de 2025."""
    from app.models.company import Company
    from app.models.user import User

    moyza = db.query(Company).filter_by(code="MOYZA").one()
    moes = db.query(Company).filter_by(code="MOES").one()
    user = db.query(User).order_by(User.id).first()
    if user is None:
        pytest.skip("Sin usuarios en la base de datos")

    agent = Agent(name="PYTEST-TRAZA LAURA", email="pytest.traza.laura@example.com")
    agent.companies.extend([moyza, moes])
    other = Agent(name="PYTEST-TRAZA OTRO", email="pytest.traza.otro@example.com")
    other.companies.append(moyza)
    db.add_all([agent, other])
    db.flush()

    c = SimpleNamespace(db=db, moyza=moyza, moes=moes, user=user, agent=agent, other=other)
    _seed(c)
    return c


def _prop(c, company, business_type, entry, agent=None, title="PYTEST-TRAZA PROP"):
    prop = Property(title=title, referencia="PYT-REF", city="Jaén", address="Calle Secreta 12",
                    company_id=company.id, agent_id=(agent or c.agent).id,
                    business_type=business_type, market_entry_date=entry, price=100000)
    c.db.add(prop)
    c.db.flush()
    return prop


def _drop(c, prop, created_at, old=100, new=90):
    c.db.add(PropertyPriceHistory(property_id=prop.id, old_price=old, new_price=new,
                                  reason="PYTEST", created_at=created_at))


def _alert(c, prop, business_type, created_at, agent=None, company=None, closed_at=None, lead="PYTEST COMPRADOR"):
    alert = PropertyAlert(property_id=prop.id if prop else None,
                          company_id=(company or (prop.company if prop else c.moyza)).id,
                          origin="property" if prop else "search",
                          agent_id=(agent or c.agent).id, lead_name=lead, created_by=c.user.id,
                          business_type=business_type, created_at=created_at)
    c.db.add(alert)
    c.db.flush()
    if closed_at:
        c.db.add(AlertFollowUp(alert_id=alert.id, action_type="CERRADO", notes="Firmado",
                               created_by=c.user.id, created_at=closed_at))
    return alert


def _visit(c, prop, created_at, agent=None, companion=None):
    c.db.add(PropertyVisit(property_id=prop.id, visitor_name="PYTEST VISITANTE",
                           agent_id=agent.id if agent else None,
                           companion_agent_id=companion.id if companion else None,
                           created_at=created_at))


def _seed(c):
    # Captaciones (MOYZA, marzo, Laura): venta, alquiler, traspaso (otros) y el último segundo del mes
    venta = _prop(c, c.moyza, "Venta", IN)
    alquiler = _prop(c, c.moyza, "alquiler", IN)
    traspaso = _prop(c, c.moyza, "Traspaso", IN)
    _prop(c, c.moyza, "VENTA", IN_LATE)
    # Fuera: otro mes, otra empresa, otro agente
    fuera = _prop(c, c.moyza, "Venta", BEFORE)
    _prop(c, c.moyza, "Venta", AFTER)
    moes = _prop(c, c.moes, "Venta", IN)
    ajena = _prop(c, c.moyza, "Alquiler", IN, agent=c.other)

    # Bajadas: venta, alquiler y traspaso cuentan; subida, fuera de mes, MOES y otro agente no
    _drop(c, venta, IN)
    _drop(c, alquiler, IN)
    _drop(c, traspaso, IN)
    _drop(c, venta, IN, old=90, new=95)
    _drop(c, venta, AFTER)
    _drop(c, fuera, BEFORE)
    _drop(c, moes, IN)
    _drop(c, ajena, IN)

    # Contactos: venta, alquiler, búsqueda sin propiedad (venta); sin tipo no cuenta (otros)
    _alert(c, venta, "Venta", IN, closed_at=IN)
    _alert(c, alquiler, "Alquiler", IN, closed_at=IN_LATE)
    _alert(c, None, "Venta", IN, company=c.moyza, closed_at=IN)       # búsqueda general cerrada
    sin_tipo = _alert(c, traspaso, None, IN, closed_at=IN)           # contacto 'otros'; cierre por la propiedad: otros
    _alert(c, venta, "Venta", BEFORE, closed_at=AFTER)                # fuera de período (ambos)
    _alert(c, moes, "Venta", IN, closed_at=IN)                        # otra empresa
    _alert(c, ajena, "Alquiler", IN, agent=c.other, closed_at=IN)     # otro agente
    # Seguimiento que no es cierre
    c.db.add(AlertFollowUp(alert_id=sin_tipo.id, action_type="CONTACTADO",
                           created_by=c.user.id, created_at=IN))

    # Visitas: principal, acompañante; MOES, otro agente y fuera de período no cuentan
    _visit(c, venta, IN, agent=c.agent)
    _visit(c, alquiler, IN, agent=c.other, companion=c.agent)
    _visit(c, moes, IN, agent=c.agent)
    _visit(c, ajena, IN, agent=c.other)
    _visit(c, venta, AFTER, agent=c.agent)
    c.db.flush()


EXPECTED_MOYZA = {
    "captaciones_crm": 4,   # venta, alquiler, traspaso, venta del último segundo
    "bajadas": 3,
    "contactos": 3,         # venta, alquiler, búsqueda (venta); el sin tipo no suma
    "cierres": 4,           # venta, alquiler, búsqueda, sin tipo (otros)
    "hojas_visita": 2,
}


@pytest.mark.parametrize("indicator", RESULT_METRICS)
def test_filas_igual_al_contador(ctx, indicator):
    svc = PerformanceReportService(ctx.db, ctx.moyza.id)
    metrics = svc.calculate_metrics(ctx.agent.id, *MARCH)
    expected = svc.metric_value(metrics, indicator)

    rows = svc.indicator_rows(indicator, ctx.agent.id, *MARCH, limit=None)

    assert expected == EXPECTED_MOYZA[indicator]
    assert len(rows) == expected
    assert svc.indicator_live_total(indicator, ctx.agent.id, *MARCH) == expected

    # El desglose de las filas coincide con el de la tarjeta
    detail = svc.breakdown(metrics, indicator)
    if detail is not None:
        for kind in ("venta", "alquiler", "otros"):
            assert sum(1 for r in rows if r["kind"] == kind) == detail[kind], kind
        assert svc.indicator_live_counts(indicator, ctx.agent.id, *MARCH)["detail"] == detail


@pytest.mark.parametrize("indicator", RESULT_METRICS)
def test_otra_empresa_y_otro_agente(ctx, indicator):
    moes = PerformanceReportService(ctx.db, ctx.moes.id)
    moes_value = moes.metric_value(moes.calculate_metrics(ctx.agent.id, *MARCH), indicator)
    assert len(moes.indicator_rows(indicator, ctx.agent.id, *MARCH, limit=None)) == moes_value
    # Cada indicador tiene exactamente un registro de Laura en MOES
    assert moes_value == 1

    moyza = PerformanceReportService(ctx.db, ctx.moyza.id)
    other_value = moyza.metric_value(moyza.calculate_metrics(ctx.other.id, *MARCH), indicator)
    assert len(moyza.indicator_rows(indicator, ctx.other.id, *MARCH, limit=None)) == other_value


def test_filas_ordenadas_y_paginadas(ctx):
    svc = PerformanceReportService(ctx.db, ctx.moyza.id)
    all_rows = svc.indicator_rows("captaciones_crm", ctx.agent.id, *MARCH, limit=None)
    assert all_rows[0]["date"] == IN_LATE
    assert [r["date"] for r in all_rows] == sorted((r["date"] for r in all_rows), reverse=True)

    first = svc.indicator_rows("captaciones_crm", ctx.agent.id, *MARCH, limit=3)
    rest = svc.indicator_rows("captaciones_crm", ctx.agent.id, *MARCH, limit=3, offset=3)
    assert [r["id"] for r in first + rest] == [r["id"] for r in all_rows]
    assert len(rest) == 1


def test_contenido_de_las_filas(ctx):
    svc = PerformanceReportService(ctx.db, ctx.moyza.id)

    capt = svc.indicator_rows("captaciones_crm", ctx.agent.id, *MARCH)[0]
    assert (capt["property_ref"], capt["property_city"]) == ("PYT-REF", "Jaén")
    # Sin dirección (decisión §4, nota)
    assert "address" not in capt and "Calle Secreta" not in str(capt)

    contacts = svc.indicator_rows("contactos", ctx.agent.id, *MARCH)
    assert sum(1 for r in contacts if r["is_search"]) == 1
    assert all(r["buyer_name"] == "PYTEST COMPRADOR" for r in contacts)

    drops = svc.indicator_rows("bajadas", ctx.agent.id, *MARCH)
    assert all(r["new_price"] < r["old_price"] for r in drops)

    closings = svc.indicator_rows("cierres", ctx.agent.id, *MARCH)
    assert {r["notes"] for r in closings} == {"Firmado"}

    visits = svc.indicator_rows("hojas_visita", ctx.agent.id, *MARCH)
    assert sorted(r["role"] for r in visits) == ["acompañante", "principal"]


def test_frase_de_la_regla(ctx):
    for indicator in RESULT_METRICS:
        text = svc_cls.indicator_rule_text(indicator, ctx.agent, *MARCH, ctx.moyza)
        assert ctx.agent.name in text
        assert ctx.moyza.name in text
        assert "entre el 1 y el 31 de marzo de 2025" in text
    assert "fecha de entrada al mercado" in svc_cls.indicator_rule_text(
        "captaciones_crm", ctx.agent, *MARCH, ctx.moes)


def test_congelado_frente_a_recalculado(ctx):
    svc = PerformanceReportService(ctx.db, ctx.moyza.id)
    period = svc.period("MONTHLY", "2025-03-01")
    assert svc.indicator_frozen("captaciones_crm", ctx.agent.id, period) is None

    ctx.db.add(AgentPerformanceReport(
        agent_id=ctx.agent.id, company_id=ctx.moyza.id, period_type="MONTHLY",
        period_start=period.start, period_end=period.end, captaciones_crm=2,
        captaciones_venta=2, captaciones_alquiler=0, is_locked=True, locked_at=datetime(2025, 4, 1, 3, 0),
    ))
    ctx.db.flush()

    frozen = svc.indicator_frozen("captaciones_crm", ctx.agent.id, period)
    assert frozen["total"] == 2 and frozen["locked_at"] == datetime(2025, 4, 1, 3, 0)
    assert svc.indicator_live_total("captaciones_crm", ctx.agent.id, period.start, period.end) == 4
