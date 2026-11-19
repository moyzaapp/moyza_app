"""
Listas de agentes por empresa y sin dados de baja; contactos por agente
(PLAN_LISTAS_AGENTES_POR_EMPRESA.md, fase B).

- Servicio, dentro de una transacción que se deshace al terminar:
  filas de Rendimiento (activos de la empresa; en un período congelado, el
  dado de baja con snapshot), contactos de una alerta de otra empresa en
  Rendimiento y en la lupa (distintivo, CSV con "Empresa"), grupos del alta
  y la reasignación, ventana "sin gestionar" y la suma de empresas del Inicio
  del agente sin duplicar contactos (`sum_company_metrics`).
- Rutas, contra la app levantada (se omite si no responde): filtro de
  agentes de Alertas sin dados de baja ni agentes de MOES, chip del agente
  fuera de la lista y Rendimiento de MOYZA sin el agente de MOES.

    docker exec moyza_backend python -m pytest tests/test_agent_lists_by_company.py -q
"""
import os
import re
import urllib.error
import urllib.request
from datetime import datetime
from types import SimpleNamespace

import pytest

from app.core.constants import AlertStatus
from app.core.constants import PeriodType

TAG = "PYTEST-LISTAS"
EMAIL = "pytest.listas.{}@example.com"
PAST_MONTH = "2026-10-01"


# ---------------------------------------------------------------------------
# Servicio con base de datos
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
    """Agentes: ana (MOYZA), baja (MOYZA, dado de baja, con snapshot de octubre),
    olvido (MOYZA, dado de baja, sin nada), carla (MOES) y dual (las dos)."""
    from app.models.agent import Agent
    from app.models.company import Company
    from app.models.property import Property
    from app.models.user import User

    moyza = db.query(Company).filter_by(code="MOYZA").one()
    moes = db.query(Company).filter_by(code="MOES").one()
    admin = User(email=EMAIL.format("admin"), full_name="Admin", hashed_password="x", is_active=True)
    db.add(admin)

    def agent(key, companies, active=True):
        ag = Agent(name=f"{TAG} {key.upper()}", email=EMAIL.format(key), is_active=active,
                   company=", ".join(c.name for c in companies))
        ag.companies.extend(companies)
        db.add(ag)
        return ag

    agents = {
        "ana": agent("ana", [moyza]),
        "baja": agent("baja", [moyza], active=False),
        "olvido": agent("olvido", [moyza], active=False),
        "carla": agent("carla", [moes]),
        "dual": agent("dual", [moyza, moes]),
    }
    db.flush()
    props = {
        "moyza": Property(title=f"{TAG} PISO MOYZA", address="Calle Test 1", city="Jaén",
                          agent_id=agents["ana"].id, company_id=moyza.id, business_type="Venta"),
        "moes": Property(title=f"{TAG} PISO MOES", address="Calle Test 2", city="Granada",
                         agent_id=agents["carla"].id, company_id=moes.id, business_type="Venta"),
    }
    db.add_all(props.values())
    db.flush()
    return SimpleNamespace(db=db, moyza=moyza, moes=moes, admin=admin, agents=agents, props=props)


def _alert(ctx, agent, prop_key, created_at=None, business_type="Venta"):
    from app.models.property_alert import PropertyAlert
    prop = ctx.props[prop_key]
    alert = PropertyAlert(property_id=prop.id, company_id=prop.company_id, origin="property",
                          agent_id=agent.id, lead_name=f"{TAG} COMPRADOR", created_by=ctx.admin.id,
                          business_type=business_type, status=AlertStatus.PENDING,
                          created_at=created_at or datetime.utcnow())
    ctx.db.add(alert)
    ctx.db.flush()
    return alert


def _snapshot(ctx, agent, company, period, contactos=0, all_companies=False):
    from app.models.agent_performance_report import AgentPerformanceReport
    report = AgentPerformanceReport(
        agent_id=agent.id, company_id=company.id, period_type=period.period_type,
        period_start=period.start, period_end=period.end, contactos_venta=contactos,
        contactos_alquiler=0, captaciones_crm=1, bajadas=0, cierres=0, hojas_visita=0,
        is_locked=True, locked_at=period.end, contacts_all_companies=all_companies,
    )
    ctx.db.add(report)
    ctx.db.flush()
    return report


