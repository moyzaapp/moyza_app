"""
Revisión obligatoria de las propiedades nuevas por el captador
(PLAN_REVISION_PROPIEDADES_NUEVAS.md §6, servicio).

Con base de datos, dentro de una transacción externa que se deshace al
terminar (los commit del servicio solo cierran savepoints), patrón de
test_notification_service.py: registro (P1, P3, P7), avisos (violet, una vez,
captador sin usuario), transiciones de §4.1, gancho de compradores
compatibles (plan 2), recordatorio único en horas hábiles (P5) y lecturas por
empresa para el Inicio y «Requiere atención».

    docker exec moyza_backend python -m pytest tests/test_property_review_service.py -q
"""
import sys
from datetime import datetime, timedelta
from types import ModuleType, SimpleNamespace

import pytest

from app.core.constants import PropertyReviewStatus as S
from app.models.notification import Notification
from app.models.property_review import PropertyReview
from app.services import notification_service as ns
from app.services import property_review_service as svc
from app.services.notification_service import NotificationKind


# Martes 24/11/2026 10:00 en Madrid (09:00 UTC); jueves 26 a la misma hora = 48 h hábiles
NOW = datetime(2026, 11, 24, 9, 0)


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
def ctx(db, monkeypatch):
    """MOYZA y MOES; Laura (agente con usuario, en las dos), Carlos (con usuario,
    MOYZA), Pepe (agente sin usuario) y un admin. Ninguna propiedad propia aún."""
    from app.core.config import settings
    from app.models.agent import Agent
    from app.models.company import Company
    from app.models.role import Role
    from app.models.user import User

    monkeypatch.setattr(settings, "PROPERTY_REVIEW_MAX_AGE_DAYS", 15)
    monkeypatch.setattr(settings, "PROPERTY_REVIEW_REMINDER_BUSINESS_HOURS", 48)

    # Ninguna propiedad real sin revisión debe colarse en las pasadas del test
    from app.models.property import Property
    orphans = (
        db.query(Property.id)
        .outerjoin(PropertyReview, PropertyReview.property_id == Property.id)
        .filter(PropertyReview.id.is_(None))
        .all()
    )
    for (pid,) in orphans:
        db.add(PropertyReview(property_id=pid, status=S.SKIPPED, rounds=0, created_at=NOW))
    db.query(PropertyReview).filter(PropertyReview.status == S.PENDING,
                                    PropertyReview.notified_at.is_(None)).update(
        {PropertyReview.notified_at: NOW - timedelta(days=30)}, synchronize_session=False)
    db.flush()

    moyza = db.query(Company).filter_by(code="MOYZA").one()
    moes = db.query(Company).filter_by(code="MOES").one()
    admin_role = db.query(Role).filter(Role.name.ilike("admin")).first()
    agent_role = db.query(Role).filter(Role.name.ilike("agent")).first()

    laura_agent = Agent(name="PYTEST-REV LAURA", email="pytest.rev.laura@example.com")
    carlos_agent = Agent(name="PYTEST-REV CARLOS", email="pytest.rev.carlos@example.com")
    pepe_agent = Agent(name="PYTEST-REV PEPE", email="pytest.rev.pepe@example.com")
    laura_agent.companies.extend([moyza, moes])
    carlos_agent.companies.append(moyza)
    pepe_agent.companies.append(moyza)
    laura = User(email="pytest.rev.laura@example.com", full_name="Laura", hashed_password="x",
                 is_active=True, role=agent_role)
    carlos = User(email="pytest.rev.carlos@example.com", full_name="Carlos", hashed_password="x",
                  is_active=True, role=agent_role)
    admin = User(email="pytest.rev.admin@example.com", full_name="Admin Rev", hashed_password="x",
                 is_active=True, role=admin_role)
    db.add_all([laura_agent, carlos_agent, pepe_agent, laura, carlos, admin])
    db.flush()
    return SimpleNamespace(db=db, moyza=moyza, moes=moes, laura_agent=laura_agent, carlos_agent=carlos_agent,
                           pepe_agent=pepe_agent, laura=laura, carlos=carlos, admin=admin)


