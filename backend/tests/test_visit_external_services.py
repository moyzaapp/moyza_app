"""
Visitas a propiedades externas (fuera del inventario) en los servicios que
leen la propiedad de una visita: hoja de visita en PDF, indicador «Hojas de
visita» (Resultados Comerciales e Inicio), avisos, alcance por empresa,
WhatsApp y registro de actividad.

Una visita externa tiene `property_id` NULL y los datos escritos a mano en
`external_*`; se pinta con `visit.subject`. Las visitas se crean directamente
con el modelo (no con las rutas de alta).

Con base de datos (se omiten si no hay conexión), dentro de una transacción
externa que se deshace al terminar: los commit de los servicios solo cierran
savepoints y no queda nada creado.

    docker exec moyza_backend python -m pytest tests/test_visit_external_services.py -q
"""
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.models.property_visit import PropertyVisit


NOW = datetime(2026, 10, 8, 10, 30)   # jueves
MARCH = (datetime(2025, 3, 1), datetime(2025, 3, 31, 23, 59, 59))


# ---------------------------------------------------------------------------
# Fixtures
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
    """MOYZA y MOES, dos agentes de MOYZA con su usuario (Laura también en MOES)."""
    from app.models.agent import Agent
    from app.models.company import Company
    from app.models.user import User

    moyza = db.query(Company).filter_by(code="MOYZA").one()
    moes = db.query(Company).filter_by(code="MOES").one()

    laura = Agent(name="PYTEST-EXT LAURA", email="pytest.ext.laura@example.com")
    carlos = Agent(name="PYTEST-EXT CARLOS", email="pytest.ext.carlos@example.com")
    laura.companies.extend([moyza, moes])
    carlos.companies.append(moyza)
    laura_user = User(email="pytest.ext.laura@example.com", full_name="Laura", hashed_password="x", is_active=True)
    carlos_user = User(email="pytest.ext.carlos@example.com", full_name="Carlos", hashed_password="x", is_active=True)
    db.add_all([laura, carlos, laura_user, carlos_user])
    db.flush()
    return SimpleNamespace(db=db, moyza=moyza, moes=moes, laura=laura, carlos=carlos,
                           laura_user=laura_user, carlos_user=carlos_user)


def _external(ctx, company=None, agent=None, companion=None, created_at=None, **fields):
    """Visita a una propiedad externa creada directamente con el modelo."""
    data = dict(
        external_address="Calle Externa 12, 3ºB",
        external_city="Úbeda",
        external_zone="Centro",
        external_property_type="Piso",
        external_business_type="Venta",
        external_price=Decimal("185000"),
        external_bedrooms=3,
        external_bathrooms=2,
        external_m2=Decimal("95.50"),
        external_contact_name="Pepe Particular",
        external_contact_phone="34600111222",
        external_source="Particular",
    )
    data.update(fields)
    visit = PropertyVisit(
        property_id=None,
        company_id=(company or ctx.moyza).id,
        agent_id=(agent or ctx.carlos).id,
        companion_agent_id=companion.id if companion else None,
        visitor_name="PYTEST-EXT VISITANTE",
        created_at=created_at or datetime.utcnow(),
        **data,
    )
    ctx.db.add(visit)
    ctx.db.flush()
    ctx.db.refresh(visit)
    return visit


# ---------------------------------------------------------------------------
# Modelo
# ---------------------------------------------------------------------------

def test_subject_de_una_externa_sin_guardar():
    visit = PropertyVisit(property_id=None, external_address="Calle Sol 1", external_city="Jaén",
                          external_property_type="Casa", visitor_name="X")
    assert visit.is_external
    assert visit.subject.title == "Casa en Calle Sol 1, Jaén"
    assert visit.subject.id is None and visit.subject.agent is None and visit.subject.company is None
    assert visit.signing_agent is None and not visit.is_cross_company


# ---------------------------------------------------------------------------
# Hoja de visita (PDF)
# ---------------------------------------------------------------------------

def _pdf_text(path):
    pypdf = pytest.importorskip("pypdf")
    return " ".join(page.extract_text() for page in pypdf.PdfReader(str(path)).pages)