def _mine(agents):
    return [a.name for a in agents if a.name.startswith(TAG)]


def test_rendimiento_solo_activos_de_la_empresa(ctx):
    from app.services.performance_report_service import PerformanceReportService

    svc = PerformanceReportService(ctx.db, ctx.moyza.id)
    current = svc.period(PeriodType.MONTHLY)
    # Período en curso: activos de MOYZA; ni dados de baja ni la agente de MOES
    assert _mine(svc.period_agents(current)) == [f"{TAG} ANA", f"{TAG} DUAL"]
    # En MOES, solo los suyos
    moes = PerformanceReportService(ctx.db, ctx.moes.id)
    assert _mine(moes.period_agents(current)) == [f"{TAG} CARLA", f"{TAG} DUAL"]


def test_periodo_congelado_conserva_al_dado_de_baja_con_snapshot(ctx):
    from app.services.performance_report_service import PerformanceReportService

    svc = PerformanceReportService(ctx.db, ctx.moyza.id)
    october = svc.period(PeriodType.MONTHLY, PAST_MONTH)
    _snapshot(ctx, ctx.agents["baja"], ctx.moyza, october)
    # El dado de baja con snapshot sigue (badge "Baja" en la plantilla); el
    # que no tiene snapshot ni actividad, no
    assert _mine(svc.period_agents(october)) == [f"{TAG} ANA", f"{TAG} BAJA", f"{TAG} DUAL"]
    data = {d["agent"].name: d for d in svc.agents_period_data(svc.period_agents(october), october)}
    assert data[f"{TAG} BAJA"]["is_locked"] and data[f"{TAG} BAJA"]["values"]["captaciones_crm"] == 1
    # Sin snapshot pero con actividad en ese período, también sale
    _alert(ctx, ctx.agents["olvido"], "moyza", created_at=datetime(2026, 10, 15, 10))
    assert f"{TAG} OLVIDO" in _mine(svc.period_agents(october))
    # En el período en curso, ninguno de los dos
    assert _mine(svc.period_agents(svc.period(PeriodType.MONTHLY))) == [f"{TAG} ANA", f"{TAG} DUAL"]


def test_contacto_de_alerta_de_otra_empresa_cuenta_en_rendimiento_y_lupa(ctx):
    from app.services.performance_report_service import PerformanceReportService
    from app.web.routes.commercial_results import METRIC_CSV_COLUMNS

    ana = ctx.agents["ana"]
    own = _alert(ctx, ana, "moyza")
    foreign = _alert(ctx, ana, "moes")
    svc = PerformanceReportService(ctx.db, ctx.moyza.id)
    period = svc.period(PeriodType.MONTHLY)

    metrics = svc.calculate_metrics(ana.id, period.start, period.end)
    assert svc.metric_value(metrics, "contactos") == 2

    rows = {r["alert_id"]: r for r in svc.indicator_rows("contactos", ana.id, period.start, period.end, limit=None)}
    assert set(rows) == {own.id, foreign.id}
    assert rows[own.id]["alert_company"] is None and rows[own.id]["property_company"] is None
    assert rows[foreign.id]["alert_company"].id == ctx.moes.id
    assert rows[foreign.id]["property_company"].id == ctx.moes.id
    # CSV: columna "Empresa" con la empresa de la alerta
    columns = dict(METRIC_CSV_COLUMNS["contactos"])
    assert columns["Empresa"](rows[foreign.id]) == "MOES PREMIUM"
    assert columns["Empresa"](rows[own.id]) == "MOYZA"
    # La regla lo explica
    text = svc.indicator_rule_text("contactos", ana, period.start, period.end, ctx.moyza)
    assert f"contactos registrados por {ana.name} en sus alertas de cualquier empresa" in text

    # Captaciones siguen siendo de la empresa de la propiedad: la de MOES no cuenta en MOYZA
    assert svc.calculate_metrics(ctx.agents["carla"].id, period.start, period.end)["captaciones_crm"] == 0


