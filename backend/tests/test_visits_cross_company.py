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


# ---------------------------------------------------------------------------
# Ficha y vista previa (fase C)
# ---------------------------------------------------------------------------

@pytest.fixture
def cross_visit(ctx):
    """Visita de Mia (MOYZA) a la propiedad de Teo (MOES), sin firmar."""
    from app.models.property_visit import PropertyVisit
    visit = PropertyVisit(property_id=ctx.props.moes.id, company_id=ctx.moyza.id, visitor_name="PYTEST-CRUZ CLIENTE",
                          phone="34600000002", purchase_fees="2500", notes="nota", agent_id=ctx.mia.id,
                          visit_status="draft")
    ctx.db.add(visit)
    ctx.db.flush()
    ctx.db.refresh(visit)
    return visit


def test_preview_con_marca_de_la_visita_y_comercializado_por(ctx, cross_visit):
    from app.web.routes.visits import preview_visit
    response = asyncio.run(preview_visit(cross_visit.id, _request(ctx, ctx.users.mia, "/visits/preview"), db=ctx.db))
    assert response.status_code == 200
    html = _html(response)
    assert "FICHA DE VISITA INMOBILIARIA MOYZA" in html
    assert "en calidad de representante de la agencia inmobiliaria MOYZA" in html
    assert "Inmueble comercializado por MOES PREMIUM" in html
    # El documento lleva la dirección completa aunque Mia no vea la calle en la app
    assert "Calle Secreta Moes 7" in html


def test_pdf_con_marca_de_la_visita_y_comercializado_por(ctx, cross_visit, tmp_path):
    pypdf = pytest.importorskip("pypdf")
    from app.services.visit_sheet_generator import generate_visit_sheet

    output = tmp_path / "ficha.pdf"
    generate_visit_sheet(property_item=cross_visit.property, visit=cross_visit, agent=cross_visit.signing_agent,
                         output_path=str(output))
    text = " ".join(page.extract_text() for page in pypdf.PdfReader(str(output)).pages)
    text = " ".join(text.split())
    assert "FICHA DE VISITA INMOBILIARIA MOYZA" in text
    assert "agencia inmobiliaria MOYZA" in text
    assert "Inmueble comercializado por MOES PREMIUM" in text
    assert "Calle Secreta Moes 7" in text


def test_ficha_de_visita_propia_sin_linea_de_comercializacion(ctx):
    from app.models.property_visit import PropertyVisit
    from app.web.routes.visits import preview_visit
    visit = PropertyVisit(property_id=ctx.props.moes.id, company_id=ctx.moes.id, visitor_name="PYTEST-CRUZ PROPIA",
                          phone="34600000003", purchase_fees="2500", notes="n", agent_id=ctx.teo.id,
                          visit_status="draft")
    ctx.db.add(visit)
    ctx.db.flush()
    response = asyncio.run(preview_visit(visit.id, _request(ctx, ctx.users.teo, "/visits/preview"), db=ctx.db))
    html = _html(response)
    assert "FICHA DE VISITA INMOBILIARIA MOES PREMIUM" in html
    assert "comercializado por" not in html


# ---------------------------------------------------------------------------
# Visibilidad para la empresa de la propiedad (fase C)
# ---------------------------------------------------------------------------

def test_admin_de_moes_ve_la_visita_en_la_ficha_de_la_propiedad(ctx, cross_visit):
    from app.web.routes.properties import property_detail
    request = _request(ctx, ctx.admin, f"/properties/{ctx.props.moes.id}", cookie_company="MOES")
    response = asyncio.run(property_detail(ctx.props.moes.id, request, db=ctx.db))
    html = _html(response)
    assert cross_visit in response.context["visits_registered"]
    assert "PYTEST-CRUZ CLIENTE" in html
    assert 'title="Visita registrada en MOYZA (solo lectura)"' in html
    # Sin generar ni enviar la ficha de una visita ajena
    assert f"/visits/{cross_visit.id}/generate-pdf" not in html


def test_admin_de_moes_la_ve_en_visitas_en_solo_lectura(ctx, cross_visit):
    from app.web.routes.visits import edit_visit
    from app.web.routes.visits import visits_page
    request = _request(ctx, ctx.admin, "/visits", cookie_company="MOES")
    response = asyncio.run(visits_page(request, db=ctx.db))
    html = _html(response)
    assert cross_visit in response.context["visits"]
    assert 'title="Visita registrada en MOYZA (solo lectura)"' in html
    assert f'href="/visits/edit/{cross_visit.id}"' not in html
    assert f'value="{cross_visit.id}"' not in html                        # sin borrar
    assert f"/visits/{cross_visit.id}/generate-pdf" not in html
    # Editar por URL tampoco
    response = asyncio.run(edit_visit(cross_visit.id, _request(ctx, ctx.admin, "/visits/edit", cookie_company="MOES"),
                                      db=ctx.db))
    assert _flash(response)["message"] == "Visita no encontrada"


def test_descarga_de_la_ficha_para_la_empresa_de_la_propiedad(ctx, cross_visit):
    from app.web.routes.visits import download_visit_sheet
    cross_visit.visit_sheet_filepath = "/no/existe/ficha.pdf"
    ctx.db.flush()

    def download(user, cookie_company=None):
        request = _request(ctx, user, "/visits/download", cookie_company=cookie_company)
        return _flash(asyncio.run(download_visit_sheet(cross_visit.id, request, db=ctx.db)))["message"]

    # La visita existe para las dos empresas (falta el archivo, no la visita)
    assert download(ctx.admin, "MOES") == "Archivo de ficha de visita no existe"
    assert download(ctx.users.mia) == "Archivo de ficha de visita no existe"