def _prop(ctx, title="PYTEST-REV Piso", agent=None, company=None, status="Activa", entry=NOW - timedelta(days=1)):
    from app.models.property import Property
    prop = Property(title=title, address="Calle Real 12, 3ºA", city="Jaén", zona="Centro", property_type="Piso",
                    business_type="Venta", price=120000, status=status, market_entry_date=entry,
                    company_id=(company or ctx.moyza).id, agent_id=agent.id if agent is not None else None)
    ctx.db.add(prop)
    ctx.db.flush()
    return prop


def _review(ctx, prop):
    ctx.db.expire_all()
    return svc.review_for_property(ctx.db, prop.id)


def _notifications(ctx, user=None, review=None, unread=None):
    query = ctx.db.query(Notification).filter(Notification.entity_type == svc.ENTITY)
    if user is not None:
        query = query.filter(Notification.user_id == user.id)
    if review is not None:
        query = query.filter(Notification.entity_id == review.id)
    if unread is not None:
        query = query.filter(Notification.read_at.is_(None) if unread else Notification.read_at.isnot(None))
    return query.order_by(Notification.id).all()


def _pending(ctx, prop, agent=None, now=NOW):
    """Propiedad registrada y avisada: revisión `pending` con `notified_at` = now."""
    svc.register_new_properties(ctx.db, now=now)
    svc.notify_pending(ctx.db, now=now)
    return _review(ctx, prop)


# ---------------------------------------------------------------------------
# Registro (P1, P3, P7)
# ---------------------------------------------------------------------------

def test_backfill_ninguna_existente_queda_pendiente(ctx):
    """Lo que había al desplegar tiene fila `skipped` (la migración): no pide revisión."""
    prop = _prop(ctx, agent=ctx.laura_agent)
    ctx.db.add(PropertyReview(property_id=prop.id, agent_id=ctx.laura_agent.id, status=S.SKIPPED,
                              rounds=0, created_at=NOW))
    ctx.db.flush()
    assert svc.register_new_properties(ctx.db, now=NOW) == []
    assert svc.pending_for_agent(ctx.db, ctx.laura_agent.id) == []
    assert ctx.db.query(PropertyReview).filter(PropertyReview.status == S.PENDING,
                                               PropertyReview.notified_at.is_(None)).count() == 0


def test_registro_activa_vendida_y_sin_captador(ctx):
    active = _prop(ctx, "PYTEST-REV activa", agent=ctx.laura_agent)
    sold = _prop(ctx, "PYTEST-REV vendida", agent=ctx.laura_agent, status="Vendida")
    orphan = _prop(ctx, "PYTEST-REV sin captador")

    created = svc.register_new_properties(ctx.db, now=NOW)
    assert {r.property_id: r.status for r in created} == {active.id: S.PENDING, sold.id: S.SKIPPED}
    assert _review(ctx, active).agent_id == ctx.laura_agent.id
    assert _review(ctx, orphan) is None
    # Idempotente
    assert svc.register_new_properties(ctx.db, now=NOW) == []

    # Al tener captador, la siguiente pasada la recoge
    orphan.agent_id = ctx.carlos_agent.id
    ctx.db.flush()
    [late] = svc.register_new_properties(ctx.db, now=NOW + timedelta(minutes=10))
    assert (late.property_id, late.status, late.agent_id) == (orphan.id, S.PENDING, ctx.carlos_agent.id)


def test_p7_alta_reciente_queda_pending(ctx):
    prop = _prop(ctx, "PYTEST-REV reciente", agent=ctx.laura_agent, entry=NOW - timedelta(days=14))
    svc.register_new_properties(ctx.db, now=NOW)
    assert _review(ctx, prop).status == S.PENDING
    assert svc.notify_pending(ctx.db, now=NOW) == 1


def test_p7_alta_antigua_queda_skipped_sin_aviso(ctx):
    """Más de PROPERTY_REVIEW_MAX_AGE_DAYS (15) días desde market_entry_date: carga histórica."""
    prop = _prop(ctx, "PYTEST-REV antigua", agent=ctx.laura_agent, entry=NOW - timedelta(days=16))
    svc.register_new_properties(ctx.db, now=NOW)
    assert _review(ctx, prop).status == S.SKIPPED
    assert svc.notify_pending(ctx.db, now=NOW) == 0
    assert _notifications(ctx, ctx.laura) == []