def test_lupa_html_con_distintivo(ctx):
    from app.services.performance_report_service import PerformanceReportService
    from app.web.template_env import templates

    ana = ctx.agents["ana"]
    _alert(ctx, ana, "moes")
    svc = PerformanceReportService(ctx.db, ctx.moyza.id)
    period = svc.period(PeriodType.MONTHLY)
    rows = svc.indicator_rows("contactos", ana.id, period.start, period.end)
    html = templates.get_template("commercial_results/_metric_detail.html").render(
        key="contactos", label="Contactos", agent=ana, company=ctx.moyza, period=period, rows=rows,
        live=svc.indicator_live_counts("contactos", ana.id, period.start, period.end), offset=0,
        rows_only=True, has_more=False, remaining=0, more_url=None,
        kind_labels={"venta": "Venta", "alquiler": "Alquiler", "otros": "Otros"}, visit_status_labels={},
    )
    assert 'title="Alerta de MOES PREMIUM"' in html
    # Sin enlace a una alerta que no se abre desde MOYZA
    assert f'href="/alerts/{rows[0]["alert_id"]}"' not in html


def test_alta_y_reasignacion_con_los_tres_grupos(ctx):
    from app.services import alert_assignment_service as svc

    groups = svc.assignable_agents(ctx.db, ctx.moyza.id)
    by_agent = {a.id: g["label"] for g in groups for a in g["agents"]}
    assert by_agent[ctx.agents["ana"].id] == "MOYZA"
    assert by_agent[ctx.agents["carla"].id] == "MOES PREMIUM"
    assert by_agent[ctx.agents["dual"].id] == "MOYZA, MOES PREMIUM"
    # Sin dados de baja; los de la empresa de la alerta primero
    assert ctx.agents["baja"].id not in by_agent
    labels = [g["label"] for g in groups]
    assert labels.index("MOYZA") < labels.index("MOYZA, MOES PREMIUM") < labels.index("MOES PREMIUM")


def test_ventana_sin_gestionar_nombra_al_agente_de_fuera_y_omite_bajas(ctx):
    from app.services.dashboard_service import DashboardService

    def rows(n):
        return [{"never_managed": True, "business_hours_elapsed": 30 + i, "reassigned": False} for i in range(n)]

    svc = DashboardService(ctx.db, ctx.moyza.id)
    raw = {
        (ctx.agents["ana"].id, ctx.moyza.id): rows(1),
        (ctx.agents["carla"].id, ctx.moyza.id): rows(2),   # de MOES, con alertas de MOYZA
        (ctx.agents["baja"].id, ctx.moyza.id): rows(1),    # dado de baja: fuera
        (ctx.agents["carla"].id, ctx.moes.id): rows(5),    # otra empresa: fuera
    }
    groups = {g["agent_id"]: g for g in svc.unmanaged_by_agent([ctx.agents["ana"]], raw=raw)}
    assert set(groups) == {ctx.agents["ana"].id, ctx.agents["carla"].id}
    assert groups[ctx.agents["carla"].id]["agent_name"] == f"{TAG} CARLA"
    assert groups[ctx.agents["carla"].id]["outside_company"] == "MOES PREMIUM"
    assert groups[ctx.agents["carla"].id]["count"] == 2
    assert groups[ctx.agents["ana"].id]["outside_company"] is None


def test_inicio_del_agente_en_dos_empresas_no_duplica_contactos(ctx):
    from app.services.dashboard_service import DashboardService

    dual = ctx.agents["dual"]
    _alert(ctx, dual, "moyza")
    _alert(ctx, dual, "moes")
    _alert(ctx, dual, "moes", business_type="Alquiler")

    home = DashboardService(ctx.db, [ctx.moyza.id, ctx.moes.id])
    week, month = home.current_periods()
    metrics = home.team_metrics([dual.id], week)[dual.id]
    assert (metrics["contactos_venta"], metrics["contactos_alquiler"]) == (2, 1)

    # Cada empresa por separado ve sus tres contactos (Rendimiento de MOYZA y de MOES)
    for company in (ctx.moyza, ctx.moes):
        alone = DashboardService(ctx.db, company.id).team_metrics([dual.id], week)[dual.id]
        assert (alone["contactos_venta"], alone["contactos_alquiler"]) == (2, 1)

    # KPI de contactos del Inicio y tendencia semanal, una sola vez
    block = home.agent_period_block(dual, month)
    contacts = next(k for k in block["activity_kpis"] if k.key == "contactos")
    assert contacts.value == 3
    trend = home.agent_trend(dual, week)
    series = next(s for s in trend.series if s.key == "contactos")
    assert series.data[-1] == 3


