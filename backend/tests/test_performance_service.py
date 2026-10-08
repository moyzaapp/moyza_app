"""
Tests del servicio de rendimiento (PLAN_RESULTADOS_COMERCIALES.md, fase 1).

- Unitarios (sin base de datos): períodos semana / mes / año, objetivos por
  período, % de cumplimiento, desglose de snapshots y SQL del tipo de negocio.
- Con base de datos (se omiten si no hay conexión): aislamiento por empresa,
  desglose venta / alquiler (mayúsculas, NULL, tipo de la alerta en cierres),
  límites de año, snapshots y objetivos por empresa. Todo dentro de una
  transacción externa que se deshace al terminar (los commit del servicio
  solo cierran savepoints).

Ejecución dentro del contenedor:
    docker exec moyza_backend python -m pytest tests/test_performance_service.py -q
"""
from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from app.core.constants import PerformanceObjectives
from app.core.constants import PeriodType
from app.models.agent import Agent
from app.models.agent_performance_report import AgentPerformanceReport
from app.models.agent_performance_target import AgentPerformanceTarget
from app.models.alert_follow_up import AlertFollowUp
from app.models.property import Property
from app.models.property_alert import PropertyAlert
from app.models.property_price_history import PropertyPriceHistory
from app.models.property_visit import PropertyVisit
from app.services.performance_report_service import PerformanceReportService
from app.services.performance_report_service import business_kind
from app.services.performance_report_service import closing_business_type


NOW = datetime(2026, 10, 8, 10, 30)
svc_cls = PerformanceReportService


