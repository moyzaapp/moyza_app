"""
Visitas a propiedades de cualquier empresa (PLAN_VISITAS_OTRA_EMPRESA.md,
fase E de PLAN_VISTA_UNIFICADA_AGENTES.md).

- Selector: "Mis propiedades" y una sección por empresa activa (también las
  que no son del usuario), con distintivo; la calle de una propiedad de otra
  empresa solo para quien pertenece a ella o el admin.
- Alta: un agente solo de MOYZA registra una visita a una propiedad de MOES
  PREMIUM; la visita queda en MOYZA y el principal se valida contra MOYZA.
  Un agente en las dos elige la empresa de la visita.
- Ficha PDF y vista previa con la marca de la visita y la línea "Inmueble
  comercializado por {empresa de la propiedad}".
- La empresa de la propiedad la ve en solo lectura (ficha de la propiedad y
  /visits); cuenta en "Hojas de visita" de la empresa de la visita.
- El admin con selector, sin cambios.

Contra la base de datos real en una transacción que se deshace al terminar
(como tests/test_unified_view_properties.py; se omiten sin conexión).

    docker exec moyza_backend python -m pytest tests/test_visits_cross_company.py -q
"""
import asyncio
from types import SimpleNamespace

import pytest

from tests.test_alert_search import _flash
from tests.test_unified_view_properties import _request

MIA_EMAIL = "pytest.cruzada.mia@example.com"      # solo MOYZA
TEO_EMAIL = "pytest.cruzada.teo@example.com"      # solo MOES (captador)
VERA_EMAIL = "pytest.cruzada.vera@example.com"    # MOYZA y MOES


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
    from app.models.agent import Agent
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

    mia = agent("PYTEST-CRUZ MIA", MIA_EMAIL, moyza)
    teo = agent("PYTEST-CRUZ TEO", TEO_EMAIL, moes)
    vera = agent("PYTEST-CRUZ VERA", VERA_EMAIL, moyza, moes)
    users = SimpleNamespace(mia=user(MIA_EMAIL, moyza), teo=user(TEO_EMAIL, moes), vera=user(VERA_EMAIL, moyza, moes))
    db.add_all([mia, teo, vera, users.mia, users.teo, users.vera])
    db.flush()

    def prop(title, company, owner, address, status="Activa"):
        item = Property(title=title, company_id=company.id, agent_id=owner.id, business_type="Venta",
                        status=status, price=999999999, city="Jaén", zona="Centro", address=address)
        db.add(item)
        return item

    props = SimpleNamespace(
        moes=prop("PYTEST-CRUZ ATICO MOES", moes, teo, "Calle Secreta Moes 7"),
        moes_paused=prop("PYTEST-CRUZ PAUSADA MOES", moes, teo, "Calle Pausada Moes 8", status="Pausada"),
        moyza=prop("PYTEST-CRUZ PISO MOYZA", moyza, mia, "Calle Mia Moyza 1"),
    )
    db.flush()
    for item in (users.mia, users.teo, users.vera):
        db.refresh(item)
    return SimpleNamespace(db=db, moyza=moyza, moes=moes, admin=admin, mia=mia, teo=teo, vera=vera,
                           users=users, props=props)


@pytest.fixture(autouse=True)
def no_side_effects(monkeypatch):
    """Sin auditoría (no es el objeto de estos tests)."""
    import app.services.visit_audit_service as audit
    monkeypatch.setattr(audit, "log_visit_event", lambda **k: None)


def _html(response):
    return response.body.decode("utf-8")


def _select(ctx, user, cookie_company=None):
    from app.web.routes.visits import select_property
    request = _request(ctx, user, "/visits/select-property", cookie_company=cookie_company)
    return asyncio.run(select_property(request, db=ctx.db))


def _new(ctx, user, prop, cookie_company=None):
    from app.web.routes.visits import new_visit
    request = _request(ctx, user, f"/visits/new/{prop.id}", cookie_company=cookie_company)
    return asyncio.run(new_visit(prop.id, request, db=ctx.db))


def _create(ctx, user, prop, cookie_company=None, name="PYTEST-CRUZ VISITANTE", **extra):
    from app.web.routes.visits import create_visit
    form = {"visitor_name": name, "phone_country_code": "34", "phone_number": "600000001",
            "purchase_fees": "2500", "notes": "nota interna", "generate_sheet": "true", **extra}
    request = _request(ctx, user, f"/visits/create/{prop.id}", "POST", form=form, cookie_company=cookie_company)
    return asyncio.run(create_visit(prop.id, request, db=ctx.db))


def _visit(ctx, name="PYTEST-CRUZ VISITANTE"):
    from app.models.property_visit import PropertyVisit
    return ctx.db.query(PropertyVisit).filter_by(visitor_name=name).one_or_none()


def _section(response, title):
    for section in response.context["sections"]:
        if section["title"] == title:
            return section
    raise AssertionError(f"Sin sección {title}: {[s['title'] for s in response.context['sections']]}")


# ---------------------------------------------------------------------------
# Selector de propiedad
# ---------------------------------------------------------------------------

def test_selector_con_una_seccion_por_empresa(ctx):
    response = _select(ctx, ctx.users.mia)
    html = _html(response)
    titles = [s["title"] for s in response.context["sections"]]
    assert titles == ["Mis propiedades", "Otras propiedades de MOYZA", "Propiedades de MOES PREMIUM"]
    assert ctx.props.moyza in _section(response, "Mis propiedades")["properties"]
    moes = _section(response, "Propiedades de MOES PREMIUM")
    assert ctx.props.moes in moes["properties"]
    # De la otra empresa, solo el inventario activo
    assert ctx.props.moes_paused not in moes["properties"]
    # Distintivo y calle oculta (Mia no pertenece a MOES): ni se pinta ni se busca
    assert 'title="Propiedad de MOES PREMIUM"' in html
    assert moes["show_street"] is False
    assert "Calle Secreta Moes" not in html and "calle secreta moes" not in html
    assert "La visita se registra en MOYZA" in html


