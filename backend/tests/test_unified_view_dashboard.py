"""
Inicio y notificaciones en la vista unificada del agente
(PLAN_VISTA_UNIFICADA_AGENTES.md, fase C).

- Un agente en MOYZA y MOES (sin "Puede cambiar de empresa") ve en el Inicio
  la suma de sus empresas: KPIs de actividad, objetivos (suma de los de cada
  empresa; si solo hay en una, ese), agenda y compradores de las dos con
  distintivo, cartera de las dos y tendencia sumada.
- Campana, contador, /notifications y "Novedades": las de sus dos empresas,
  con distintivo.
- Con una sola empresa o con `company_switch_enabled`, y para el admin, todo
  sigue siendo de la empresa activa.

Contra la base de datos real en una transacción que se deshace al terminar
(patrón de tests/test_dashboard_service.py; se omiten sin conexión). Las
rutas se llaman en proceso con el estado de empresa que dejaría el
middleware (`resolve_company_scope`).

    docker exec moyza_backend python -m pytest tests/test_unified_view_dashboard.py -q
"""
import asyncio
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app.services.dashboard_service import DashboardService

EMAIL = "pytest.unificada.inicio@example.com"
SOLO_EMAIL = "pytest.unificada.solo@example.com"


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
    """Laura (agente en MOYZA y MOES, usuario en vista unificada) y Sol (solo MOYZA)."""
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

    laura = Agent(name="PYTEST-UNIF LAURA", email=EMAIL)
    laura.companies.extend([moyza, moes])
    sol = Agent(name="PYTEST-UNIF SOL", email=SOLO_EMAIL)
    sol.companies.append(moyza)
    user = User(email=EMAIL, full_name="Laura Unificada", hashed_password="x", role_id=agent_role.id,
                is_active=True, company_switch_enabled=False)
    user.companies.extend([moyza, moes])
    solo_user = User(email=SOLO_EMAIL, full_name="Sol Solo", hashed_password="x", role_id=agent_role.id,
                     is_active=True, company_switch_enabled=False)
    solo_user.companies.append(moyza)
    db.add_all([laura, sol, user, solo_user])
    db.flush()
    db.refresh(user)
    db.refresh(solo_user)
    return SimpleNamespace(db=db, moyza=moyza, moes=moes, laura=laura, sol=sol, user=user,
                           solo_user=solo_user, admin=admin)


def _prop(ctx, company, agent, entry, business_type="Venta", title="PYTEST-UNIF PROP"):
    from app.models.property import Property
    prop = Property(title=title, company_id=company.id, agent_id=agent.id, business_type=business_type,
                    market_entry_date=entry, status="Activa")
    ctx.db.add(prop)
    ctx.db.flush()
    return prop


def _target(ctx, company, period, **values):
    from app.models.agent_performance_target import AgentPerformanceTarget
    ctx.db.add(AgentPerformanceTarget(agent_id=ctx.laura.id, company_id=company.id, period_type=period.period_type,
                                      period_start=period.start, created_by=ctx.admin.id, **values))
    ctx.db.flush()


def _alert(ctx, company, name, created_at, prop=None, status="IN_PROGRESS"):
    from app.models.property_alert import PropertyAlert
    alert = PropertyAlert(company_id=company.id, property_id=prop.id if prop else None, agent_id=ctx.laura.id,
                          lead_name=name, business_type="Venta", status=status, priority="NORMAL",
                          origin="search" if prop is None else "property", created_by=ctx.admin.id,
                          created_at=created_at, assigned_at=created_at, read_at=created_at)
    ctx.db.add(alert)
    ctx.db.flush()
    return alert


def _notify(ctx, user, company, title):
    from app.services import notification_service as ns
    ns.notify(ctx.db, users=[user], company_id=company.id, kind="admin_note_added", title=title, url="/dashboard")
    ctx.db.flush()


