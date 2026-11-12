"""
Empresa propia de la visita (PLAN_VISITAS_OTRA_EMPRESA.md, fase A).

- `property_visits.company_id` es la empresa desde la que se registra la
  visita, no siempre la de la propiedad; `scope_visits` y
  `get_visit_in_company` filtran por ella (un id o una lista) y
  `scope_visible_visits` añade las registradas por otra empresa a sus
  propiedades.
- Un alta que no fija la empresa toma la de la propiedad (red de seguridad).
- `resolve_visit_company`: admin y vista por empresa, la activa; agente en
  vista unificada con una empresa, esa; con varias, la elegida en el select
  "Empresa" (validada contra sus empresas), la principal si no elige.
- `create_visit` guarda la empresa elegida y valida al principal contra ella.

Contra la base de datos real en una transacción que se deshace al terminar
(como tests/test_unified_view_properties.py; se omiten sin conexión).

    docker exec moyza_backend python -m pytest tests/test_visit_company.py -q
"""
import asyncio
from types import SimpleNamespace

import pytest

from tests.test_alert_search import _flash
from tests.test_unified_view_properties import _request

EMAIL = "pytest.visita.empresa@example.com"
SOLO_EMAIL = "pytest.visita.empresa.solo@example.com"


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
    """Vera (MOYZA y MOES, vista unificada, principal MOYZA), Sami (solo
    MOYZA) y una propiedad por empresa."""
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

    vera = agent("PYTEST-VEMP VERA", EMAIL, moyza, moes)
    sami = agent("PYTEST-VEMP SAMI", SOLO_EMAIL, moyza)
    vera_user, sami_user = user(EMAIL, moyza, moes), user(SOLO_EMAIL, moyza)
    db.add_all([vera, sami, vera_user, sami_user])
    db.flush()

    def prop(title, company, owner):
        item = Property(title=title, company_id=company.id, agent_id=owner.id, business_type="Venta",
                        status="Activa", price=999999999, city="Jaén", address=f"Calle {title} 1")
        db.add(item)
        return item

    props = SimpleNamespace(moyza=prop("PYTEST-VEMP PISO MOYZA", moyza, sami),
                            moes=prop("PYTEST-VEMP ATICO MOES", moes, vera))
    db.flush()
    for item in (vera_user, sami_user):
        db.refresh(item)
    return SimpleNamespace(db=db, moyza=moyza, moes=moes, admin=admin, vera=vera, sami=sami,
                           user=vera_user, solo_user=sami_user, props=props)


def _visit(ctx, prop, company=None, name="PYTEST-VEMP VISITANTE", agent=None):
    from app.models.property_visit import PropertyVisit
    visit = PropertyVisit(property_id=prop.id, visitor_name=name, phone="34600000000",
                          company_id=company.id if company is not None else None,
                          agent_id=(agent or ctx.vera).id, visit_status="completed")
    ctx.db.add(visit)
    ctx.db.flush()
    return visit


# ---------------------------------------------------------------------------
# Modelo y alcance
# ---------------------------------------------------------------------------

def test_sin_empresa_toma_la_de_la_propiedad(ctx):
    visit = _visit(ctx, ctx.props.moes)
    assert visit.company_id == ctx.moes.id
    assert visit.is_cross_company is False


def test_scope_visits_por_la_empresa_de_la_visita(ctx):
    from app.models.property_visit import PropertyVisit
    from app.services.company_scope import get_visible_visit
    from app.services.company_scope import get_visit_in_company
    from app.services.company_scope import scope_visible_visits
    from app.services.company_scope import scope_visits

    # Visita de MOYZA a una propiedad de MOES (cruzada)
    cross = _visit(ctx, ctx.props.moes, company=ctx.moyza)
    ctx.db.refresh(cross)
    assert cross.is_cross_company is True
    assert cross.company.code == "MOYZA"

    def ids(query):
        return {v.id for v in query.filter(PropertyVisit.visitor_name.like("PYTEST-VEMP%")).all()}

    assert ids(scope_visits(ctx.db.query(PropertyVisit), ctx.moyza.id)) == {cross.id}
    assert ids(scope_visits(ctx.db.query(PropertyVisit), ctx.moes.id)) == set()
    assert ids(scope_visits(ctx.db.query(PropertyVisit), [ctx.moyza.id, ctx.moes.id])) == {cross.id}
    # MOES la ve (solo lectura) porque la propiedad es suya
    assert ids(scope_visible_visits(ctx.db.query(PropertyVisit), ctx.moes.id)) == {cross.id}

    assert get_visit_in_company(ctx.db, cross.id, ctx.moyza.id) is not None
    assert get_visit_in_company(ctx.db, cross.id, ctx.moes.id) is None
    assert get_visit_in_company(ctx.db, cross.id, [ctx.moes.id, ctx.moyza.id]) is not None
    assert get_visible_visit(ctx.db, cross.id, ctx.moes.id) is not None