def test_pdf_de_una_visita_externa(ctx, tmp_path):
    from app.services.company_service import branding_for
    from app.services.visit_sheet_generator import generate_visit_sheet

    visit = _external(ctx)
    output = tmp_path / "ficha_externa.pdf"
    # Sin propiedad: el generador toma `visit.subject`
    generate_visit_sheet(property_item=None, visit=visit, agent=visit.signing_agent, output_path=str(output))
    text = " ".join(_pdf_text(output).split())

    brand = branding_for(ctx.moyza)
    assert f"FICHA DE VISITA INMOBILIARIA {brand.name}" in text
    assert "DIRECCIÓN DEL INMUEBLE VISITADO: Calle Externa 12, 3ºB, Úbeda" in text
    assert "PROPIEDAD EXTERNA: inmueble que no forma parte del inventario de " + brand.name in text
    assert "DATOS DEL INMUEBLE VISITADO (PROPIEDAD EXTERNA)" in text
    assert "Piso en Calle Externa 12, 3ºB, Úbeda" in text
    assert "Centro" in text and "Venta" in text
    assert "185.000 €" in text
    assert "3 dormitorios · 2 baños · 95,5 m²" in text
    assert "Origen: Particular" in text
    assert "Pepe Particular · +34 600 111 222" in text
    assert "PYTEST-EXT CARLOS" in text
    # Sin id de propiedad: "EXT" en el id de documento
    assert f"-{visit.id}-EXT" in text and "None" not in text
    # Una externa no la comercializa otra empresa
    assert "Inmueble comercializado por" not in text


def test_pdf_externa_minima_y_marca_de_la_empresa_de_la_visita(ctx, tmp_path):
    from app.services.company_service import branding_for
    from app.services.visit_sheet_generator import generate_visit_sheet

    # Solo lo obligatorio del alta: dirección y población
    visit = _external(
        ctx, company=ctx.moes, agent=ctx.laura,
        external_zone=None, external_property_type=None, external_business_type=None, external_price=None,
        external_bedrooms=None, external_bathrooms=None, external_m2=None,
        external_contact_name=None, external_contact_phone=None, external_source=None,
    )
    output = tmp_path / "ficha_minima.pdf"
    generate_visit_sheet(property_item=visit.subject, visit=visit, agent=visit.signing_agent, output_path=str(output))
    text = " ".join(_pdf_text(output).split())

    assert f"FICHA DE VISITA INMOBILIARIA {branding_for(ctx.moes).name}" in text
    assert "Propiedad en Calle Externa 12, 3ºB, Úbeda" in text
    assert "Precio: No especificado" in text
    assert "Origen" not in text and "Contacto del inmueble" not in text and "Características" not in text


def test_filas_de_la_propiedad_externa_por_operacion():
    from app.services.visit_sheet_generator import external_property_rows

    def rows(**fields):
        visit = PropertyVisit(property_id=None, external_address="C/ Uno 1", external_city="Jaén",
                              visitor_name="X", **fields)
        return dict(external_property_rows(visit.subject))

    assert rows(external_business_type="Alquiler", external_price=Decimal("750"))["Precio de alquiler:"] == "750 €"
    assert rows(external_business_type="Venta", external_price=Decimal("1500000.5"))["Precio de venta:"] == "1.500.000,5 €"
    assert rows()["Precio:"] == "No especificado"
    assert rows(external_contact_phone="34600111222")["Contacto del inmueble:"] == "+34 600 111 222"


# ---------------------------------------------------------------------------
# Indicador «Hojas de visita»
# ---------------------------------------------------------------------------

def test_hojas_de_visita_cuentan_la_externa(ctx):
    from app.services.performance_report_service import PerformanceReportService

    _external(ctx, agent=ctx.carlos, companion=ctx.laura, created_at=datetime(2025, 3, 10, 9))
    _external(ctx, company=ctx.moes, agent=ctx.laura, created_at=datetime(2025, 3, 11, 9))

    moyza = PerformanceReportService(ctx.db, ctx.moyza.id)
    assert moyza.calculate_metrics(ctx.carlos.id, *MARCH)["hojas_visita"] == 1
    # Acompañante: también cuenta, como en las del inventario
    assert moyza.calculate_metrics(ctx.laura.id, *MARCH)["hojas_visita"] == 1
    moes = PerformanceReportService(ctx.db, ctx.moes.id)
    assert moes.calculate_metrics(ctx.laura.id, *MARCH)["hojas_visita"] == 1
    assert moes.calculate_metrics(ctx.carlos.id, *MARCH)["hojas_visita"] == 0

    # Hojas de visita no tiene desglose por operación (tampoco con externas)
    live = moyza.indicator_live_counts("hojas_visita", ctx.carlos.id, *MARCH)
    assert live == {"total": 1, "detail": None}