def _request(ctx, user, path, cookie_company=None, cookies=None):
    """Petición con el estado de empresa que dejaría AuthMiddleware para `user`."""
    from app.web.dependencies.company import get_allowed_companies
    from app.web.dependencies.company import resolve_company_scope

    scope = resolve_company_scope(user, get_allowed_companies(user, ctx.db), cookie_company)
    headers = [(b"host", b"testserver")]
    if cookies:
        headers.append((b"cookie", "; ".join(f"{k}={v}" for k, v in cookies.items()).encode()))

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request({
        "type": "http", "method": "GET", "scheme": "http", "server": ("testserver", 80),
        "path": path, "root_path": "", "query_string": b"", "headers": headers,
        "state": {"user": user, "company": scope.company, "allowed_companies": scope.allowed,
                  "company_ids": scope.company_ids, "unified_view": scope.unified_view},
    }, receive)


def _dashboard(ctx, user, cookie_company=None):
    from app.web.routes.dashboard import dashboard
    response = asyncio.run(dashboard(_request(ctx, user, "/dashboard", cookie_company), period_type="",
                                     period_start="", db=ctx.db))
    return response, response.body.decode("utf-8")


# ---------------------------------------------------------------------------
# Servicio: suma de empresas
# ---------------------------------------------------------------------------

def test_kpis_y_objetivos_sumados_entre_empresas(ctx):
    svc = DashboardService(ctx.db, [ctx.moyza.id, ctx.moes.id])
    week, month = svc.current_periods()
    entry = max(week.start, month.start) + timedelta(minutes=5)
    # Captaciones: 2 en MOYZA y 1 en MOES esta semana
    _prop(ctx, ctx.moyza, ctx.laura, entry)
    _prop(ctx, ctx.moyza, ctx.laura, entry, business_type="Alquiler")
    _prop(ctx, ctx.moes, ctx.laura, entry)
    # Contactos: uno en cada empresa
    _alert(ctx, ctx.moyza, "PYTEST-UNIF C1", entry)
    _alert(ctx, ctx.moes, "PYTEST-UNIF C2", entry)
    # Objetivo semanal en las dos (se suman) y mensual solo en MOES (ese)
    _target(ctx, ctx.moyza, week, target_captaciones_crm=4, target_bajadas=1)
    _target(ctx, ctx.moes, week, target_captaciones_crm=2)
    _target(ctx, ctx.moes, month, target_captaciones_crm=10, target_cierres=3)

    home = svc.agent_home(ctx.laura, week=week, month=month)
    kpis = {k.key: k for k in home["week"]["objective_kpis"] + home["week"]["activity_kpis"]}
    assert kpis["captaciones_crm"].value == 3
    assert kpis["captaciones_crm"].breakdown == {"venta": 2, "alquiler": 1, "otros": 0}
    assert kpis["captaciones_crm"].target == 6 and kpis["captaciones_crm"].pct == 50
    assert kpis["bajadas"].target == 1
    assert kpis["contactos"].value == 2
    assert home["week"]["has_target"] is True

    month_kpis = {k.key: k for k in home["month"]["objective_kpis"]}
    assert month_kpis["captaciones_crm"].target == 10 and month_kpis["cierres"].target == 3

    # La cartera es la de las dos empresas
    assert home["portfolio"]["total"] == 3
    # Tendencia: los dos contactos en la última semana
    contacts = next(s for s in home["trend"].series if s.key == "contactos")
    assert contacts.data[-1] == 2

    # Cada empresa por separado no mezcla
    only_moes = DashboardService(ctx.db, ctx.moes.id).agent_home(ctx.laura, week=week, month=month)
    capt = next(k for k in only_moes["week"]["objective_kpis"] if k.key == "captaciones_crm")
    assert capt.value == 1 and capt.target == 2
    assert only_moes["portfolio"]["total"] == 1


