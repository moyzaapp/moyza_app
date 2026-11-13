"""
Propiedades, clientes e informes en la vista unificada del agente
(PLAN_VISTA_UNIFICADA_AGENTES.md, fase D).

- Un agente en MOYZA y MOES (sin "Puede cambiar de empresa") ve en "Mis
  propiedades" las suyas de las dos, con distintivo; el inventario sale en
  una pestaña "Resto de {empresa}" por cada una (sin "Propiedades de
  {otra}": las dos son suyas) y con la calle visible.
- Edita una propiedad de la empresa que no es su principal; cliente y
  captador tienen que ser de la empresa de la propiedad.
- El alta de propiedades y de clientes sigue siendo solo del admin, en la
  empresa activa.
- Clientes e informes: los de sus dos empresas, con distintivo.
- Con una sola empresa y para el admin, todo como antes.

Contra la base de datos real en una transacción que se deshace al terminar
(como tests/test_unified_view_dashboard.py; se omiten sin conexión).

    docker exec moyza_backend python -m pytest tests/test_unified_view_properties.py -q
"""
import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from starlette.requests import Request

from tests.test_alert_search import _flash

EMAIL = "pytest.unificada.prop@example.com"
SOLO_EMAIL = "pytest.unificada.prop.solo@example.com"
OTHER_EMAIL = "pytest.unificada.prop.otro@example.com"


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
    """Laura (MOYZA y MOES, vista unificada, principal MOYZA), Sol (solo MOYZA) y
    Otto (otro agente de las dos), con un cliente y una propiedad por empresa."""
    from app.models.agent import Agent
    from app.models.client import Client
    from app.models.company import Company
    from app.models.property import Property
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

    def agent(name, email, *companies):
        item = Agent(name=name, email=email)
        item.companies.extend(companies)
        return item

    def user(email, *companies):
        item = User(email=email, full_name=email.split("@")[0], hashed_password="x", role_id=agent_role.id,
                    is_active=True, company_switch_enabled=False, primary_company_id=companies[0].id)
        item.companies.extend(companies)
        return item

    def client(name, *companies):
        item = Client(name=name, phone="34600000000", status="Activo")
        item.companies.extend(companies)
        return item

    laura = agent("PYTEST-UPROP LAURA", EMAIL, moyza, moes)
    sol = agent("PYTEST-UPROP SOL", SOLO_EMAIL, moyza)
    otto = agent("PYTEST-UPROP OTTO", OTHER_EMAIL, moyza, moes)
    laura_user, sol_user = user(EMAIL, moyza, moes), user(SOLO_EMAIL, moyza)
    moyza_client, moes_client = client("PYTEST-UPROP CLIENTE MOYZA", moyza), client("PYTEST-UPROP CLIENTA MOES", moes)
    db.add_all([laura, sol, otto, laura_user, sol_user, moyza_client, moes_client])
    db.flush()

    def prop(title, company, owner, client_item, address):
        item = Property(title=title, company_id=company.id, agent_id=owner.id, client_id=client_item.id,
                        business_type="Venta", status="Activa", price=999999999, city="Jaén", address=address,
                        market_entry_date=datetime.utcnow() - timedelta(days=30))
        db.add(item)
        return item

    props = SimpleNamespace(
        laura_moyza=prop("PYTEST-UPROP PISO MOYZA", moyza, laura, moyza_client, "Calle Laura Moyza 1"),
        laura_moes=prop("PYTEST-UPROP ATICO MOES", moes, laura, moes_client, "Calle Laura Moes 2"),
        otto_moyza=prop("PYTEST-UPROP OTTO MOYZA", moyza, otto, moyza_client, "Calle Otto Moyza 3"),
        otto_moes=prop("PYTEST-UPROP OTTO MOES", moes, otto, moes_client, "Calle Otto Moes 4"),
    )
    db.flush()
    for item in (laura_user, sol_user):
        db.refresh(item)
    return SimpleNamespace(db=db, moyza=moyza, moes=moes, admin=admin, laura=laura, sol=sol, otto=otto,
                           user=laura_user, solo_user=sol_user, moyza_client=moyza_client,
                           moes_client=moes_client, props=props)