def test_p7_sin_fecha_de_alta_se_trata_como_nueva(ctx):
    prop = _prop(ctx, "PYTEST-REV sin fecha", agent=ctx.laura_agent)
    prop.market_entry_date = None
    ctx.db.flush()
    svc.register_new_properties(ctx.db, now=NOW)
    assert _review(ctx, prop).status == S.PENDING
    assert svc.notify_pending(ctx.db, now=NOW) == 1


# ---------------------------------------------------------------------------
# Avisos
# ---------------------------------------------------------------------------

def test_notify_pending_una_vez_violet_y_con_ancla(ctx):
    prop = _prop(ctx, agent=ctx.laura_agent)
    svc.register_new_properties(ctx.db, now=NOW)
    assert svc.notify_pending(ctx.db, now=NOW) == 1

    review = _review(ctx, prop)
    assert review.notified_at == NOW
    [n] = _notifications(ctx, ctx.laura)
    assert n.kind == NotificationKind.PROPERTY_REVIEW_PENDING
    assert n.company_id == ctx.moyza.id
    assert n.url == f"/properties/{prop.id}#revision"
    assert n.title == "Propiedad nueva: revisa la ficha · PYTEST-REV Piso"
    assert n.body.startswith("Piso en Centro, Jaén · 120.000 €")
    data = ns.serialize(n)
    assert (data["icon"], data["tone"]) == ("clipboard", "violet")

    # Segunda pasada: nada
    assert svc.notify_pending(ctx.db, now=NOW + timedelta(minutes=10)) == 0
    assert len(_notifications(ctx, ctx.laura)) == 1
    # A nadie más
    assert _notifications(ctx, ctx.carlos) == [] and _notifications(ctx, ctx.admin) == []


def test_captador_sin_usuario_marca_notified_sin_avisos(ctx):
    prop = _prop(ctx, agent=ctx.pepe_agent)
    svc.register_new_properties(ctx.db, now=NOW)
    assert svc.notify_pending(ctx.db, now=NOW) == 0
    assert _review(ctx, prop).notified_at == NOW


# ---------------------------------------------------------------------------
# Transiciones (§4.1)
# ---------------------------------------------------------------------------

def test_ciclo_completo_revisar_corregir_y_ok(ctx):
    prop = _prop(ctx, agent=ctx.laura_agent)
    review = _pending(ctx, prop)

    with pytest.raises(ValueError):
        svc.flag_issues(ctx.db, review, ctx.laura, "   ", now=NOW)
    with pytest.raises(ValueError):
        svc.flag_issues(ctx.db, review, ctx.laura, "x" * (svc.COMMENT_MAX + 1), now=NOW)
    with pytest.raises(ValueError):
        svc.mark_fixed(ctx.db, review, ctx.admin, "nada", now=NOW)

    svc.flag_issues(ctx.db, review, ctx.laura, " El precio es 135.000 € ", now=NOW + timedelta(hours=1))
    assert (review.status, review.agent_comment, review.rounds) == (S.ISSUES, "El precio es 135.000 €", 1)
    assert review.flagged_at == NOW + timedelta(hours=1)
    # El aviso inicial queda leído
    assert _notifications(ctx, ctx.laura, review, unread=True) == []

    # El captador no puede dar el OK con observaciones; el admin sí (P4), pero aquí corrige
    with pytest.raises(ValueError):
        svc.mark_ok(ctx.db, review, ctx.laura, now=NOW)
    svc.mark_fixed(ctx.db, review, ctx.admin, "Precio actualizado", now=NOW + timedelta(hours=2))
    assert (review.status, review.admin_comment, review.fixed_by) == (S.FIXED, "Precio actualizado", ctx.admin.id)
    [fixed_notice] = _notifications(ctx, ctx.laura, review, unread=True)
    assert fixed_notice.kind == NotificationKind.PROPERTY_REVIEW_FIXED
    assert fixed_notice.title == "Propiedad corregida: confirma que está correcta · PYTEST-REV Piso"
    assert fixed_notice.body == "Precio actualizado"
    assert _notifications(ctx, ctx.admin) == []   # nunca al actor

    # Segunda vuelta
    svc.flag_issues(ctx.db, review, ctx.laura, "Faltan los m²", now=NOW + timedelta(hours=3))
    assert (review.status, review.rounds) == (S.ISSUES, 2)
    svc.mark_fixed(ctx.db, review, ctx.admin, "", now=NOW + timedelta(hours=4))
    assert review.admin_comment is None

    svc.mark_ok(ctx.db, review, ctx.laura, now=NOW + timedelta(hours=5))
    assert (review.status, review.ok_by, review.ok_at) == (S.OK, ctx.laura.id, NOW + timedelta(hours=5))
    assert _notifications(ctx, ctx.laura, review, unread=True) == []
    for action in (lambda: svc.flag_issues(ctx.db, review, ctx.laura, "otra", now=NOW),
                   lambda: svc.mark_ok(ctx.db, review, ctx.admin, now=NOW, by_admin=True),
                   lambda: svc.mark_fixed(ctx.db, review, ctx.admin, None, now=NOW)):
        with pytest.raises(ValueError):
            action()