def _sql(clause):
    return str(clause.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


# ---------------------------------------------------------------------------
# Períodos
# ---------------------------------------------------------------------------

class TestPeriod:

    def test_semana_en_curso_por_defecto(self):
        p = svc_cls.period("WEEKLY", "", now=NOW)
        assert p.start == datetime(2026, 10, 5)
        assert p.end == datetime(2026, 10, 11, 23, 59, 59)
        assert p.is_current and not p.show_next
        assert p.prev_start == datetime(2026, 9, 28)
        assert p.label == "5 oct – 11 oct 2026"

    def test_semana_normaliza_al_lunes(self):
        p = svc_cls.period("WEEKLY", "2026-09-17", now=NOW)
        assert p.start == datetime(2026, 9, 14)
        assert not p.is_current and p.show_next

    def test_mes_cruza_el_anio(self):
        p = svc_cls.period("MONTHLY", "2026-01-20", now=NOW)
        assert p.start == datetime(2026, 1, 1)
        assert p.end == datetime(2026, 1, 31, 23, 59, 59)
        assert p.prev_start == datetime(2025, 12, 1)
        assert p.next_start == datetime(2026, 2, 1)
        assert p.label == "Enero 2026"

    def test_mes_diciembre_siguiente_es_enero(self):
        p = svc_cls.period("MONTHLY", "2025-12-03", now=NOW)
        assert p.next_start == datetime(2026, 1, 1)
        assert p.end == datetime(2025, 12, 31, 23, 59, 59)

    def test_anio_limites_y_navegacion(self):
        p = svc_cls.period("YEARLY", "2025-06-03", now=NOW)
        assert p.start == datetime(2025, 1, 1)
        assert p.end == datetime(2025, 12, 31, 23, 59, 59)
        assert p.prev_start == datetime(2024, 1, 1)
        assert p.next_start == datetime(2026, 1, 1)
        assert p.show_next and not p.is_current
        assert p.label == "2025"

    def test_anio_en_curso_sin_siguiente(self):
        p = svc_cls.period("YEARLY", "", now=NOW)
        assert p.start == datetime(2026, 1, 1)
        assert p.is_current and not p.show_next

    def test_anio_bisiesto(self):
        _, end = svc_cls.month_bounds(datetime(2028, 2, 1))
        assert end == datetime(2028, 2, 29, 23, 59, 59)

    def test_tipo_invalido_es_semana(self):
        assert svc_cls.period("DAILY", "", now=NOW).period_type == "WEEKLY"

    def test_fecha_invalida_es_periodo_en_curso(self):
        assert svc_cls.period("MONTHLY", "2026-13-45", now=NOW).start == datetime(2026, 10, 1)

    @pytest.mark.parametrize("period_type, start, expected", [
        ("WEEKLY", datetime(2026, 10, 5), True),
        ("WEEKLY", datetime(2026, 9, 28), False),
        ("MONTHLY", datetime(2026, 10, 1), True),
        ("MONTHLY", datetime(2025, 10, 1), False),
        ("YEARLY", datetime(2026, 1, 1), True),
        ("YEARLY", datetime(2025, 1, 1), False),
    ])
    def test_is_current_period(self, period_type, start, expected):
        assert svc_cls.is_current_period(period_type, start, now=NOW) is expected


# ---------------------------------------------------------------------------
# Objetivos por período y % de cumplimiento
# ---------------------------------------------------------------------------

def target(**values):
    fields = {f: None for f in PerformanceObjectives.TARGET_FIELDS.values()}
    fields.update(values)
    return SimpleNamespace(**fields)


class TestObjectives:

    def test_claves_por_periodo(self):
        assert svc_cls.objective_keys("WEEKLY") == ("captaciones_crm", "bajadas")
        assert svc_cls.objective_keys("MONTHLY") == ("captaciones_crm", "bajadas", "cierres")
        assert svc_cls.objective_keys("YEARLY") == ("captaciones_crm", "bajadas", "cierres")
        assert svc_cls.objective_keys("OTRO") == ()

    def test_campos_permitidos(self):
        assert svc_cls.allowed_target_fields("WEEKLY") == {"target_captaciones_crm", "target_bajadas"}
        assert "target_contactos" not in svc_cls.allowed_target_fields("MONTHLY")
        assert "target_hojas_visita" not in svc_cls.allowed_target_fields("YEARLY")

    def test_media_simple_de_los_porcentajes(self):
        metrics = {"captaciones_crm": 3, "bajadas": 1, "cierres": 0}
        t = target(target_captaciones_crm=4, target_bajadas=2)
        # 75 % y 50 % -> 62.5 -> 62 (redondeo bancario de round)
        assert svc_cls.completion_pct(metrics, t, "WEEKLY") == round((75 + 50) / 2)

    def test_cada_porcentaje_se_limita_a_100(self):
        metrics = {"captaciones_crm": 10, "bajadas": 0}
        t = target(target_captaciones_crm=2, target_bajadas=4)
        assert svc_cls.completion_pct(metrics, t, "WEEKLY") == 50

    def test_ignora_objetivos_que_no_son_del_periodo(self):
        """Un target_contactos antiguo no cuenta en la semana (decisión §5-5)."""
        metrics = {"contactos_venta": 0, "captaciones_crm": 2, "bajadas": 2}
        t = target(target_contactos=50, target_hojas_visita=10, target_captaciones_crm=2, target_bajadas=2)
        assert svc_cls.completion_pct(metrics, t, "WEEKLY") == 100

    def test_sin_objetivos_es_none(self):
        assert svc_cls.completion_pct({"captaciones_crm": 3}, None, "MONTHLY") is None
        assert svc_cls.completion_pct({"captaciones_crm": 3}, target(), "MONTHLY") is None

    def test_filas_de_objetivo(self):
        rows = svc_cls.objective_rows({"captaciones_crm": 5, "bajadas": 1, "cierres": 1},
                                      target(target_captaciones_crm=4), "MONTHLY")
        assert [r["key"] for r in rows] == ["captaciones_crm", "bajadas", "cierres"]
        assert rows[0]["pct"] == 125 and rows[0]["bar_pct"] == 100
        assert rows[1]["target"] is None and rows[1]["pct"] is None

    def test_contactos_es_venta_mas_alquiler(self):
        assert svc_cls.metric_value({"contactos_venta": 2, "contactos_alquiler": 3}, "contactos") == 5


class TestBreakdown:

    def test_desglose_con_otros(self):
        m = {"captaciones_crm": 5, "captaciones_venta": 3, "captaciones_alquiler": 1}
        assert svc_cls.breakdown(m, "captaciones_crm") == {"venta": 3, "alquiler": 1, "otros": 1}

    def test_snapshot_antiguo_sin_desglose(self):
        m = {"cierres": 4, "cierres_venta": None, "cierres_alquiler": None}
        assert svc_cls.breakdown(m, "cierres") is None
        assert svc_cls._snapshot_counts(m, "cierres") == {"venta": 0, "alquiler": 0, "otros": 4}

    def test_hojas_visita_no_tiene_desglose(self):
        assert svc_cls.breakdown({"hojas_visita": 3}, "hojas_visita") is None


class TestBusinessKindSql:

    def test_insensible_a_mayusculas(self):
        sql = _sql(business_kind(Property.business_type))
        assert "ILIKE 'venta'" in sql
        assert "ILIKE 'alquiler'" in sql
        assert "ELSE 'otros'" in sql

    def test_cierre_usa_alerta_y_cae_a_propiedad(self):
        sql = _sql(closing_business_type())
        assert sql.startswith("coalesce(nullif(trim(property_alerts.business_type), ''), properties.business_type")


def test_sin_empresa_no_calcula():
    with pytest.raises(ValueError, match="company_id"):
        PerformanceReportService(db=None).calculate_metrics(1, NOW, NOW)


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
    """Empresas, un usuario para `created_by` y un agente en las dos empresas."""
    from app.models.company import Company
    from app.models.user import User

    moyza = db.query(Company).filter_by(code="MOYZA").one()
    moes = db.query(Company).filter_by(code="MOES").one()
    user = db.query(User).order_by(User.id).first()
    if user is None:
        pytest.skip("Sin usuarios en la base de datos")

    agent = Agent(name="PYTEST-PERF AMBAS", email="pytest.perf.ambas@example.com")
    agent.companies.extend([moyza, moes])
    db.add(agent)
    db.flush()
    return SimpleNamespace(db=db, moyza=moyza, moes=moes, user=user, agent=agent)


def _prop(ctx, company, business_type, entry, title="PYTEST-PERF PROP"):
    prop = Property(title=title, company_id=company.id, agent_id=ctx.agent.id,
                    business_type=business_type, market_entry_date=entry)
    ctx.db.add(prop)
    ctx.db.flush()
    return prop


def _alert(ctx, prop, business_type, created_at, closed_at=None):
    alert = PropertyAlert(property_id=prop.id, agent_id=ctx.agent.id, lead_name="PYTEST",
                          created_by=ctx.user.id, business_type=business_type, created_at=created_at)
    ctx.db.add(alert)
    ctx.db.flush()
    if closed_at:
        ctx.db.add(AlertFollowUp(alert_id=alert.id, action_type="CERRADO",
                                 created_by=ctx.user.id, created_at=closed_at))
        ctx.db.flush()
    return alert


MARCH = (datetime(2025, 3, 1), datetime(2025, 3, 31, 23, 59, 59))


def test_metricas_aisladas_por_empresa(ctx):
    pm = _prop(ctx, ctx.moyza, "Venta", datetime(2025, 3, 10))
    pe = _prop(ctx, ctx.moes, "Alquiler", datetime(2025, 3, 11))
    ctx.db.add(PropertyPriceHistory(property_id=pm.id, old_price=100, new_price=90,
                                    created_at=datetime(2025, 3, 12)))
    _alert(ctx, pm, "Venta", datetime(2025, 3, 12), closed_at=datetime(2025, 3, 13))
    ctx.db.add(PropertyVisit(property_id=pe.id, visitor_name="PYTEST", agent_id=ctx.agent.id,
                             created_at=datetime(2025, 3, 14)))
    ctx.db.flush()

    m_moyza = PerformanceReportService(ctx.db, ctx.moyza.id).calculate_metrics(ctx.agent.id, *MARCH)
    m_moes = PerformanceReportService(ctx.db, ctx.moes.id).calculate_metrics(ctx.agent.id, *MARCH)

    assert (m_moyza["captaciones_crm"], m_moyza["captaciones_venta"]) == (1, 1)
    assert (m_moyza["bajadas"], m_moyza["bajadas_venta"]) == (1, 1)
    assert (m_moyza["cierres"], m_moyza["cierres_venta"], m_moyza["contactos_venta"]) == (1, 1, 1)
    assert m_moyza["hojas_visita"] == 0

    assert (m_moes["captaciones_crm"], m_moes["captaciones_alquiler"]) == (1, 1)
    assert m_moes["hojas_visita"] == 1
    assert m_moes["bajadas"] == m_moes["cierres"] == m_moes["contactos_venta"] == 0


def test_desglose_venta_alquiler_mayusculas_y_null(ctx):
    venta = _prop(ctx, ctx.moyza, "VENTA", datetime(2025, 3, 2))
    alquiler = _prop(ctx, ctx.moyza, "alquiler", datetime(2025, 3, 3))
    sin_tipo = _prop(ctx, ctx.moyza, None, datetime(2025, 3, 4))
    traspaso = _prop(ctx, ctx.moyza, "Traspaso", datetime(2025, 3, 5))
    # El default del modelo ("Venta") se aplica al insertar None: se anula después
    sin_tipo.business_type = None
    ctx.db.flush()
    for prop in (venta, alquiler, sin_tipo):
        ctx.db.add(PropertyPriceHistory(property_id=prop.id, old_price=100, new_price=50,
                                        created_at=datetime(2025, 3, 6)))
    # Subida de precio: no es bajada
    ctx.db.add(PropertyPriceHistory(property_id=venta.id, old_price=50, new_price=60,
                                    created_at=datetime(2025, 3, 6)))
    closed = datetime(2025, 3, 20)
    _alert(ctx, alquiler, None, closed, closed_at=closed)      # NULL -> el de la propiedad: alquiler
    _alert(ctx, alquiler, "Venta", closed, closed_at=closed)   # el de la alerta manda: venta
    _alert(ctx, venta, "", closed, closed_at=closed)           # vacío -> propiedad: venta
    _alert(ctx, sin_tipo, None, closed, closed_at=closed)      # sin tipo en ninguna: otros
    _alert(ctx, traspaso, "Venta", closed)                     # sin cierre: no cuenta

    m = PerformanceReportService(ctx.db, ctx.moyza.id).calculate_metrics(ctx.agent.id, *MARCH)

    assert (m["captaciones_crm"], m["captaciones_venta"], m["captaciones_alquiler"]) == (4, 1, 1)
    assert (m["bajadas"], m["bajadas_venta"], m["bajadas_alquiler"]) == (3, 1, 1)
    assert (m["cierres"], m["cierres_venta"], m["cierres_alquiler"]) == (4, 2, 1)
    # Contactos: solo cuentan venta y alquiler de la alerta, como antes
    assert (m["contactos_venta"], m["contactos_alquiler"]) == (2, 0)


def test_limites_del_anio(ctx):
    _prop(ctx, ctx.moyza, "Venta", datetime(2025, 12, 31, 23, 59, 59))
    _prop(ctx, ctx.moyza, "Venta", datetime(2026, 1, 1, 0, 0, 0))
    svc = PerformanceReportService(ctx.db, ctx.moyza.id)

    y2025 = svc.year_bounds(datetime(2025, 1, 1))
    y2026 = svc.year_bounds(datetime(2026, 1, 1))
    assert svc.calculate_metrics(ctx.agent.id, *y2025)["captaciones_crm"] == 1
    assert svc.calculate_metrics(ctx.agent.id, *y2026)["captaciones_crm"] == 1


def test_snapshots_y_objetivos_por_empresa(ctx):
    _prop(ctx, ctx.moyza, "Venta", datetime(2025, 3, 10))
    _prop(ctx, ctx.moes, "Alquiler", datetime(2025, 3, 10))
    _prop(ctx, ctx.moes, "Alquiler", datetime(2025, 3, 11))

    # Sin empresa recorre todas las empresas y sus agentes
    PerformanceReportService(ctx.db).freeze_all_for_period("MONTHLY", *MARCH)

    reports = {
        r.company_id: r
        for r in ctx.db.query(AgentPerformanceReport).filter_by(agent_id=ctx.agent.id)
    }
    assert set(reports) == {ctx.moyza.id, ctx.moes.id}
    assert reports[ctx.moyza.id].is_locked
    assert (reports[ctx.moyza.id].captaciones_crm, reports[ctx.moyza.id].captaciones_venta) == (1, 1)
    assert (reports[ctx.moes.id].captaciones_crm, reports[ctx.moes.id].captaciones_alquiler) == (2, 2)

    moyza_svc = PerformanceReportService(ctx.db, ctx.moyza.id)
    moes_svc = PerformanceReportService(ctx.db, ctx.moes.id)
    assert moyza_svc.get_report(ctx.agent.id, "MONTHLY", MARCH[0]).id == reports[ctx.moyza.id].id

    moyza_svc.save_target(ctx.agent.id, "MONTHLY", MARCH[0], ctx.user.id, target_captaciones_crm=5)
    moes_svc.save_target(ctx.agent.id, "MONTHLY", MARCH[0], ctx.user.id, target_captaciones_crm=8)
    assert moyza_svc.get_target(ctx.agent.id, "MONTHLY", MARCH[0]).target_captaciones_crm == 5
    assert moes_svc.get_target(ctx.agent.id, "MONTHLY", MARCH[0]).target_captaciones_crm == 8


def test_save_target_ignora_campos_fuera_del_periodo(ctx):
    start = datetime(2025, 3, 3)
    ctx.db.add(AgentPerformanceTarget(agent_id=ctx.agent.id, company_id=ctx.moyza.id,
                                      period_type="WEEKLY", period_start=start,
                                      target_contactos=9, created_by=ctx.user.id))
    ctx.db.flush()

    svc = PerformanceReportService(ctx.db, ctx.moyza.id)
    t = svc.save_target(ctx.agent.id, "WEEKLY", start, ctx.user.id,
                        target_bajadas=3, target_cierres=5, target_contactos=None)

    assert t.target_bajadas == 3
    assert t.target_cierres is None          # no es objetivo semanal
    assert t.target_contactos == 9           # histórico conservado


def test_evolucion_anual_snapshot_y_vivo(ctx):
    year = 2025
    # Marzo congelado con un snapshot antiguo (sin desglose)
    ctx.db.add(AgentPerformanceReport(
        agent_id=ctx.agent.id, company_id=ctx.moyza.id, period_type=PeriodType.MONTHLY,
        period_start=datetime(year, 3, 1), period_end=datetime(year, 3, 31, 23, 59, 59),
        captaciones_crm=4, bajadas=0, cierres=0, is_locked=True,
    ))
    # Marzo en vivo tendría 1: manda el snapshot
    _prop(ctx, ctx.moyza, "Venta", datetime(year, 3, 10))
    # Mayo sin congelar: en vivo
    _prop(ctx, ctx.moyza, "Alquiler", datetime(year, 5, 2))
    _prop(ctx, ctx.moyza, "Venta", datetime(year, 5, 3))
    ctx.db.add(AgentPerformanceTarget(agent_id=ctx.agent.id, company_id=ctx.moyza.id,
                                      period_type="YEARLY", period_start=datetime(year, 1, 1),
                                      target_captaciones_crm=12, created_by=ctx.user.id))
    ctx.db.flush()

    data = PerformanceReportService(ctx.db, ctx.moyza.id).yearly_evolution(year, [ctx.agent], now=NOW)
    agent = data["agents"][0]
    capt = agent["monthly"]["captaciones_crm"]

    assert (capt["venta"][2], capt["alquiler"][2], capt["otros"][2]) == (0, 0, 4)
    assert (capt["venta"][4], capt["alquiler"][4]) == (1, 1)
    totals = agent["totals"]["captaciones_crm"]
    assert (totals["total"], totals["otros"], totals["target"]) == (6, 4, 12)
    # Solo captaciones tiene objetivo: 6 / 12
    assert agent["completion"] == 50
    assert data["indicators"] == {"captaciones_crm": "Captaciones CRM", "cierres": "Cierres", "bajadas": "Bajadas"}