def _request(ctx, user, path, method="GET", form=None, cookie_company=None, query=""):
    """Petición con el estado de empresa que dejaría AuthMiddleware para `user`."""
    from app.web.dependencies.company import get_allowed_companies
    from app.web.dependencies.company import resolve_company_scope

    scope = resolve_company_scope(user, get_allowed_companies(user, ctx.db), cookie_company)
    body = urlencode(form or {}, doseq=True).encode()
    headers = [(b"host", b"testserver")]
    if form is not None:
        headers.append((b"content-type", b"application/x-www-form-urlencoded"))

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request({
        "type": "http", "method": method, "scheme": "http", "server": ("testserver", 80),
        "path": path, "root_path": "", "query_string": query.encode(), "headers": headers,
        "state": {"user": user, "company": scope.company, "allowed_companies": scope.allowed,
                  "company_ids": scope.company_ids, "unified_view": scope.unified_view},
    }, receive)


def _properties(ctx, user, tab="mine", company_id=None, cookie_company=None):
    from app.web.routes.properties import properties_page
    query = urlencode({"tab": tab, **({"company_id": company_id} if company_id else {})})
    request = _request(ctx, user, "/properties", cookie_company=cookie_company, query=query)
    response = asyncio.run(properties_page(request, tab=tab, filtro="activas", company_id=company_id,
                                           phone_country_code=None, phone_number=None,
                                           phone_country_code_other=None, db=ctx.db))
    return response, response.body.decode("utf-8")


def _update(ctx, user, prop, client_id=None, agent_id=None, title="PYTEST-UPROP EDITADA"):
    from app.web.routes.properties import update_property
    form = {"property_id": prop.id, "title": title, "price": "123000", "status": "Activa",
            "address": prop.address, "city": "Jaén", "description": "",
            "client_id": client_id or prop.client_id, "agent_id": agent_id or prop.agent_id}
    request = _request(ctx, user, "/properties/update", "POST", form=form)
    return asyncio.run(update_property(
        request, property_id=prop.id, title=title, price=123000.0, client_id=form["client_id"],
        agent_id=form["agent_id"], address=prop.address, city="Jaén", description="", status="Activa",
        auto_send_report=False, report_frequency=None, report_day=None, report_hour=None, db=ctx.db,
    ))


def _tab_labels(response):
    """Etiquetas de la barra de pestañas (lo que se pinta con ui.tabs)."""
    html = response.body.decode("utf-8")
    start = html.find('id="propertyTabs"')
    return html[start:html.find("</nav>", start)]


# ---------------------------------------------------------------------------
# Listado y pestañas
# ---------------------------------------------------------------------------

def test_mis_propiedades_de_las_dos_empresas_con_distintivo(ctx):
    response, html = _properties(ctx, ctx.user, cookie_company="MOES")
    assert response.status_code == 200
    titles = {p.title for p in response.context["properties"]}
    assert titles == {"PYTEST-UPROP PISO MOYZA", "PYTEST-UPROP ATICO MOES"}
    assert 'title="Propiedad de MOES PREMIUM"' in html and 'title="Propiedad de MOYZA"' in html
    # Pestañas: un "Resto de {empresa}" por cada una y ninguna "Propiedades de {otra}"
    tabs = _tab_labels(response)
    assert "Resto de MOYZA" in tabs and "Resto de MOES PREMIUM" in tabs
    assert "Propiedades de MOES PREMIUM" not in tabs and "Resto de propiedades" not in tabs
    assert response.context["other_company_tabs"] == []
    # El formulario de edición trae clientes y agentes de las dos, con su empresa
    assert f'data-company-id="{ctx.moes.id}"' in html
    assert f'data-companies="{ctx.moes.id}"' in html and f'data-companies="{ctx.moyza.id}"' in html


