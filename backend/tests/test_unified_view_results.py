"""
Resultados del agente en la vista unificada (PLAN_VISTA_UNIFICADA_AGENTES.md, fase F).

Resultados Comerciales (`/commercial-results`, lupa y CSV) es **solo del admin**
(PLAN_RESULTADOS_COMERCIALES.md, PLAN_TRAZABILIDAD_INDICADORES.md: "nada para
agentes"). Los resultados del agente, con la suma de sus empresas (§5-3), son
los de su Inicio (fase C). Aquí se fija:

- El agente en vista unificada con dos empresas no entra en Resultados (ni
  pestañas, ni lupa, ni CSV, ni objetivos) y su Inicio ya no le enlaza ahí
  ("Ver histórico y año" lo devolvía a /alerts con un error).
- La suma del Inicio combina bien un snapshot congelado de una empresa con el
  cálculo en vivo de la otra, y une las observaciones del admin de las dos.
- El admin no cambia: Rendimiento, lupa y CSV por empresa activa, sin mezclar
  las cifras del agente de las dos empresas ni columna "Empresa".

Contra la base de datos real en una transacción que se deshace al terminar
(patrón de tests/test_unified_view_dashboard.py; se omiten sin conexión).

    docker exec moyza_backend python -m pytest tests/test_unified_view_results.py -q
"""
import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app.core.constants import PeriodType
from app.services.dashboard_service import DashboardService

EMAIL = "pytest.unificada.resultados@example.com"


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
    """Rita: agente en MOYZA y MOES, usuario en vista unificada."""
    from app.models.agent import Agent
    from app.models.company import Company
    from app.models.role import Role
    from app.models.user import User

    moyza = db.query(Company).filter_by(code="MOYZA").one()
    moes = db.query(Company).filter_by(code="MOES").one()
    agent_role = db.query(Role).filter(Role.name.ilike("agent")).first()
    admin = (
        db.query(User).join(Role, Role.id == User.role_id)
        .filter(Role.name.ilike("admin"), User.is_active.isnot(False)).order_by(User.id).first()
    )
    if agent_role is None or admin is None:
        pytest.skip("Faltan roles o un admin en la base de datos")

    rita = Agent(name="PYTEST-RES RITA", email=EMAIL)
    rita.companies.extend([moyza, moes])
    user = User(email=EMAIL, full_name="Rita Resultados", hashed_password="x", role_id=agent_role.id,
                is_active=True, company_switch_enabled=False)
    user.companies.extend([moyza, moes])
    db.add_all([rita, user])
    db.flush()
    db.refresh(user)
    return SimpleNamespace(db=db, moyza=moyza, moes=moes, rita=rita, user=user, admin=admin)


def _prop(ctx, company, entry, title, business_type="Venta"):
    from app.models.property import Property
    prop = Property(title=title, company_id=company.id, agent_id=ctx.rita.id, business_type=business_type,
                    market_entry_date=entry, status="Activa")
    ctx.db.add(prop)
    ctx.db.flush()
    return prop


def _report(ctx, company, period, locked=False, notes=None, **metrics):
    from app.models.agent_performance_report import AgentPerformanceReport
    report = AgentPerformanceReport(
        agent_id=ctx.rita.id, company_id=company.id, period_type=period.period_type,
        period_start=period.start, period_end=period.end, is_locked=locked,
        locked_at=datetime.utcnow() if locked else None, admin_notes=notes, **metrics,
    )
    ctx.db.add(report)
    ctx.db.flush()
    return report


def _request(ctx, user, path, cookie_company=None):
    """Petición con el estado de empresa que dejaría AuthMiddleware para `user`."""
    from app.web.dependencies.company import get_allowed_companies
    from app.web.dependencies.company import resolve_company_scope

    scope = resolve_company_scope(user, get_allowed_companies(user, ctx.db), cookie_company)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request({
        "type": "http", "method": "GET", "scheme": "http", "server": ("testserver", 80),
        "path": path, "root_path": "", "query_string": b"", "headers": [(b"host", b"testserver")],
        "state": {"user": user, "company": scope.company, "allowed_companies": scope.allowed,
                  "company_ids": scope.company_ids, "unified_view": scope.unified_view},
    }, receive)