def test_detalle_y_csv_del_indicador_con_una_externa(ctx):
    from app.services.performance_report_service import PerformanceReportService
    from app.web.routes.commercial_results import METRIC_CSV_COLUMNS

    visit = _external(ctx, agent=ctx.carlos, created_at=datetime(2025, 3, 10, 9))
    svc = PerformanceReportService(ctx.db, ctx.moyza.id)
    [row] = svc.indicator_rows("hojas_visita", ctx.carlos.id, *MARCH, limit=None)

    assert row["visit_id"] == visit.id
    assert row["property_external"] is True
    assert row["property_id"] is None and row["property_company"] is None
    assert row["property_title"] == "Piso en Calle Externa 12, 3ºB, Úbeda"
    assert row["property_city"] == "Úbeda"

    csv = {header: value(row) for header, value in METRIC_CSV_COLUMNS["hojas_visita"]}
    assert csv["Propiedad"] == "Piso en Calle Externa 12, 3ºB, Úbeda (propiedad externa)"
    assert csv["Ciudad"] == "Úbeda"


def test_inicio_cuenta_y_pinta_la_externa(ctx):
    from app.services.dashboard_service import DashboardService

    svc = DashboardService(ctx.db, ctx.moyza.id)
    week = svc.period("WEEKLY", "", now=NOW)
    when = week.start + timedelta(hours=10)
    _external(ctx, agent=ctx.carlos, companion=ctx.laura, created_at=when)

    metrics = svc.team_metrics([ctx.carlos.id, ctx.laura.id], week)
    assert metrics[ctx.carlos.id]["hojas_visita"] == 1
    assert metrics[ctx.laura.id]["hojas_visita"] == 1
    assert svc._company_visit_count(week.start, week.end) >= 1
    assert svc.agent_trend(ctx.carlos, week, now=NOW).series[0].data[-1] == 1
    # En MOES no cuenta
    moes = DashboardService(ctx.db, ctx.moes.id)
    assert moes.team_metrics([ctx.laura.id], week)[ctx.laura.id]["hojas_visita"] == 0


def test_feed_del_inicio_con_una_externa(ctx):
    from app.services.dashboard_service import DashboardService

    now = datetime.utcnow()
    visit = _external(ctx, agent=ctx.carlos, created_at=now - timedelta(minutes=2))
    visit.visit_status = "completed"
    visit.signature_captured_at = now - timedelta(minutes=1)
    ctx.db.flush()

    feed = [e for e in DashboardService(ctx.db, ctx.moyza.id).activity_feed(now=now)
            if "Calle Externa 12" in (e.get("text") or "")]
    by_kind = {e["kind"]: e for e in feed}
    assert set(by_kind) == {"visit", "signed"}
    for event in feed:
        assert event["external"] is True
        assert event["href"] == "/visits"
        assert event["text"].startswith("Piso en Calle Externa 12, 3ºB, Úbeda")
        assert "company" not in event
    assert by_kind["visit"]["title"] == "PYTEST-EXT CARLOS registró una visita"
    assert by_kind["visit"]["cross"] is False
    # La otra empresa no la ve
    moes_feed = DashboardService(ctx.db, ctx.moes.id).activity_feed(now=now)
    assert not [e for e in moes_feed if "Calle Externa 12" in (e.get("text") or "")]


def test_feed_item_pinta_el_distintivo_de_externa():
    from app.web.template_env import templates

    module = templates.env.get_template("dashboard/components/feed_item.html").module
    event = {"icon": "calendar", "tone": "blue", "title": "Visita", "text": "Piso en X", "when": NOW,
             "href": "/visits", "cross": False, "external": True}
    html = str(module.feed_item(event))
    assert "Propiedad externa" in html


# ---------------------------------------------------------------------------
# Alcance por empresa
# ---------------------------------------------------------------------------

def test_alcance_por_empresa_de_una_externa(ctx):
    from app.services.company_scope import get_visible_visit
    from app.services.company_scope import get_visit_in_company
    from app.services.company_scope import scope_visible_visits

    visit = _external(ctx)
    db = ctx.db

    assert get_visit_in_company(db, visit.id, ctx.moyza.id) is visit
    assert get_visible_visit(db, visit.id, ctx.moyza.id) is visit
    # Lista de empresas (vista unificada)
    assert get_visible_visit(db, visit.id, [ctx.moyza.id, ctx.moes.id]) is visit
    # La otra empresa no la ve: el EXISTS de la propiedad es falso con property_id NULL
    assert get_visit_in_company(db, visit.id, ctx.moes.id) is None
    assert get_visible_visit(db, visit.id, ctx.moes.id) is None
    visible_moes = scope_visible_visits(db.query(PropertyVisit), ctx.moes.id).filter(PropertyVisit.id == visit.id)
    assert visible_moes.count() == 0