def test_selector_calle_visible_para_quien_pertenece_y_admin(ctx):
    response = _select(ctx, ctx.users.vera)
    titles = [s["title"] for s in response.context["sections"]]
    assert titles == ["Mis propiedades", "Otras propiedades de MOYZA", "Otras propiedades de MOES PREMIUM"]
    assert "Calle Secreta Moes 7" in _html(response)

    response = _select(ctx, ctx.admin, cookie_company="MOYZA")
    titles = [s["title"] for s in response.context["sections"]]
    assert titles == ["Propiedades de MOYZA", "Propiedades de MOES PREMIUM"]
    assert "Calle Secreta Moes 7" in _html(response)


# ---------------------------------------------------------------------------
# Alta cruzada
# ---------------------------------------------------------------------------

def test_formulario_avisa_de_la_propiedad_de_otra_empresa(ctx):
    response = _new(ctx, ctx.users.mia, ctx.props.moes)
    assert response.status_code == 200
    html = _html(response)
    assert "Propiedad de <span class=\"font-medium\">MOES PREMIUM</span>: la visita se registra en" in html
    assert '<span class="font-medium" id="crossCompanyVisitName">MOYZA</span>' in html
    # Calle oculta, sin select de empresa (Mia solo está en MOYZA) y "Volver" al selector
    assert "Calle Secreta Moes" not in html
    assert 'name="visit_company_id"' not in html
    assert "Volver a seleccionar propiedad" in html


def test_agente_de_moyza_registra_visita_a_propiedad_de_moes(ctx, monkeypatch):
    import app.web.routes.visits as visits_routes
    notified = []
    monkeypatch.setattr(visits_routes, "notify_visit_created", lambda db, visit, actor=None: notified.append(visit))

    response = _create(ctx, ctx.users.mia, ctx.props.moes)
    assert response.status_code == 302 and "/visits/preview/" in response.headers["location"]
    visit = _visit(ctx)
    assert visit.company_id == ctx.moyza.id and visit.property.company_id == ctx.moes.id
    assert visit.agent_id == ctx.mia.id and visit.is_cross_company
    # El aviso al captador se manda como siempre
    assert notified == [visit]


def test_pausada_de_otra_empresa_no_se_visita(ctx):
    response = _create(ctx, ctx.users.mia, ctx.props.moes_paused)
    assert _flash(response)["message"] == "Propiedad no encontrada"
    assert response.headers["location"] == "/visits/select-property"
    assert _visit(ctx) is None


def test_agente_en_dos_empresas_elige_la_empresa_de_la_visita(ctx, monkeypatch):
    import app.web.routes.visits as visits_routes
    monkeypatch.setattr(visits_routes, "notify_visit_created", lambda *a, **k: [])

    response = _new(ctx, ctx.users.vera, ctx.props.moes)
    html = _html(response)
    assert 'name="visit_company_id"' in html
    assert f'<option value="{ctx.moyza.id}" selected>MOYZA</option>' in html   # la principal
    assert 'id="crossCompanyNotice"' in html

    _create(ctx, ctx.users.vera, ctx.props.moes, visit_company_id=str(ctx.moes.id), name="PYTEST-CRUZ EN MOES")
    assert _visit(ctx, "PYTEST-CRUZ EN MOES").company_id == ctx.moes.id
    _create(ctx, ctx.users.vera, ctx.props.moes, name="PYTEST-CRUZ EN MOYZA")
    assert _visit(ctx, "PYTEST-CRUZ EN MOYZA").company_id == ctx.moyza.id


def test_admin_con_selector_registra_en_la_activa(ctx, monkeypatch):
    import app.web.routes.visits as visits_routes
    monkeypatch.setattr(visits_routes, "notify_visit_created", lambda *a, **k: [])

    # El principal tiene que ser de la empresa de la visita (MOYZA), no de la propiedad
    response = _create(ctx, ctx.admin, ctx.props.moes, cookie_company="MOYZA", agent_id=str(ctx.teo.id))
    assert _flash(response)["message"] == "El agente de la visita no pertenece a MOYZA"
    assert _visit(ctx) is None

    response = _create(ctx, ctx.admin, ctx.props.moes, cookie_company="MOYZA", agent_id=str(ctx.mia.id))
    assert response.status_code == 302
    assert _visit(ctx).company_id == ctx.moyza.id

    # Con su propia empresa activa, como siempre
    _create(ctx, ctx.admin, ctx.props.moyza, cookie_company="MOYZA", agent_id=str(ctx.mia.id),
            name="PYTEST-CRUZ PROPIA")
    visit = _visit(ctx, "PYTEST-CRUZ PROPIA")
    assert visit.company_id == ctx.moyza.id and not visit.is_cross_company


def test_pestana_de_otra_empresa_con_registrar_visita(ctx):
    """La tabla de solo lectura "Propiedades de {otra empresa}" lleva el
    botón "Registrar visita" junto al título (sin columna nueva)."""
    from tests.test_unified_view_properties import _properties

    response, html = _properties(ctx, ctx.users.mia, tab="other_company", company_id=ctx.moes.id)
    assert any(r["id"] == ctx.props.moes.id for r in response.context["other_properties"])
    assert f'href="/visits/new/{ctx.props.moes.id}"' in html
    assert f'aria-label="Registrar visita en {ctx.props.moes.title}"' in html