def test_suma_de_empresas_con_snapshots_antiguos_y_nuevos(ctx):
    from app.services.dashboard_service import DashboardService
    from app.services.performance_report_service import PerformanceReportService

    dual = ctx.agents["dual"]
    october = PerformanceReportService.period(PeriodType.MONTHLY, PAST_MONTH)
    home = DashboardService(ctx.db, [ctx.moyza.id, ctx.moes.id])

    # Antiguos (contactos solo de su empresa): se suman como antes
    old_moyza = _snapshot(ctx, dual, ctx.moyza, october, contactos=2)
    old_moes = _snapshot(ctx, dual, ctx.moes, october, contactos=3)
    assert home.team_metrics([dual.id], october)[dual.id]["contactos_venta"] == 5
    # Captaciones (por empresa) se suman siempre
    assert home.team_metrics([dual.id], october)[dual.id]["captaciones_crm"] == 2

    # Nuevos (contactos de cualquier empresa en cada uno): una sola vez
    for report in (old_moyza, old_moes):
        report.contactos_venta = 5
        report.contacts_all_companies = True
    ctx.db.flush()
    assert home.team_metrics([dual.id], october)[dual.id]["contactos_venta"] == 5
    assert home.team_metrics([dual.id], october)[dual.id]["captaciones_crm"] == 2


def test_sum_company_metrics_unitario():
    from app.services.performance_report_service import SOURCE_LIVE
    from app.services.performance_report_service import SOURCE_SNAPSHOT
    from app.services.performance_report_service import SOURCE_SNAPSHOT_COMPANY
    from app.services.performance_report_service import sum_company_metrics

    def m(contactos, captaciones=1):
        return {"contactos_venta": contactos, "contactos_alquiler": 0, "captaciones_crm": captaciones}

    assert sum_company_metrics([(m(3), SOURCE_LIVE), (m(3), SOURCE_LIVE)]) == m(3, 2)
    assert sum_company_metrics([(m(2), SOURCE_SNAPSHOT_COMPANY), (m(1), SOURCE_SNAPSHOT_COMPANY)]) == m(3, 2)
    # Un snapshot nuevo manda sobre el vivo y sobre los antiguos (ya los incluye)
    assert sum_company_metrics([(m(4), SOURCE_SNAPSHOT), (m(5), SOURCE_LIVE)])["contactos_venta"] == 4
    assert sum_company_metrics([(m(1), SOURCE_SNAPSHOT_COMPANY), (m(6), SOURCE_LIVE)])["contactos_venta"] == 6
    assert sum_company_metrics([(m(4), SOURCE_SNAPSHOT), (m(1), SOURCE_SNAPSHOT_COMPANY)])["contactos_venta"] == 4
    assert sum_company_metrics([(m(7), SOURCE_LIVE)]) == m(7)


def test_congelar_marca_la_regla_nueva(ctx):
    from app.services.performance_report_service import PerformanceReportService

    ana = ctx.agents["ana"]
    _alert(ctx, ana, "moes", created_at=datetime(2026, 10, 10, 10))
    svc = PerformanceReportService(ctx.db, ctx.moyza.id)
    october = svc.period(PeriodType.MONTHLY, PAST_MONTH)
    report = svc.freeze_report(ana.id, october.period_type, october.start, october.end)
    assert report.contacts_all_companies is True
    assert report.contactos_venta == 1


# ---------------------------------------------------------------------------
# Rutas (app levantada)
# ---------------------------------------------------------------------------