def _results(ctx, user, tab, cookie_company=None, period_type=PeriodType.YEARLY):
    from app.web.routes.commercial_results import commercial_results
    return asyncio.run(commercial_results(
        _request(ctx, user, "/commercial-results", cookie_company), tab=tab, period_type=period_type,
        period_start="", year="", open_agent="", db=ctx.db,
    ))


def _metric(ctx, user, key, cookie_company=None, output=""):
    from app.web.routes.commercial_results import metric_detail
    path = f"/commercial-results/{ctx.rita.id}/metric/{key}"
    return asyncio.run(metric_detail(
        ctx.rita.id, key, _request(ctx, user, path, cookie_company), period_type=PeriodType.YEARLY,
        period_start="", offset=0, output=output, db=ctx.db,
    ))


def _dashboard(ctx, user, cookie_company=None):
    from app.web.routes.dashboard import dashboard
    response = asyncio.run(dashboard(_request(ctx, user, "/dashboard", cookie_company), period_type="",
                                     period_start="", db=ctx.db))
    return response, response.body.decode("utf-8")


# ---------------------------------------------------------------------------
# Agente en vista unificada: Resultados sigue siendo del admin
# ---------------------------------------------------------------------------

def test_agente_unificado_no_entra_en_resultados(ctx):
    from app.web.routes.commercial_results import save_notes
    from app.web.routes.commercial_results import save_targets

    assert _request(ctx, ctx.user, "/").state.unified_view is True
    for tab in ("rendimiento", "evolucion", "compradores", "cierres"):
        response = _results(ctx, ctx.user, tab)
        assert response.status_code == 302 and response.headers["location"] == "/alerts", tab

    for output in ("", "csv"):
        response = _metric(ctx, ctx.user, "captaciones_crm", output=output)
        assert response.status_code == 403, output

    for handler, extra in ((save_targets, {}), (save_notes, {"admin_notes": "x"})):
        request = _request(ctx, ctx.user, f"/commercial-results/{ctx.rita.id}/targets")
        response = asyncio.run(handler(ctx.rita.id, request, period_type="WEEKLY", period_start_str="",
                                       db=ctx.db, **extra))
        assert response.status_code == 302 and response.headers["location"] == "/alerts"


def test_inicio_del_agente_sin_enlace_a_resultados_y_admin_con_el(ctx):
    response, html = _dashboard(ctx, ctx.user)
    assert response.status_code == 200 and response.context["view"] == "agent"
    # Sus resultados están en el Inicio, con la cabecera de sus dos empresas
    assert "MOYZA y MOES PREMIUM ·" in html
    assert "/commercial-results" not in html and "Ver histórico y año" not in html

    response, html = _dashboard(ctx, ctx.admin, cookie_company="MOYZA")
    assert response.context["view"] == "admin"
    assert "Ver histórico y año" in html and 'href="/commercial-results?tab=rendimiento"' in html


# ---------------------------------------------------------------------------
# Suma del Inicio: snapshot congelado de una empresa + vivo de la otra
# ---------------------------------------------------------------------------