def test_agente_de_moyza_ve_su_visita_con_el_distintivo_de_la_propiedad(ctx, cross_visit):
    from app.web.routes.visits import visits_page
    response = asyncio.run(visits_page(_request(ctx, ctx.users.mia, "/visits"), db=ctx.db))
    html = _html(response)
    assert cross_visit in response.context["visits"]
    assert 'title="Propiedad de MOES PREMIUM"' in html
    assert f'href="/visits/edit/{cross_visit.id}"' in html        # es suya: la gestiona
    assert f'href="/properties/{ctx.props.moes.id}"' not in html  # la ficha de MOES no se abre
    assert "(solo lectura)" not in html


def test_feed_del_inicio_con_distintivo(ctx, cross_visit):
    from app.services.dashboard_service import DashboardService

    def event(company):
        feed = DashboardService(ctx.db, company.id).activity_feed()
        return next(e for e in feed if e["kind"] == "visit" and "PYTEST-CRUZ CLIENTE" in e["text"])

    moyza_event = event(ctx.moyza)
    assert moyza_event["company"].id == ctx.moes.id and moyza_event["href"] == "/visits"
    assert moyza_event["company_title"] == "Propiedad de MOES PREMIUM"
    moes_event = event(ctx.moes)
    assert moes_event["company"].id == ctx.moyza.id and moes_event["cross"] is True
    assert moes_event["href"] == f"/properties/{ctx.props.moes.id}"


def test_aviso_de_ficha_firmada_en_la_empresa_de_la_visita(ctx, cross_visit):
    from app.models.notification import Notification
    from app.services.notification_service import notify_visit_completed

    created = notify_visit_completed(ctx.db, cross_visit, sent=False)
    assert created and all(n.company_id == ctx.moyza.id and n.url == "/visits" for n in created)
    ctx.db.query(Notification).filter(Notification.id.in_([n.id for n in created])).delete(synchronize_session=False)


# ---------------------------------------------------------------------------
# Métrica "Hojas de visita" (fase D)
# ---------------------------------------------------------------------------

def test_cuenta_en_hojas_de_visita_de_la_empresa_de_la_visita(ctx, cross_visit):
    from datetime import datetime, timedelta
    from app.services.dashboard_service import DashboardService
    from app.services.performance_report_service import PerformanceReportService

    start, end = datetime.utcnow() - timedelta(days=1), datetime.utcnow() + timedelta(days=1)

    def hojas(company):
        return PerformanceReportService(ctx.db, company.id).calculate_metrics(ctx.mia.id, start, end)["hojas_visita"]

    assert hojas(ctx.moyza) == 1 and hojas(ctx.moes) == 0
    # El Inicio y el equipo, con el mismo criterio
    assert DashboardService(ctx.db, ctx.moyza.id)._visit_counts([ctx.mia.id], start, end) == {ctx.mia.id: 1}
    assert DashboardService(ctx.db, ctx.moes.id)._visit_counts([ctx.mia.id], start, end) == {}
    assert DashboardService(ctx.db, ctx.moyza.id)._company_visit_count(start, end) >= 1
    weekly = DashboardService(ctx.db, ctx.moyza.id)._weekly_visits([ctx.mia.id], start, end)
    assert sum(weekly.values()) == 1


def test_lupa_con_la_regla_y_el_distintivo(ctx, cross_visit):
    from datetime import datetime, timedelta
    from app.services.performance_report_service import PerformanceReportService

    start, end = datetime.utcnow() - timedelta(days=1), datetime.utcnow() + timedelta(days=1)
    svc = PerformanceReportService(ctx.db, ctx.moyza.id)
    rows = svc.indicator_rows("hojas_visita", ctx.mia.id, start, end)
    assert [r["visit_id"] for r in rows] == [cross_visit.id]
    assert rows[0]["property_company"].id == ctx.moes.id
    text = svc.indicator_rule_text("hojas_visita", ctx.mia, start, end, ctx.moyza)
    assert "visitas realizadas por PYTEST-CRUZ MIA como principal o acompañante, registradas en MOYZA, " \
           "a propiedades de cualquier empresa" in text


def test_lupa_pinta_el_distintivo_sin_enlace_a_la_ficha(ctx, cross_visit):
    from app.web.routes.commercial_results import metric_detail
    request = _request(ctx, ctx.admin, f"/commercial-results/{ctx.mia.id}/metric/hojas_visita", cookie_company="MOYZA")
    response = asyncio.run(metric_detail(ctx.mia.id, "hojas_visita", request, period_type="MONTHLY",
                                         period_start="", offset=0, output="", db=ctx.db))
    html = _html(response)
    assert "PYTEST-CRUZ CLIENTE" in html
    assert 'title="Propiedad de MOES PREMIUM"' in html
    assert f'href="/properties/{ctx.props.moes.id}"' not in html
    assert "a propiedades de cualquier empresa" in html


def test_tras_la_firma_vuelve_a_visitas_si_la_ficha_no_se_abre(ctx, cross_visit):
    from app.web.routes.visits import complete_visit_page
    from app.web.routes.visits import preview_visit
    cross_visit.signature_filepath = "/no/existe/firma.png"
    cross_visit.visit_status = "signed"
    ctx.db.flush()

    response = asyncio.run(complete_visit_page(cross_visit.id, _request(ctx, ctx.users.mia, "/visits/complete"),
                                               db=ctx.db))
    assert response.context["property_url"] == "/visits"
    assert "← Volver a Visitas" in _html(response)
    # Visita ya procesada: de la vista previa, a Visitas (no a una ficha que no se abre)
    response = asyncio.run(preview_visit(cross_visit.id, _request(ctx, ctx.users.mia, "/visits/preview"), db=ctx.db))
    assert response.headers["location"] == "/visits"