def test_resto_por_empresa_con_calle(ctx):
    response, html = _properties(ctx, ctx.user, tab="others", company_id=ctx.moes.id)
    rows = {r["title"]: r for r in response.context["other_properties"]}
    assert "PYTEST-UPROP OTTO MOES" in rows and "PYTEST-UPROP OTTO MOYZA" not in rows
    assert "PYTEST-UPROP ATICO MOES" not in rows   # la suya no es "resto"
    assert rows["PYTEST-UPROP OTTO MOES"]["address"] == "Calle Otto Moes 4"
    assert response.context["selected_others_company"].id == ctx.moes.id
    assert "inventario general de MOES PREMIUM" in html
    assert f'name="company_id" value="{ctx.moes.id}"' in html   # el buscador conserva la pestaña

    # Sin empresa: la primera (MOYZA)
    response, _ = _properties(ctx, ctx.user, tab="others")
    rows = {r["title"] for r in response.context["other_properties"]}
    assert "PYTEST-UPROP OTTO MOYZA" in rows and "PYTEST-UPROP OTTO MOES" not in rows


def test_agente_de_una_empresa_sin_cambios(ctx):
    response, html = _properties(ctx, ctx.solo_user)
    assert response.context["properties"] == []
    tabs = _tab_labels(response)
    assert "Resto de propiedades" in tabs and "Propiedades de MOES PREMIUM" in tabs
    assert "Resto de MOYZA" not in tabs
    assert 'title="Propiedad de' not in html and "data-companies=" not in html


def test_admin_sin_cambios(ctx):
    response, html = _properties(ctx, ctx.admin, cookie_company="MOYZA")
    titles = {p.title for p in response.context["properties"]}
    assert "PYTEST-UPROP PISO MOYZA" in titles and "PYTEST-UPROP ATICO MOES" not in titles
    tabs = _tab_labels(response)
    assert "Propiedades de MOES PREMIUM" in tabs and "Resto de" not in tabs
    assert 'title="Propiedad de' not in html and "data-companies=" not in html


# ---------------------------------------------------------------------------
# Edición y alta
# ---------------------------------------------------------------------------

def test_edita_la_propiedad_de_la_empresa_que_no_es_la_principal(ctx):
    prop = ctx.props.laura_moes
    response = _update(ctx, ctx.user, prop)
    assert response.status_code == 302 and _flash(response)["category"] == "success"
    ctx.db.refresh(prop)
    assert prop.title == "PYTEST-UPROP EDITADA" and prop.company_id == ctx.moes.id

    # Cliente de otra empresa que la de la propiedad: error y nada cambia
    response = _update(ctx, ctx.user, prop, client_id=ctx.moyza_client.id, title="PYTEST-UPROP MAL")
    flash = _flash(response)
    assert flash["category"] == "error" and flash["message"] == "El cliente seleccionado no pertenece a MOES PREMIUM"
    # Captador que no está en la empresa de la propiedad
    response = _update(ctx, ctx.user, prop, agent_id=ctx.sol.id, title="PYTEST-UPROP MAL")
    assert _flash(response)["message"] == "El agente seleccionado no pertenece a MOES PREMIUM"
    ctx.db.refresh(prop)
    assert prop.title == "PYTEST-UPROP EDITADA"


def test_vista_por_empresa_no_edita_la_de_la_otra(ctx):
    ctx.user.company_switch_enabled = True
    ctx.db.flush()
    response = _update(ctx, ctx.user, ctx.props.laura_moes)
    assert _flash(response)["message"] == "Propiedad no encontrada"