# ---------------------------------------------------------------------------
# Avisos
# ---------------------------------------------------------------------------

def _kinds(created):
    return sorted(n.kind for n in created)


def test_alta_de_externa_sin_acompanante_no_avisa(ctx):
    from app.services import notification_service as ns

    visit = _external(ctx, agent=ctx.carlos)
    assert ns.notify_visit_created(ctx.db, visit, actor=ctx.carlos_user) == []


def test_alta_de_externa_avisa_al_acompanante_y_no_a_un_captador(ctx):
    from app.services import notification_service as ns
    from app.services.notification_service import NotificationKind

    visit = _external(ctx, agent=ctx.carlos, companion=ctx.laura)
    created = ns.notify_visit_created(ctx.db, visit, actor=ctx.carlos_user)
    assert _kinds(created) == [NotificationKind.VISIT_AS_COMPANION]
    [notice] = created
    assert notice.user_id == ctx.laura_user.id
    assert notice.company_id == ctx.moyza.id
    assert notice.url == "/visits"
    assert notice.body == "Piso en Calle Externa 12, 3ºB, Úbeda · visitante: PYTEST-EXT VISITANTE"


def test_ficha_completada_y_envio_fallido_de_externa(ctx):
    from app.services import notification_service as ns
    from app.services.notification_service import NotificationKind

    visit = _external(ctx, agent=ctx.carlos, companion=ctx.laura, phone="34600999888")
    done = ns.notify_visit_completed(ctx.db, visit, actor=None, sent=True)
    assert {n.user_id for n in done} == {ctx.carlos_user.id, ctx.laura_user.id}
    assert all(n.kind == NotificationKind.VISIT_COMPLETED and n.url == "/visits" for n in done)

    failed = ns.notify_visit_sheet_failed(ctx.db, visit, actor=None)
    assert [n.user_id for n in failed] == [ctx.carlos_user.id]
    assert failed[0].body.startswith("Piso en Calle Externa 12")


# ---------------------------------------------------------------------------
# WhatsApp: log de envío y pantalla de logs
# ---------------------------------------------------------------------------

def test_log_de_whatsapp_de_una_externa(ctx):
    from app.models.visit_whatsapp_log import VisitWhatsappLog
    from app.services.dashboard_service import DashboardService
    from app.services.visit_whatsapp_log_service import log_whatsapp_attempt
    from app.web.template_env import templates

    visit = _external(ctx, agent=ctx.carlos)
    now = datetime.utcnow()
    log = log_whatsapp_attempt(ctx.db, visit_id=visit.id, recipient_type="comprador", status="ERROR",
                               trigger="finalize", property_id=visit.property_id,
                               recipient_name=visit.visitor_name, error_message="PYTEST")
    assert log is not None and log.property_id is None
    log.attempted_at = now
    ctx.db.flush()

    # «Requiere atención» del Inicio cuenta el envío fallido en la empresa de la visita
    assert DashboardService(ctx.db, ctx.moyza.id).whatsapp_errors_count(now) >= 1

    from app.web.routes.report_logs import _scope_visit_whatsapp_logs
    scoped = _scope_visit_whatsapp_logs(ctx.db.query(VisitWhatsappLog), ctx.moyza.id)
    assert scoped.filter(VisitWhatsappLog.id == log.id).count() == 1

    html = templates.env.get_template("report_logs/visit_whatsapp_table.html").render(visit_whatsapp_logs=[log])
    assert "Piso en Calle Externa 12, 3ºB, Úbeda" in html
    assert "Propiedad externa" in html
    assert "/properties/None" not in html


# ---------------------------------------------------------------------------
# Registro de actividad
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("method, path, label", [
    ("GET", "/visits/new-external", "Abrió el formulario de visita a una propiedad externa"),
    ("POST", "/visits/new-external", "Registró una visita a una propiedad externa"),
    ("POST", "/visits/create-external", "Registró una visita a una propiedad externa"),
])
def test_actividad_del_alta_externa(method, path, label):
    from app.services.activity_log_view import describe

    row = describe(method, path, 200)
    assert row["module"] == "Visitas" and row["label"] == label