# ---------------------------------------------------------------------------
# Empresa de una visita nueva
# ---------------------------------------------------------------------------

def test_resolve_visit_company(ctx):
    from app.services.visit_agents import VisitAgentsError
    from app.web.routes.visits import resolve_visit_company
    from app.web.routes.visits import visit_company_options

    # Admin con selector: la activa, sin select
    request = _request(ctx, ctx.admin, "/visits/new/1", cookie_company="MOES")
    assert visit_company_options(request) == []
    assert resolve_visit_company(request, {"visit_company_id": str(ctx.moyza.id)}).id == ctx.moes.id

    # Agente de una sola empresa: esa, sin select
    request = _request(ctx, ctx.solo_user, "/visits/new/1")
    assert visit_company_options(request) == []
    assert resolve_visit_company(request).id == ctx.moyza.id

    # Agente en dos: select con las dos; la principal si no elige
    request = _request(ctx, ctx.user, "/visits/new/1")
    assert [c.id for c in visit_company_options(request)] == [ctx.moyza.id, ctx.moes.id]
    assert resolve_visit_company(request).id == ctx.moyza.id
    assert resolve_visit_company(request, {"visit_company_id": str(ctx.moes.id)}).id == ctx.moes.id
    with pytest.raises(VisitAgentsError, match="no es una de tus empresas"):
        resolve_visit_company(request, {"visit_company_id": "999999"})

    # Con "Puede cambiar de empresa": la activa, como el admin
    ctx.user.company_switch_enabled = True
    ctx.db.flush()
    request = _request(ctx, ctx.user, "/visits/new/1", cookie_company="MOES")
    assert visit_company_options(request) == []
    assert resolve_visit_company(request).id == ctx.moes.id


def _create(ctx, user, prop, cookie_company=None, **extra):
    from app.web.routes.visits import create_visit
    form = {"visitor_name": "PYTEST-VEMP ALTA", "phone_country_code": "34", "phone_number": "600000001",
            "purchase_fees": "2500", "notes": "nota", "generate_sheet": "true", **extra}
    request = _request(ctx, user, f"/visits/create/{prop.id}", "POST", form=form, cookie_company=cookie_company)
    return asyncio.run(create_visit(prop.id, request, db=ctx.db))


def _created(ctx):
    from app.models.property_visit import PropertyVisit
    return ctx.db.query(PropertyVisit).filter_by(visitor_name="PYTEST-VEMP ALTA").one_or_none()


@pytest.fixture
def no_side_effects(monkeypatch):
    """Sin avisos ni auditoría (no son el objeto de estos tests)."""
    import app.services.visit_audit_service as audit
    import app.web.routes.visits as visits_routes
    monkeypatch.setattr(visits_routes, "notify_visit_created", lambda *a, **k: [])
    monkeypatch.setattr(audit, "log_visit_event", lambda **k: None)


def test_alta_guarda_la_empresa_elegida(ctx, no_side_effects):
    # Vera (principal MOYZA) registra en MOES una visita
    response = _create(ctx, ctx.user, ctx.props.moyza, visit_company_id=str(ctx.moes.id))
    assert response.status_code == 302 and "/visits/preview/" in response.headers["location"]
    visit = _created(ctx)
    assert visit.company_id == ctx.moes.id and visit.agent_id == ctx.vera.id


def test_alta_sin_elegir_es_la_principal(ctx, no_side_effects):
    _create(ctx, ctx.user, ctx.props.moyza)
    assert _created(ctx).company_id == ctx.moyza.id


def test_alta_con_empresa_ajena_no_crea(ctx, no_side_effects):
    response = _create(ctx, ctx.user, ctx.props.moyza, visit_company_id="999999")
    assert _flash(response)["message"] == "La empresa elegida para la visita no es una de tus empresas"
    assert _created(ctx) is None


def test_admin_valida_el_principal_contra_la_empresa_de_la_visita(ctx, no_side_effects):
    # Admin con MOYZA activa: Sami (solo MOYZA) vale; con MOES activa no
    response = _create(ctx, ctx.admin, ctx.props.moyza, cookie_company="MOYZA", agent_id=str(ctx.sami.id))
    assert response.status_code == 302 and _created(ctx).company_id == ctx.moyza.id