BASE_URL = os.getenv("MOYZA_TEST_BASE_URL", "http://localhost:8000")
ADMIN_EMAIL = os.getenv("MOYZA_TEST_ADMIN_EMAIL", "admin@moyza.com")


def _server_up() -> bool:
    try:
        urllib.request.urlopen(BASE_URL + "/", timeout=3)
        return True
    except Exception:
        return False


def _get(path, company="MOYZA"):
    from app.core.security import create_access_token

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    req = urllib.request.Request(BASE_URL + path)
    req.add_header("Cookie", f"access_token={create_access_token({'sub': ADMIN_EMAIL})}; active_company={company}")
    try:
        resp = urllib.request.build_opener(_NoRedirect).open(req, timeout=30)
        return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def _routes_cleanup(db):
    from app.models.agent import Agent

    db.rollback()
    db.query(Agent).filter(Agent.email.like(EMAIL.format("ruta%"))).delete(synchronize_session=False)
    db.commit()


@pytest.fixture(scope="module")
def routes_data():
    if not _server_up():
        pytest.skip(f"La app no responde en {BASE_URL}; tests de integración omitidos")
    from app.db.session import SessionLocal
    from app.models.agent import Agent
    from app.models.company import Company

    db = SessionLocal()
    _routes_cleanup(db)
    moyza = db.query(Company).filter_by(code="MOYZA").one()
    moes = db.query(Company).filter_by(code="MOES").one()
    agents = {}
    for key, companies, active in (("ruta_activo", [moyza], True), ("ruta_baja", [moyza], False),
                                   ("ruta_moes", [moes], True)):
        ag = Agent(name=f"{TAG} {key.upper()}", email=EMAIL.format(key), is_active=active)
        ag.companies.extend(companies)
        db.add(ag)
        agents[key] = ag
    db.commit()
    out = {key: ag.id for key, ag in agents.items()}
    yield out
    _routes_cleanup(db)
    db.close()


def _select(body, select_id) -> str:
    match = re.search(rf'<select[^>]*id="{select_id}".*?</select>', body, re.S)
    assert match, f"No está el select {select_id}"
    return match.group(0)


def test_filtro_de_alertas_sin_bajas_ni_agentes_de_moes(routes_data):
    status, body = _get("/alerts")
    assert status == 200
    select = _select(body, "alertAgentFilter")
    assert f'value="{routes_data["ruta_activo"]}"' in select
    assert f'value="{routes_data["ruta_baja"]}"' not in select
    assert f'value="{routes_data["ruta_moes"]}"' not in select
    assert "(baja)" not in select

    # El agente de MOES sí sale en el filtro de MOES
    status, body = _get("/alerts", company="MOES")
    assert f'value="{routes_data["ruta_moes"]}"' in _select(body, "alertAgentFilter")

    # Un enlace con el dado de baja sigue filtrando y se ve como chip
    status, body = _get(f"/alerts?agent_id={routes_data['ruta_baja']}")
    assert status == 200
    assert f"{TAG} RUTA_BAJA · dado de baja" in body
    status, body = _get(f"/alerts?agent_id={routes_data['ruta_moes']}")
    assert f"{TAG} RUTA_MOES · de MOES PREMIUM" in body


def test_historial_de_asignaciones_sin_bajas(routes_data):
    status, body = _get("/alerts/assignments")
    assert status == 200
    select = _select(body, "hAgent")
    assert f'value="{routes_data["ruta_activo"]}"' in select
    assert f'value="{routes_data["ruta_baja"]}"' not in select
    assert f'value="{routes_data["ruta_moes"]}"' not in select


def test_resultados_de_moyza_sin_el_agente_de_moes(routes_data):
    for tab in ("rendimiento", "evolucion"):
        status, body = _get(f"/commercial-results?tab={tab}")
        assert status == 200, tab
        assert f"{TAG} RUTA_ACTIVO" in body, tab
        assert f"{TAG} RUTA_MOES" not in body, tab
        assert f"{TAG} RUTA_BAJA" not in body, tab
    status, body = _get("/commercial-results?tab=evolucion")
    assert "(baja)" not in _select(body, "evo-agent")
