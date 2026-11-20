"""
Visitas a propiedades externas (inmuebles que no están en el inventario).

- Entrada desde el selector de propiedad y formulario /visits/new-external
  con el bloque "Propiedad externa".
- Alta en /visits/create-external: mismo flujo que una visita normal
  (borrador → vista previa), sin propiedad (`property_id` NULL), empresa de
  la visita con la regla del alta y agentes con la de parse_visit_agents.
- Validaciones con lo escrito conservado (dirección, población, enlace,
  teléfono del contacto).
- Listado con el distintivo "Externa" y el filtro `?filtro=externas`.
- Edición de los datos externos, vista previa, ficha PDF, página final y
  borrado; una empresa ajena no la gestiona y un agente que no participó no
  la ve en su listado.

Contra la base de datos real en una transacción que se deshace al terminar
(como tests/test_visits_cross_company.py; se omiten sin conexión).

    docker exec moyza_backend python -m pytest tests/test_visit_external.py -q
"""
import asyncio
import re
from decimal import Decimal
from types import SimpleNamespace

import pytest

from tests.test_alert_search import _flash
from tests.test_unified_view_properties import _request

MIA_EMAIL = "pytest.externa.mia@example.com"    # MOYZA, registra la visita
ANA_EMAIL = "pytest.externa.ana@example.com"    # MOYZA, no participa
TEO_EMAIL = "pytest.externa.teo@example.com"    # solo MOES

VISITOR = "PYTEST-EXT VISITANTE"


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
    from app.models.property_visit import PropertyVisit
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

    def agent(name, email, company):
        item = Agent(name=name, email=email)
        item.companies.append(company)
        return item

    def user(email, company):
        item = User(email=email, full_name=email.split("@")[0], hashed_password="x", role_id=agent_role.id,
                    is_active=True, company_switch_enabled=False, primary_company_id=company.id)
        item.companies.append(company)
        return item

    mia = agent("PYTEST-EXT MIA", MIA_EMAIL, moyza)
    ana = agent("PYTEST-EXT ANA", ANA_EMAIL, moyza)
    teo = agent("PYTEST-EXT TEO", TEO_EMAIL, moes)
    users = SimpleNamespace(mia=user(MIA_EMAIL, moyza), ana=user(ANA_EMAIL, moyza), teo=user(TEO_EMAIL, moes))
    db.add_all([mia, ana, teo, users.mia, users.ana, users.teo])
    db.flush()

    # Una visita del inventario, para comprobar el filtro del listado
    prop = Property(title="PYTEST-EXT PISO INVENTARIO", company_id=moyza.id, agent_id=mia.id,
                    business_type="Venta", status="Activa", city="Jaén", address="Calle Inventario 1")
    db.add(prop)
    db.flush()
    inventory_visit = PropertyVisit(property_id=prop.id, company_id=moyza.id, visitor_name="PYTEST-EXT INVENTARIO",
                                    phone="34600000009", purchase_fees="2500", notes="n", agent_id=mia.id,
                                    visit_status="draft")
    db.add(inventory_visit)
    db.flush()
    for item in (users.mia, users.ana, users.teo):
        db.refresh(item)
    return SimpleNamespace(db=db, moyza=moyza, moes=moes, admin=admin, mia=mia, ana=ana, teo=teo,
                           users=users, prop=prop, inventory_visit=inventory_visit)


@pytest.fixture(autouse=True)
def no_side_effects(monkeypatch):
    """Sin auditoría ni avisos (no son el objeto de estos tests)."""
    import app.services.visit_audit_service as audit
    import app.web.routes.visits as visits_routes
    monkeypatch.setattr(audit, "log_visit_event", lambda **k: None)
    monkeypatch.setattr(visits_routes, "notify_visit_created", lambda *a, **k: [])


def _html(response):
    return response.body.decode("utf-8")


VALID_FORM = {
    "external_address": "Calle Mayor 3, 2ºB",
    "external_city": "Jaén",
    "external_zone": "Centro",
    "external_property_type": "Piso",
    "external_business_type": "Venta",
    "external_price": "185.000",
    "external_bedrooms": "3",
    "external_bathrooms": "2",
    "external_m2": "90,5",
    "external_contact_name": "Pedro Dueño",
    "external_contact_phone_country_code": "34",
    "external_contact_phone_number": "600 111 222",
    "external_source": "Particular",
    "external_url": "https://www.idealista.com/inmueble/123/",
    "visitor_name": VISITOR,
    "phone_country_code": "34",
    "phone_number": "600000001",
    "purchase_fees": "2500",
    "notes": "nota interna",
    "generate_sheet": "true",
    "visit_mode": "solo",
}