def test_alta_de_propiedad_sigue_siendo_del_admin_en_la_activa(ctx):
    from app.models.property import Property
    from app.web.routes.properties import create_property

    def create(user, cookie_company, title):
        form = {"title": title, "address": "Calle Alta 1", "city": "Jaén", "price": "1000", "description": "x",
                "client_id": ctx.moes_client.id, "agent_id": ctx.otto.id}
        request = _request(ctx, user, "/properties/create", "POST", form=form, cookie_company=cookie_company)
        return asyncio.run(create_property(request, title=title, address="Calle Alta 1", city="Jaén",
                                           price=1000.0, description="x", client_id=ctx.moes_client.id,
                                           agent_id=ctx.otto.id, db=ctx.db))

    response = create(ctx.user, None, "PYTEST-UPROP ALTA AGENTE")
    assert _flash(response)["message"] == "No tienes permisos para realizar esta acción."
    assert ctx.db.query(Property).filter_by(title="PYTEST-UPROP ALTA AGENTE").first() is None

    # El admin crea en la activa; con MOYZA activa, un cliente de MOES no vale
    response = create(ctx.admin, "MOYZA", "PYTEST-UPROP ALTA ADMIN")
    assert _flash(response)["message"] == "El cliente seleccionado no pertenece a MOYZA"
    response = create(ctx.admin, "MOES", "PYTEST-UPROP ALTA ADMIN")
    assert _flash(response)["category"] == "success"
    assert ctx.db.query(Property).filter_by(title="PYTEST-UPROP ALTA ADMIN").one().company_id == ctx.moes.id


# ---------------------------------------------------------------------------
# Clientes e informes
# ---------------------------------------------------------------------------

def test_clientes_de_las_dos_empresas(ctx):
    from app.web.routes.clients import clients_page

    response = asyncio.run(clients_page(_request(ctx, ctx.user, "/clients"), db=ctx.db))
    html = response.body.decode("utf-8")
    names = {c.name for c in response.context["clients"]}
    assert names == {"PYTEST-UPROP CLIENTE MOYZA", "PYTEST-UPROP CLIENTA MOES"}
    assert 'title="Propiedad de MOES PREMIUM"' in html
    # Solo sus propiedades en la columna de dirección
    shown = {p.id for props in response.context["properties_by_client"].values() for p in props}
    assert shown == {ctx.props.laura_moyza.id, ctx.props.laura_moes.id}

    response = asyncio.run(clients_page(_request(ctx, ctx.admin, "/clients", cookie_company="MOYZA"), db=ctx.db))
    names = {c.name for c in response.context["clients"]}
    assert "PYTEST-UPROP CLIENTE MOYZA" in names and "PYTEST-UPROP CLIENTA MOES" not in names
    assert 'title="Propiedad de' not in response.body.decode("utf-8")


def test_informes_de_las_dos_empresas(ctx):
    from app.models.report import Report
    from app.web.routes.reports import download_report, reports_page

    report = Report(property_id=ctx.props.laura_moes.id, report_type="GENERAL", filename="x.pdf",
                    filepath="/no/existe/x.pdf")
    ctx.db.add(report)
    ctx.db.flush()

    response = asyncio.run(reports_page(_request(ctx, ctx.user, "/reports"), db=ctx.db))
    html = response.body.decode("utf-8")
    assert report.id in {r.id for r in response.context["reports"]}
    assert {p.id for p in response.context["properties"]} == {ctx.props.laura_moyza.id, ctx.props.laura_moes.id}
    assert 'title="Propiedad de MOES PREMIUM"' in html
    assert "PYTEST-UPROP ATICO MOES · MOES PREMIUM" in html

    # El informe de MOES existe para ella (falta el archivo, no el informe)
    response = asyncio.run(download_report(report.id, _request(ctx, ctx.user, "/reports/download"), db=ctx.db))
    assert _flash(response)["message"] == "Archivo del informe no encontrado en el servidor"
    # Para el admin con MOYZA activa no existe
    response = asyncio.run(download_report(report.id, _request(ctx, ctx.admin, "/reports/download",
                                                               cookie_company="MOYZA"), db=ctx.db))
    assert _flash(response)["message"] == "Informe no encontrado"