def test_admin_da_el_ok_desde_pending_y_desde_issues(ctx):
    first = _prop(ctx, "PYTEST-REV uno", agent=ctx.laura_agent)
    second = _prop(ctx, "PYTEST-REV dos", agent=ctx.laura_agent)
    svc.register_new_properties(ctx.db, now=NOW)
    svc.notify_pending(ctx.db, now=NOW)
    r1, r2 = _review(ctx, first), _review(ctx, second)

    svc.mark_ok(ctx.db, r1, ctx.admin, now=NOW, by_admin=True)
    assert (r1.status, r1.ok_by) == (S.OK, ctx.admin.id)
    svc.flag_issues(ctx.db, r2, ctx.laura, "Revisar dirección", now=NOW)
    svc.mark_ok(ctx.db, r2, ctx.admin, now=NOW, by_admin=True)
    assert r2.status == S.OK


def test_can_review_quien_puede_que(ctx):
    prop = _prop(ctx, agent=ctx.laura_agent)
    review = _pending(ctx, prop)

    captador = svc.can_review(review, ctx.laura, ctx.laura_agent, False)
    assert (captador["ok"], captador["issues"], captador["fixed"]) == (True, True, False)
    other = svc.can_review(review, ctx.carlos, ctx.carlos_agent, False)
    assert not any((other["ok"], other["issues"], other["fixed"]))
    admin = svc.can_review(review, ctx.admin, None, True)
    assert (admin["ok"], admin["issues"], admin["fixed"]) == (True, False, False)

    svc.flag_issues(ctx.db, review, ctx.laura, "Revisar", now=NOW)
    assert not any(svc.can_review(review, ctx.laura, ctx.laura_agent, False)[k] for k in ("ok", "issues", "fixed"))
    admin = svc.can_review(review, ctx.admin, None, True)
    assert (admin["ok"], admin["fixed"]) == (True, True)
    assert svc.can_review(None, ctx.admin, None, True)["ok"] is False


# ---------------------------------------------------------------------------
# Gancho de compradores compatibles (plan 2)
# ---------------------------------------------------------------------------

def _fake_match_service(monkeypatch, fn):
    import app.services as services_pkg
    module = ModuleType("app.services.property_match_service")
    module.match_property = fn
    monkeypatch.setitem(sys.modules, "app.services.property_match_service", module)
    monkeypatch.setattr(services_pkg, "property_match_service", module, raising=False)


def test_mark_ok_llama_a_match_property(ctx, monkeypatch):
    calls = []
    _fake_match_service(monkeypatch, lambda db, prop, now, actor=None: calls.append((prop.id, now, actor.id)) or [])
    prop = _prop(ctx, agent=ctx.laura_agent)
    review = _pending(ctx, prop)
    svc.mark_ok(ctx.db, review, ctx.laura, now=NOW)
    assert calls == [(prop.id, NOW, ctx.laura.id)]


def test_si_match_property_falla_el_ok_se_guarda(ctx, monkeypatch):
    def boom(db, prop, now, actor=None):
        raise RuntimeError("plan 2 roto")
    _fake_match_service(monkeypatch, boom)
    prop = _prop(ctx, agent=ctx.laura_agent)
    review = _pending(ctx, prop)
    svc.mark_ok(ctx.db, review, ctx.laura, now=NOW)
    assert _review(ctx, prop).status == S.OK