def _create(ctx, user, cookie_company=None, **changes):
    from app.web.routes.visits import create_external_visit
    form = {**VALID_FORM, **changes}
    form = {k: v for k, v in form.items() if v is not None}
    request = _request(ctx, user, "/visits/create-external", "POST", form=form, cookie_company=cookie_company)
    return asyncio.run(create_external_visit(request, db=ctx.db))


def _visit(ctx, name=VISITOR):
    from app.models.property_visit import PropertyVisit
    return ctx.db.query(PropertyVisit).filter_by(visitor_name=name).one_or_none()


def _created(ctx):
    response = _create(ctx, ctx.users.mia)
    assert response.status_code == 302, _html(response)
    return _visit(ctx)


def _list(ctx, user, filtro="", cookie_company=None):
    from app.web.routes.visits import visits_page
    request = _request(ctx, user, "/visits", cookie_company=cookie_company,
                       query=f"filtro={filtro}" if filtro else "")
    return asyncio.run(visits_page(request, filtro=filtro, db=ctx.db))


# ---------------------------------------------------------------------------
# Entrada y formulario
# ---------------------------------------------------------------------------

def test_selector_ofrece_la_visita_externa(ctx):
    from app.web.routes.visits import select_property
    request = _request(ctx, ctx.users.mia, "/visits/select-property")
    html = _html(asyncio.run(select_property(request, db=ctx.db)))
    assert "Visita a una propiedad externa" in html
    assert 'href="/visits/new-external"' in html


def test_formulario_con_el_bloque_de_propiedad_externa(ctx):
    from app.web.routes.visits import new_external_visit
    request = _request(ctx, ctx.users.mia, "/visits/new-external")
    response = asyncio.run(new_external_visit(request, db=ctx.db))
    assert response.status_code == 200
    html = _html(response)
    assert 'action="/visits/create-external"' in html
    for name in ("external_address", "external_city", "external_url", "external_source",
                 "external_contact_phone_number", "visitor_name"):
        assert f'name="{name}"' in html
    # Sin propiedad: ni aviso de otra empresa ni de captador, y "Volver" al selector
    assert "crossCompanyNotice" not in html
    assert "Propiedad captada por" not in html
    assert "Volver a seleccionar propiedad" in html


# ---------------------------------------------------------------------------
# Alta
# ---------------------------------------------------------------------------

def test_alta_correcta_va_a_la_vista_previa(ctx):
    response = _create(ctx, ctx.users.mia)
    visit = _visit(ctx)
    assert response.status_code == 302
    assert response.headers["location"] == f"/visits/preview/{visit.id}"
    assert visit.property_id is None and visit.is_external
    assert visit.company_id == ctx.moyza.id
    assert visit.agent_id == ctx.mia.id and visit.companion_agent_id is None
    assert visit.visit_status == "draft"
    assert visit.external_address == "Calle Mayor 3, 2ºB" and visit.external_city == "Jaén"
    assert visit.external_price == Decimal("185000") and visit.external_m2 == Decimal("90.5")
    assert (visit.external_bedrooms, visit.external_bathrooms) == (3, 2)
    assert visit.external_contact_phone == "34600111222"
    assert visit.external_source == "Particular" and visit.external_business_type == "Venta"
    assert visit.subject.title == "Piso en Calle Mayor 3, 2ºB, Jaén"


def test_alta_solo_con_lo_obligatorio(ctx):
    optional = {name: None for name in VALID_FORM if name.startswith("external_")
                and name not in ("external_address", "external_city")}
    response = _create(ctx, ctx.users.mia, **optional)
    assert response.status_code == 302
    visit = _visit(ctx)
    assert visit.external_price is None and visit.external_contact_phone is None
    assert visit.external_url is None and visit.external_source is None