def test_agenda_y_compradores_de_las_dos_empresas_con_distintivo(ctx):
    from app.models.alert_follow_up import AlertFollowUp

    svc = DashboardService(ctx.db, [ctx.moyza.id, ctx.moes.id])
    now = datetime.utcnow()
    moyza_alert = _alert(ctx, ctx.moyza, "PYTEST-UNIF AGENDA MOYZA", now - timedelta(days=3))
    moes_alert = _alert(ctx, ctx.moes, "PYTEST-UNIF AGENDA MOES", now - timedelta(days=3))
    for alert in (moyza_alert, moes_alert):
        ctx.db.add(AlertFollowUp(alert_id=alert.id, action_type="CONTACTADO", created_by=ctx.admin.id,
                                 created_at=now - timedelta(days=2), next_action_date=now - timedelta(days=1)))
    ctx.db.flush()

    agenda = svc.agenda(ctx.laura)
    rows = {row["alert_id"]: row for row in agenda["due"]}
    assert set(rows) == {moyza_alert.id, moes_alert.id}
    assert rows[moes_alert.id]["company"].id == ctx.moes.id
    assert rows[moyza_alert.id]["company"].id == ctx.moyza.id

    # Con una sola empresa, sin distintivo y solo la suya
    single = DashboardService(ctx.db, ctx.moyza.id).agenda(ctx.laura)
    assert [row["alert_id"] for row in single["due"]] == [moyza_alert.id]
    assert single["due"][0]["company"] is None


def test_compradores_que_requieren_atencion_de_las_dos_empresas(ctx):
    long_ago = datetime.utcnow() - timedelta(days=10)
    _alert(ctx, ctx.moyza, "PYTEST-UNIF SIN GESTION MOYZA", long_ago, status="PENDING")
    _alert(ctx, ctx.moes, "PYTEST-UNIF SIN GESTION MOES", long_ago, status="PENDING")

    pending = DashboardService(ctx.db, [ctx.moyza.id, ctx.moes.id]).pending_buyers_for_agent(ctx.laura.id)
    names = {b["buyer_name"]: b["company"].code for b in pending if b["buyer_name"].startswith("PYTEST-UNIF")}
    assert names == {"PYTEST-UNIF SIN GESTION MOYZA": "MOYZA", "PYTEST-UNIF SIN GESTION MOES": "MOES"}

    single = DashboardService(ctx.db, ctx.moes.id).pending_buyers_for_agent(ctx.laura.id)
    assert [b["buyer_name"] for b in single] == ["PYTEST-UNIF SIN GESTION MOES"]
    assert single[0]["company"] is None


# ---------------------------------------------------------------------------
# Rutas: Inicio y notificaciones
# ---------------------------------------------------------------------------

def test_inicio_del_agente_en_dos_empresas(ctx):
    now = datetime.utcnow()
    _prop(ctx, ctx.moyza, ctx.laura, now - timedelta(days=400), title="PYTEST-UNIF CARTERA MOYZA")
    _prop(ctx, ctx.moes, ctx.laura, now - timedelta(days=400), title="PYTEST-UNIF CARTERA MOES")
    _notify(ctx, ctx.user, ctx.moyza, "PYTEST-UNIF aviso MOYZA")
    _notify(ctx, ctx.user, ctx.moes, "PYTEST-UNIF aviso MOES")

    response, html = _dashboard(ctx, ctx.user, cookie_company="MOES")
    assert response.status_code == 200
    assert response.context["view"] == "agent"
    home = response.context["home"]
    assert home["portfolio"]["total"] == 2
    assert home["news_unread"] == 2
    # Novedades de las dos, con distintivo
    assert "PYTEST-UNIF aviso MOYZA" in html and "PYTEST-UNIF aviso MOES" in html
    assert 'title="Aviso de MOES PREMIUM"' in html and 'title="Aviso de MOYZA"' in html
    # Cabecera con las dos empresas y sidebar sin selector
    assert "MOYZA y MOES PREMIUM ·" in html
    assert 'action="/switch-company"' not in html
    # Propiedades sin visitas de las dos, con distintivo
    assert "PYTEST-UNIF CARTERA MOES" in html and 'title="Propiedad de MOES PREMIUM"' in html