def test_snapshot_congelado_de_una_empresa_mas_vivo_de_la_otra(ctx):
    svc = DashboardService(ctx.db, [ctx.moyza.id, ctx.moes.id])
    week, _ = svc.current_periods()
    previous = svc.previous_period(week)
    entry = previous.start + timedelta(hours=1)
    # MOYZA: una captación en vivo, pero la semana está congelada con 5 (manda el snapshot)
    _prop(ctx, ctx.moyza, entry, "PYTEST-RES CAPT MOYZA")
    _report(ctx, ctx.moyza, previous, locked=True, captaciones_crm=5, captaciones_venta=4,
            captaciones_alquiler=1, bajadas=2, bajadas_venta=2, bajadas_alquiler=0)
    # MOES: sin snapshot, dos captaciones en vivo
    _prop(ctx, ctx.moes, entry, "PYTEST-RES CAPT MOES 1")
    _prop(ctx, ctx.moes, entry, "PYTEST-RES CAPT MOES 2", business_type="Alquiler")

    metrics = svc.team_metrics([ctx.rita.id], previous)[ctx.rita.id]
    assert metrics["captaciones_crm"] == 7
    assert metrics["captaciones_venta"] == 5 and metrics["captaciones_alquiler"] == 2
    assert metrics["bajadas"] == 2

    # Cada empresa por separado (lo que ve el admin) no mezcla
    assert DashboardService(ctx.db, ctx.moyza.id).team_metrics([ctx.rita.id], previous)[ctx.rita.id][
        "captaciones_crm"] == 5
    assert DashboardService(ctx.db, ctx.moes.id).team_metrics([ctx.rita.id], previous)[ctx.rita.id][
        "captaciones_crm"] == 2

    # El delta de la semana en curso del Inicio compara con esa suma
    block = svc.agent_period_block(ctx.rita, week)
    capt = next(k for k in block["objective_kpis"] if k.key == "captaciones_crm")
    assert capt.previous == 7


def test_observaciones_del_admin_de_las_dos_empresas_unidas(ctx):
    svc = DashboardService(ctx.db, [ctx.moyza.id, ctx.moes.id])
    week, _ = svc.current_periods()
    _report(ctx, ctx.moyza, week, notes="Buen ritmo de captación")
    assert svc.admin_notes(ctx.rita.id, week) == "Buen ritmo de captación"
    _report(ctx, ctx.moes, week, notes="Faltan bajadas")
    assert svc.admin_notes(ctx.rita.id, week) == "MOYZA: Buen ritmo de captación\n\nMOES PREMIUM: Faltan bajadas"
    # El admin, por empresa: solo la suya
    assert DashboardService(ctx.db, ctx.moes.id).admin_notes(ctx.rita.id, week) == "Faltan bajadas"


# ---------------------------------------------------------------------------
# Admin: Resultados por empresa activa, como siempre
# ---------------------------------------------------------------------------

def test_admin_rendimiento_lupa_y_csv_por_empresa_activa(ctx):
    entry = datetime.utcnow() - timedelta(minutes=5)
    _prop(ctx, ctx.moyza, entry, "PYTEST-RES CAPT MOYZA A")
    _prop(ctx, ctx.moyza, entry, "PYTEST-RES CAPT MOYZA B", business_type="Alquiler")
    _prop(ctx, ctx.moes, entry, "PYTEST-RES CAPT MOES")

    for code, expected in (("MOYZA", 2), ("MOES", 1)):
        response = _results(ctx, ctx.admin, "rendimiento", cookie_company=code)
        assert response.status_code == 200, code
        item = next(i for i in response.context["agents_data"] if i["agent"].id == ctx.rita.id)
        assert item["metrics"]["captaciones_crm"] == expected, code
        assert "MOYZA y MOES PREMIUM" not in response.body.decode("utf-8")

    response = _results(ctx, ctx.admin, "evolucion", cookie_company="MOES")
    assert response.status_code == 200

    response = _metric(ctx, ctx.admin, "captaciones_crm", cookie_company="MOYZA")
    html = response.body.decode("utf-8")
    assert response.status_code == 200
    assert "PYTEST-RES CAPT MOYZA A" in html and "PYTEST-RES CAPT MOES" not in html
    assert "en MOYZA y MOES PREMIUM" not in html

    response = _metric(ctx, ctx.admin, "captaciones_crm", cookie_company="MOES", output="csv")
    csv_text = response.body.decode("utf-8")
    header = csv_text.lstrip("﻿").splitlines()[0].split(";")
    assert "Empresa" not in header
    assert "PYTEST-RES CAPT MOES" in csv_text and "PYTEST-RES CAPT MOYZA" not in csv_text