def test_sin_property_match_service_el_ok_funciona(ctx, monkeypatch):
    import app.services as services_pkg
    monkeypatch.setitem(sys.modules, "app.services.property_match_service", None)   # ImportError
    monkeypatch.delattr(services_pkg, "property_match_service", raising=False)
    prop = _prop(ctx, agent=ctx.laura_agent)
    review = _pending(ctx, prop)
    svc.mark_ok(ctx.db, review, ctx.laura, now=NOW)
    assert _review(ctx, prop).status == S.OK


# ---------------------------------------------------------------------------
# Recordatorio único (P5)
# ---------------------------------------------------------------------------

def test_recordatorio_a_las_48h_habiles_y_solo_uno(ctx):
    prop = _prop(ctx, agent=ctx.laura_agent)
    review = _pending(ctx, prop)

    assert svc.remind_overdue(ctx.db, now=NOW + timedelta(hours=47)) == 0
    # Jueves a la misma hora: 48 h hábiles
    assert svc.remind_overdue(ctx.db, now=NOW + timedelta(hours=48)) == 1
    review = _review(ctx, prop)
    assert review.reminded_at == NOW + timedelta(hours=48)
    unread = _notifications(ctx, ctx.laura, review, unread=True)
    assert [n.title for n in unread] == ["Sigue pendiente: revisa la propiedad · PYTEST-REV Piso"]
    assert len(_notifications(ctx, ctx.laura, review)) == 2   # el primero, leído
    assert svc.remind_overdue(ctx.db, now=NOW + timedelta(days=10)) == 0


def test_recordatorio_de_corregida_cuenta_desde_fixed_at(ctx):
    prop = _prop(ctx, agent=ctx.laura_agent)
    review = _pending(ctx, prop)
    assert svc.remind_overdue(ctx.db, now=NOW + timedelta(hours=48)) == 1

    later = NOW + timedelta(days=2, hours=1)   # jueves 11:00
    svc.flag_issues(ctx.db, review, ctx.laura, "Revisar precio", now=later)
    svc.mark_fixed(ctx.db, review, ctx.admin, "Hecho", now=later)
    assert review.reminded_at is None
    # Viernes 11:00: 24 h hábiles desde fixed_at; aún no
    assert svc.remind_overdue(ctx.db, now=later + timedelta(days=1)) == 0
    # Lunes 11:00: 48 h hábiles (el fin de semana no cuenta)
    assert svc.remind_overdue(ctx.db, now=later + timedelta(days=4)) == 1
    [n] = _notifications(ctx, ctx.laura, review, unread=True)
    assert n.kind == NotificationKind.PROPERTY_REVIEW_FIXED
    assert n.title.startswith("Sigue pendiente: confirma que está correcta")


def test_vendida_antes_de_revisar_no_recuerda_ni_cuenta(ctx):
    prop = _prop(ctx, agent=ctx.laura_agent)
    _pending(ctx, prop)
    prop.status = "Vendida"
    ctx.db.flush()
    assert svc.remind_overdue(ctx.db, now=NOW + timedelta(days=5)) == 0
    assert svc.pending_for_agent(ctx.db, ctx.laura_agent.id) == []


# ---------------------------------------------------------------------------
# Lecturas por empresa
# ---------------------------------------------------------------------------