def test_agente_de_una_empresa_y_vista_por_empresa_sin_cambios(ctx):
    _notify(ctx, ctx.solo_user, ctx.moyza, "PYTEST-UNIF aviso SOL")
    response, html = _dashboard(ctx, ctx.solo_user)
    assert response.status_code == 200 and response.context["view"] == "agent"
    assert "PYTEST-UNIF aviso SOL" in html
    assert 'title="Aviso de' not in html and "MOYZA y MOES PREMIUM" not in html

    # Laura con "Puede cambiar de empresa": solo la activa
    ctx.user.company_switch_enabled = True
    _notify(ctx, ctx.user, ctx.moes, "PYTEST-UNIF aviso MOES")
    response, html = _dashboard(ctx, ctx.user, cookie_company="MOYZA")
    assert response.context["view"] == "agent"
    assert "PYTEST-UNIF aviso MOES" not in html and 'title="Aviso de' not in html
    response, html = _dashboard(ctx, ctx.user, cookie_company="MOES")
    assert "PYTEST-UNIF aviso MOES" in html


def test_admin_sin_cambios(ctx):
    _prop(ctx, ctx.moes, ctx.laura, datetime.utcnow() - timedelta(minutes=5), title="PYTEST-UNIF CAPTACION MOES")
    response, html = _dashboard(ctx, ctx.admin, cookie_company="MOYZA")
    assert response.status_code == 200 and response.context["view"] == "admin"
    assert "PYTEST-UNIF CAPTACION MOES" not in html
    assert "MOYZA ·" in html and "MOYZA y MOES PREMIUM" not in html
    response, html = _dashboard(ctx, ctx.admin, cookie_company="MOES")
    assert "PYTEST-UNIF CAPTACION MOES" in html


def test_campana_y_pagina_de_notificaciones_con_las_dos_empresas(ctx):
    from app.core.security import create_access_token
    from app.models.notification import Notification
    from app.web.routes import notifications as routes

    _notify(ctx, ctx.user, ctx.moyza, "PYTEST-UNIF campana MOYZA")
    _notify(ctx, ctx.user, ctx.moes, "PYTEST-UNIF campana MOES")
    cookies = {"access_token": create_access_token({"sub": EMAIL}), "active_company": "MOYZA"}

    def api(handler, **kwargs):
        return asyncio.run(handler(_request(ctx, ctx.user, "/api/notifications", cookies=cookies), db=ctx.db, **kwargs))

    assert api(routes.api_unread_count) == {"unread_count": 2}
    recent = api(routes.api_recent, limit=8)
    by_title = {i["title"]: i for i in recent["items"]}
    assert by_title["PYTEST-UNIF campana MOES"]["company"]["name"] == "MOES PREMIUM"
    assert by_title["PYTEST-UNIF campana MOYZA"]["company"]["name"] == "MOYZA"

    page = asyncio.run(routes.notifications_page(_request(ctx, ctx.user, "/notifications"), status="all", page=1,
                                                 db=ctx.db))
    html = page.body.decode("utf-8")
    assert "PYTEST-UNIF campana MOES" in html and "PYTEST-UNIF campana MOYZA" in html
    assert "Avisos de MOYZA y MOES PREMIUM" in html and 'title="Aviso de MOES PREMIUM"' in html

    # Abrir la de la otra empresa la marca leída
    moes_id = ctx.db.query(Notification.id).filter_by(title="PYTEST-UNIF campana MOES").scalar()
    opened = asyncio.run(routes.open_notification(moes_id, _request(ctx, ctx.user, "/notifications"), db=ctx.db))
    assert opened.status_code == 302 and opened.headers["location"] == "/dashboard"
    assert api(routes.api_unread_count) == {"unread_count": 1}

    # Con "Puede cambiar de empresa", solo la activa y sin distintivo
    ctx.user.company_switch_enabled = True
    ctx.db.flush()
    recent = api(routes.api_recent, limit=8)
    assert [i["title"] for i in recent["items"]] == ["PYTEST-UNIF campana MOYZA"]
    assert recent["items"][0]["company"] is None
    assert json.dumps(recent)  # serializable