def test_admin_elige_el_agente_de_la_empresa_activa(ctx):
    response = _create(ctx, ctx.admin, cookie_company="MOYZA", agent_id=str(ctx.teo.id))
    assert response.status_code == 400
    assert "El agente de la visita no pertenece a MOYZA" in _html(response)
    assert _visit(ctx) is None

    response = _create(ctx, ctx.admin, cookie_company="MOYZA", agent_id=str(ctx.ana.id))
    assert response.status_code == 302
    visit = _visit(ctx)
    assert visit.agent_id == ctx.ana.id and visit.company_id == ctx.moyza.id


@pytest.mark.parametrize("changes, field, message", [
    ({"external_address": "  "}, "external_address", "Escribe la dirección de la propiedad"),
    ({"external_city": ""}, "external_city", "Escribe la población"),
    ({"external_url": "www.idealista.com/123"}, "external_url", "http:// o https://"),
    ({"external_url": "ftp://example.com"}, "external_url", "http:// o https://"),
    ({"external_contact_phone_number": "123"}, "external_contact_phone_number", "Teléfono del contacto"),
    ({"external_price": "1.2"}, "external_price", "Revisa el precio"),
    ({"external_bedrooms": "tres"}, "external_bedrooms", "Los dormitorios"),
    ({"external_source": "Inventado"}, "external_source", "Elige un origen"),
])
def test_validaciones_conservan_lo_escrito(ctx, changes, field, message):
    response = _create(ctx, ctx.users.mia, **changes)
    assert response.status_code == 400
    assert _visit(ctx) is None
    errors = response.context["ext_errors"]
    assert set(errors) == {field} and message in errors[field]
    html = _html(response)
    assert "No se ha guardado la visita" in html
    assert message.split(":")[0] in html
    # Lo escrito sigue en el formulario
    assert f'value="{VISITOR}"' in html
    assert 'value="Pedro Dueño"' in html
    assert 'value="nota interna"' not in html and ">nota interna</textarea>" in html


def test_error_del_visitante_conserva_la_propiedad_externa(ctx):
    response = _create(ctx, ctx.users.mia, visitor_name="")
    assert response.status_code == 400
    assert _visit(ctx, "") is None
    html = _html(response)
    assert "Nombre, teléfono, honorarios y observaciones son obligatorios" in html
    assert 'value="Calle Mayor 3, 2ºB"' in html and 'value="185.000"' in html


# ---------------------------------------------------------------------------
# Listado
# ---------------------------------------------------------------------------

def test_listado_con_distintivo_y_filtro(ctx):
    visit = _created(ctx)

    response = _list(ctx, ctx.users.mia)
    visits = response.context["visits"]
    assert visit in visits and ctx.inventory_visit in visits
    html = _html(response)
    assert "Piso en Calle Mayor 3, 2ºB, Jaén" in html
    assert re.search(r">\s*Externa\s*</span>", html)
    assert 'href="/visits?filtro=externas"' in html

    response = _list(ctx, ctx.users.mia, filtro="externas")
    assert response.context["visit_filter"] == "externas"
    assert response.context["visits"] == [visit]

    # El admin de la empresa de la visita también la ve (alcance por company_id)
    response = _list(ctx, ctx.admin, filtro="externas", cookie_company="MOYZA")
    assert visit in response.context["visits"]
    response = _list(ctx, ctx.admin, filtro="externas", cookie_company="MOES")
    assert visit not in response.context["visits"]


# ---------------------------------------------------------------------------
# Resto del flujo
# ---------------------------------------------------------------------------

def test_vista_previa_igual_que_la_ficha(ctx):
    from app.web.routes.visits import preview_visit
    visit = _created(ctx)
    request = _request(ctx, ctx.users.mia, f"/visits/preview/{visit.id}")
    response = asyncio.run(preview_visit(visit.id, request, db=ctx.db))
    assert response.status_code == 200
    html = _html(response)
    assert "Calle Mayor 3, 2ºB, Jaén" in html
    assert "PROPIEDAD EXTERNA:" in html
    assert "DATOS DEL INMUEBLE VISITADO (PROPIEDAD EXTERNA)" in html
    assert "Particular" in html and "Pedro Dueño" in html
    assert "2.500 € + IVA" in html
    assert visit.visit_status == "preview"