def test_pending_for_agent_y_counts_for_admin_por_empresa(ctx):
    moyza_prop = _prop(ctx, "PYTEST-REV MOYZA", agent=ctx.laura_agent)
    moes_prop = _prop(ctx, "PYTEST-REV MOES", agent=ctx.laura_agent, company=ctx.moes)
    carlos_prop = _prop(ctx, "PYTEST-REV Carlos", agent=ctx.carlos_agent)
    svc.register_new_properties(ctx.db, now=NOW)
    svc.notify_pending(ctx.db, now=NOW)

    ids = lambda reviews: [r.property_id for r in reviews]
    assert ids(svc.pending_for_agent(ctx.db, ctx.laura_agent.id, ctx.moyza.id)) == [moyza_prop.id]
    assert ids(svc.pending_for_agent(ctx.db, ctx.laura_agent.id, [ctx.moyza.id, ctx.moes.id])) == [
        moyza_prop.id, moes_prop.id]
    assert svc.pending_count_for_agent(ctx.db, ctx.laura_agent.id, ctx.moes.id) == 1
    assert svc.pending_count_for_user(ctx.db, ctx.laura, [ctx.moyza.id, ctx.moes.id]) == 2

    svc.flag_issues(ctx.db, _review(ctx, carlos_prop), ctx.carlos, "Revisar", now=NOW)
    assert svc.counts_for_admin(ctx.db, ctx.moyza.id, NOW + timedelta(hours=1)) == {"issues": 1, "overdue": 0}
    assert svc.counts_for_admin(ctx.db, ctx.moyza.id, NOW + timedelta(hours=48)) == {"issues": 1, "overdue": 1}
    assert svc.counts_for_admin(ctx.db, ctx.moes.id, NOW + timedelta(hours=48)) == {"issues": 0, "overdue": 1}
    assert svc.open_count_for_company(ctx.db, ctx.moyza.id) == 2
    # La de Carlos espera al admin: no está en las del captador
    assert svc.pending_for_agent(ctx.db, ctx.carlos_agent.id, ctx.moyza.id) == []
    # …y es la que el admin de MOYZA tiene por corregir (ventana y bloque del Inicio)
    issues = svc.issues_for_admin(ctx.db, ctx.moyza.id)
    assert ids(issues) == [carlos_prop.id] and issues[0].property.agent.id == ctx.carlos_agent.id
    assert svc.issues_for_admin(ctx.db, ctx.moes.id) == []
    svc.mark_fixed(ctx.db, issues[0], ctx.admin, now=NOW + timedelta(hours=1))
    assert svc.issues_for_admin(ctx.db, ctx.moyza.id) == []


def test_inicio_del_agente_y_atencion_del_admin(ctx):
    from app.services.dashboard_service import DashboardService
    prop = _prop(ctx, agent=ctx.laura_agent)
    review = _pending(ctx, prop)

    svc_dash = DashboardService(ctx.db, ctx.moyza.id)
    assert [r.id for r in svc_dash.pending_reviews_for_agent(ctx.laura_agent.id)] == [review.id]
    assert svc_dash.pending_reviews_for_agent(ctx.carlos_agent.id) == []

    titles = lambda now: [i["title"] for i in svc_dash.attention([], [], now) if i["icon"] == "clipboard"]
    assert titles(NOW + timedelta(hours=1)) == []
    assert titles(NOW + timedelta(hours=48)) == ["1 propiedad nueva sin revisar desde hace más de 48 h hábiles"]
    svc.flag_issues(ctx.db, review, ctx.laura, "Revisar", now=NOW + timedelta(hours=1))
    items = [i for i in svc_dash.attention([], [], NOW + timedelta(hours=2)) if i["icon"] == "clipboard"]
    assert [(i["title"], i["tone"], i["href"]) for i in items] == [
        ("1 propiedad con observaciones del captador", "amber", "/properties?filtro=revision")]


def test_jobs_registran_avisan_y_recuerdan(ctx, monkeypatch):
    """Los jobs del scheduler abren su propia sesión: se les da la del test."""
    from app.jobs import scheduler
    monkeypatch.setattr(scheduler, "SessionLocal", lambda: _NoClose(ctx.db))
    prop = _prop(ctx, agent=ctx.laura_agent)
    assert scheduler.register_property_reviews(now=NOW) == (1, 1)
    assert scheduler.register_property_reviews(now=NOW + timedelta(minutes=10)) == (0, 0)
    assert scheduler.remind_property_reviews(now=NOW + timedelta(hours=48)) == 1
    assert _review(ctx, prop).reminded_at is not None
    # Sábado: no avisa
    assert scheduler.remind_property_reviews(now=datetime(2026, 11, 28, 9, 0)) == 0


class _NoClose:
    def __init__(self, session):
        self._session = session

    def close(self):
        pass

    def __getattr__(self, name):
        return getattr(self._session, name)