def test_edicion_corrige_los_datos_externos(ctx):
    from app.web.routes.visits import edit_visit
    from app.web.routes.visits import update_visit
    visit = _created(ctx)

    request = _request(ctx, ctx.users.mia, f"/visits/edit/{visit.id}")
    html = _html(asyncio.run(edit_visit(visit.id, request, db=ctx.db)))
    assert 'name="external_address"' in html and 'value="Calle Mayor 3, 2ºB"' in html
    assert 'value="185.000"' in html and 'value="90,5"' in html
    assert 'value="600111222"' in html   # teléfono del contacto, sin el indicativo

    form = {**VALID_FORM, "external_city": "Úbeda", "external_price": "190.000", "agent_id": str(ctx.mia.id)}
    request = _request(ctx, ctx.users.mia, f"/visits/update/{visit.id}", "POST", form=form)
    response = asyncio.run(update_visit(visit.id, request, db=ctx.db))
    assert response.status_code == 302
    assert response.headers["location"] == f"/visits/preview/{visit.id}"
    ctx.db.refresh(visit)
    assert visit.external_city == "Úbeda" and visit.external_price == Decimal("190000")

    # Un dato no válido no se guarda
    form = {**form, "external_url": "idealista", "external_city": "Linares"}
    request = _request(ctx, ctx.users.mia, f"/visits/update/{visit.id}", "POST", form=form)
    response = asyncio.run(update_visit(visit.id, request, db=ctx.db))
    assert response.headers["location"] == f"/visits/edit/{visit.id}"
    assert "http:// o https://" in _flash(response)["message"]
    ctx.db.refresh(visit)
    assert visit.external_city == "Úbeda"


def test_ficha_pdf_y_pagina_final(ctx, monkeypatch):
    import app.web.routes.visits as visits_routes
    from app.web.routes.visits import complete_visit_page
    from app.web.routes.visits import generate_visit_pdf
    visit = _created(ctx)

    calls = []
    monkeypatch.setattr(visits_routes, "generate_visit_sheet", lambda **kwargs: calls.append(kwargs))
    request = _request(ctx, ctx.users.mia, f"/visits/{visit.id}/generate-pdf", "POST", form={})
    response = asyncio.run(generate_visit_pdf(visit.id, request, db=ctx.db))
    assert _flash(response)["message"] == "Ficha de visita generada correctamente"
    assert calls and calls[0]["property_item"].is_external
    assert visit.visit_sheet_filename.startswith(f"ficha_visita_externa_{visit.id}_")

    visit.signature_filepath = "storage/signatures/pytest.png"
    visit.visit_status = "signed"
    ctx.db.flush()
    request = _request(ctx, ctx.users.mia, f"/visits/complete/{visit.id}")
    response = asyncio.run(complete_visit_page(visit.id, request, db=ctx.db))
    assert response.status_code == 200
    assert response.context["property_url"] == "/visits"
    assert "Calle Mayor 3, 2ºB · Jaén" in _html(response)


def test_borrado(ctx):
    from app.web.routes.visits import delete_visit
    visit = _created(ctx)
    visit_id = visit.id
    request = _request(ctx, ctx.users.mia, "/visits/delete", "POST", form={"visit_id": visit_id})
    response = asyncio.run(delete_visit(request, visit_id=visit_id, db=ctx.db))
    assert _flash(response)["message"] == "Visita eliminada correctamente"
    assert _visit(ctx) is None


def test_un_agente_ajeno_no_la_gestiona(ctx):
    from app.web.routes.visits import delete_visit
    from app.web.routes.visits import edit_visit
    from app.web.routes.visits import preview_visit
    visit = _created(ctx)

    # Otra empresa: ni editar, ni vista previa, ni borrar
    request = _request(ctx, ctx.users.teo, f"/visits/edit/{visit.id}")
    response = asyncio.run(edit_visit(visit.id, request, db=ctx.db))
    assert _flash(response)["message"] == "Visita no encontrada"
    request = _request(ctx, ctx.users.teo, f"/visits/preview/{visit.id}")
    response = asyncio.run(preview_visit(visit.id, request, db=ctx.db))
    assert _flash(response)["message"] == "Visita no encontrada"
    request = _request(ctx, ctx.users.teo, "/visits/delete", "POST", form={"visit_id": visit.id})
    response = asyncio.run(delete_visit(request, visit_id=visit.id, db=ctx.db))
    assert _flash(response)["message"] == "Visita no encontrada"
    assert _visit(ctx) is not None

    # Ni la ve en su listado; tampoco un agente de la misma empresa que no participó
    assert visit not in _list(ctx, ctx.users.teo).context["visits"]
    assert visit not in _list(ctx, ctx.users.ana).context["visits"]
