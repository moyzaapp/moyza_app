"""
Compradores compatibles con una propiedad nueva: servicio
(PLAN_COMPRADORES_COMPATIBLES_PROPIEDAD_NUEVA.md §4.3, §4.4, §7).

Con PostgreSQL dentro de una transacción externa que se deshace al terminar
(los commit del servicio solo cierran savepoints), patrón de
test_notification_service.py. La propiedad de prueba está en una población
inventada para que los perfiles reales de la base no encajen con ella.

- Candidatos (P2): abiertas sí, cerradas no, perfil incompleto no, sin
  comprador no, agente inactivo no, Alquiler no, las dos empresas sí.
- Un aviso por agente y empresa (P1) con el conteo, violet; nunca al actor;
  agente sin usuario -> fila sin `notified_at`.
- Idempotencia, propiedad no activa o sin captador, y el OK del plan 1
  (`mark_ok`) produce los cruces aunque el cruce falle el OK se guarda.

    docker exec moyza_backend python -m pytest tests/test_property_match_service.py -q
"""
from datetime import datetime
from types import SimpleNamespace

import pytest

from app.core.constants import AlertStatus
from app.core.constants import PropertyReviewStatus as RS
from app.models.notification import Notification
from app.models.property_buyer_match import PropertyBuyerMatch
from app.models.property_review import PropertyReview
from app.services import property_match_service as svc
from app.services import property_review_service as review_svc
from app.services.notification_service import NotificationKind


NOW = datetime(2026, 11, 24, 9, 0)
CITY = "PYTEST-PM Villanueva"


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
    """MOYZA y MOES; admin; Ana (MOYZA, con usuario, captadora), Bea (MOYZA y
    MOES, con usuario), Pepe (sin usuario) e Inés (inactiva). Propiedad Piso
    de Ana en MOYZA (150.000 €, 3 dorm.) y once alertas: cinco encajan
    (Ana ×2 en MOYZA, Bea en MOES y en MOYZA, Pepe) y seis no."""
    from app.models.agent import Agent
    from app.models.company import Company
    from app.models.property import Property
    from app.models.role import Role
    from app.models.user import User

    moyza = db.query(Company).filter_by(code="MOYZA").one()
    moes = db.query(Company).filter_by(code="MOES").one()
    admin_role = db.query(Role).filter(Role.name.ilike("admin")).first()
    agent_role = db.query(Role).filter(Role.name.ilike("agent")).first()

    admin = User(email="pytest.pm.admin@example.com", full_name="Admin PM", hashed_password="x",
                 is_active=True, role=admin_role)
    admin.companies.append(moyza)
    users, agents = {}, {}
    for key, companies, has_user, active in (("ana", [moyza], True, True), ("bea", [moyza, moes], True, True),
                                             ("pepe", [moyza], False, True), ("ines", [moyza], True, False)):
        agents[key] = Agent(name=f"PYTEST-PM {key.title()}", email=f"pytest.pm.{key}@example.com", is_active=active)
        agents[key].companies.extend(companies)
        if has_user:
            users[key] = User(email=f"pytest.pm.{key}@example.com", full_name=key.title(), hashed_password="x",
                              is_active=True, role=agent_role)
            users[key].companies.extend(companies)
    db.add_all([admin, *users.values(), *agents.values()])
    db.flush()

    prop = Property(title="PYTEST-PM Piso", city=CITY, zona="Centro", property_type="Piso", business_type="Venta",
                    price=150000, status="Activa", num_dormitorios=3, num_banos_aseos=2,
                    public_url="https://example.com/pm", company_id=moyza.id, agent_id=agents["ana"].id)
    db.add(prop)
    db.flush()
    env = SimpleNamespace(db=db, moyza=moyza, moes=moes, admin=admin, users=users, agents=agents, prop=prop,
                          alerts={})

    _alert(env, "a1", "ana", moyza)
    _alert(env, "a2", "ana", moyza, status=AlertStatus.IN_PROGRESS)
    _alert(env, "b_moes", "bea", moes)
    _alert(env, "b_moyza", "bea", moyza)
    _alert(env, "pepe", "pepe", moyza)
    _alert(env, "cerrada", "ana", moyza, status=AlertStatus.COMPLETED)
    _alert(env, "cancelada", "bea", moyza, status=AlertStatus.CANCELLED)
    _alert(env, "incompleto", "ana", moyza, profile=dict(max_bedrooms=None))
    _alert(env, "sin_comprador", "ana", moyza, buyer=False)
    _alert(env, "inactiva", "ines", moyza)
    _alert(env, "caro", "bea", moyza, profile=dict(max_price=140000))
    _alert(env, "alquiler", "bea", moyza, business_type="Alquiler")
    db.flush()
    return env


def _alert(env, key, agent_key, company, status=AlertStatus.PENDING, profile=None, buyer=True,
           business_type="Venta"):
    from app.models.buyer import Buyer
    from app.models.buyer_search_criteria import BuyerSearchCriteria
    from app.models.property_alert import PropertyAlert

    db = env.db
    name = f"PYTEST-PM Comprador {key}"
    buyer_obj = None
    if buyer:
        buyer_obj = Buyer(name=name, phone="34600111222", company_id=company.id)
        db.add(buyer_obj)
        db.flush()
        fields = dict(property_types=["Piso"], property_type="Piso", business_type="Venta", max_price=160000,
                      max_bedrooms=3, cities=[CITY], zones=["Centro"])
        fields.update(profile or {})
        db.add(BuyerSearchCriteria(buyer_id=buyer_obj.id, created_at=NOW, **fields))
    alert = PropertyAlert(company_id=company.id, agent_id=env.agents[agent_key].id, lead_name=name,
                          lead_phone="34600111222", status=status, priority="NORMAL", origin="search",
                          business_type=business_type, buyer_id=buyer_obj.id if buyer_obj else None,
                          created_by=env.admin.id, created_at=NOW, assigned_at=NOW)
    db.add(alert)
    db.flush()
    env.alerts[key] = alert
    return alert


def _ids(env, *keys):
    return {env.alerts[k].id for k in keys}


def _matches(env):
    env.db.expire_all()
    return env.db.query(PropertyBuyerMatch).filter(PropertyBuyerMatch.property_id == env.prop.id).all()


def _notifications(env, user=None):
    query = env.db.query(Notification).filter(Notification.kind == NotificationKind.PROPERTY_MATCH,
                                              Notification.entity_type == "property",
                                              Notification.entity_id == env.prop.id)
    if user is not None:
        query = query.filter(Notification.user_id == user.id)
    return query.order_by(Notification.company_id, Notification.id).all()


# ---------------------------------------------------------------------------
# Candidatos (P2)
# ---------------------------------------------------------------------------

def test_candidatos(ctx):
    ids = {a.id for a in svc.candidate_alerts(ctx.db, ctx.prop)}
    # Abiertas de agentes activos con perfil completo, de las dos empresas
    assert ids == _ids(ctx, "a1", "a2", "b_moes", "b_moyza", "pepe")


def test_propiedad_no_activa_o_sin_captador(ctx):
    ctx.prop.status = "Vendida"
    assert svc.candidate_alerts(ctx.db, ctx.prop) == []
    assert svc.match_property(ctx.db, ctx.prop, NOW, actor=ctx.admin) == []
    ctx.prop.status = "Activa"
    ctx.prop.agent_id = None
    assert svc.match_property(ctx.db, ctx.prop, NOW, actor=ctx.admin) == []
    assert _matches(ctx) == []
    assert _notifications(ctx) == []


# ---------------------------------------------------------------------------
# Cruce y avisos (P1)
# ---------------------------------------------------------------------------

def test_un_aviso_por_agente_y_empresa(ctx):
    created = svc.match_property(ctx.db, ctx.prop, NOW, actor=ctx.admin)
    assert {m.alert_id for m in created} == _ids(ctx, "a1", "a2", "b_moes", "b_moyza", "pepe")

    rows = {m.alert_id: m for m in _matches(ctx)}
    assert rows[ctx.alerts["b_moes"].id].company_id == ctx.moes.id
    assert rows[ctx.alerts["a1"].id].agent_id == ctx.agents["ana"].id
    assert all(m.created_at == NOW for m in rows.values())
    # Pepe no tiene usuario: su fila queda sin aviso
    assert rows[ctx.alerts["pepe"].id].notified_at is None
    assert all(m.notified_at == NOW for k, m in rows.items() if k != ctx.alerts["pepe"].id)

    ana = _notifications(ctx, ctx.users["ana"])
    assert [n.title for n in ana] == ["2 compradores encajan con una propiedad nueva · PYTEST-PM Piso"]
    assert ana[0].company_id == ctx.moyza.id
    assert ana[0].url == f"/properties/{ctx.prop.id}/matches"
    assert ana[0].body == ("Piso en Centro, PYTEST-PM Villanueva · 150.000 € · "
                           "PYTEST-PM Comprador a1, PYTEST-PM Comprador a2")
    assert ana[0].actor_user_id == ctx.admin.id
    assert NotificationKind.style(ana[0].kind) == ("users", "violet")

    # Bea: una en cada empresa (vista unificada, con su distintivo)
    bea = _notifications(ctx, ctx.users["bea"])
    assert sorted((n.company_id, n.title) for n in bea) == sorted([
        (ctx.moyza.id, "1 comprador encaja con una propiedad nueva · PYTEST-PM Piso"),
        (ctx.moes.id, "1 comprador encaja con una propiedad nueva · PYTEST-PM Piso"),
    ])
    assert len(_notifications(ctx)) == 3
    # Nunca se toca la lista de interés ni se crea un seguimiento (P5)
    for key in ("a1", "a2", "b_moes", "b_moyza", "pepe"):
        alert = ctx.alerts[key]
        ctx.db.refresh(alert)
        assert alert.extra_properties == [] and alert.property_id is None
        assert alert.follow_ups == []


def test_no_se_avisa_al_actor(ctx):
    """Ana da el OK a su propiedad y tiene compradores compatibles: no se avisa a sí misma."""
    svc.match_property(ctx.db, ctx.prop, NOW, actor=ctx.users["ana"])
    assert _notifications(ctx, ctx.users["ana"]) == []
    rows = [m for m in _matches(ctx) if m.agent_id == ctx.agents["ana"].id]
    assert len(rows) == 2 and all(m.notified_at == NOW for m in rows)
    assert len(_notifications(ctx, ctx.users["bea"])) == 2


def test_idempotente(ctx):
    assert len(svc.match_property(ctx.db, ctx.prop, NOW, actor=ctx.admin)) == 5
    assert svc.match_property(ctx.db, ctx.prop, NOW, actor=ctx.admin) == []
    assert len(_matches(ctx)) == 5
    assert len(_notifications(ctx)) == 3

    # Una alerta nueva que encaja: solo esa entra y solo se avisa a su agente
    from app.models.agent import Agent
    from app.models.user import User
    carla_agent = Agent(name="PYTEST-PM Carla", email="pytest.pm.carla@example.com", is_active=True)
    carla_agent.companies.append(ctx.moyza)
    carla = User(email="pytest.pm.carla@example.com", full_name="Carla", hashed_password="x", is_active=True,
                 role=ctx.users["ana"].role)
    carla.companies.append(ctx.moyza)
    ctx.db.add_all([carla_agent, carla])
    ctx.db.flush()
    ctx.agents["carla"] = carla_agent
    _alert(ctx, "carla", "carla", ctx.moyza)
    created = svc.match_property(ctx.db, ctx.prop, NOW, actor=ctx.admin)
    assert [m.alert_id for m in created] == [ctx.alerts["carla"].id]
    assert len(_matches(ctx)) == 6
    assert [n.title for n in _notifications(ctx, carla)] == [
        "1 comprador encaja con una propiedad nueva · PYTEST-PM Piso"]
    assert len(_notifications(ctx)) == 4


def test_cuerpo_con_mas_de_tres_compradores(ctx):
    for i in range(3):
        _alert(ctx, f"extra{i}", "ana", ctx.moyza)
    svc.match_property(ctx.db, ctx.prop, NOW, actor=ctx.admin)
    (ana,) = _notifications(ctx, ctx.users["ana"])
    assert ana.title.startswith("5 compradores encajan")
    assert ana.body.endswith("PYTEST-PM Comprador a1, PYTEST-PM Comprador a2, PYTEST-PM Comprador extra0 y 2 más")


def test_si_el_cruce_falla_no_lanza(ctx, monkeypatch):
    def boom(db, prop):
        raise RuntimeError("perfil roto")
    monkeypatch.setattr(svc, "candidate_alerts", boom)
    assert svc.match_property(ctx.db, ctx.prop, NOW, actor=ctx.admin) == []
    assert _matches(ctx) == []


# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------

def test_lecturas_por_propiedad_y_agente(ctx):
    svc.match_property(ctx.db, ctx.prop, NOW, actor=ctx.admin)
    rows = svc.matches_for_property(ctx.db, ctx.prop)
    # Por agente (Ana, Bea, Pepe) y comprador
    assert [m.alert_id for m in rows] == [ctx.alerts[k].id for k in ("a1", "a2", "b_moes", "b_moyza", "pepe")]
    assert svc.matches_count_for_property(ctx.db, ctx.prop) == 5
    assert svc.matches_count_for_property(ctx.db, ctx.prop, agent_id=ctx.agents["bea"].id) == 2
    assert [m.alert_id for m in svc.matches_for_property(ctx.db, ctx.prop, agent_id=ctx.agents["ana"].id)] == \
        [ctx.alerts["a1"].id, ctx.alerts["a2"].id]
    # Ana y Bea avisadas (Pepe no tiene usuario)
    assert svc.notified_agents_count(ctx.db, ctx.prop) == 2

    # Reasignada: la ve el agente que la lleva ahora
    ctx.alerts["a2"].agent_id = ctx.agents["bea"].id
    ctx.db.flush()
    assert svc.matches_count_for_property(ctx.db, ctx.prop, agent_id=ctx.agents["bea"].id) == 3
    assert svc.matches_count_for_property(ctx.db, ctx.prop, agent_id=ctx.agents["ana"].id) == 1


# ---------------------------------------------------------------------------
# Desde la revisión (plan 1)
# ---------------------------------------------------------------------------

def _pending_review(ctx):
    review = PropertyReview(property_id=ctx.prop.id, agent_id=ctx.prop.agent_id, status=RS.PENDING, rounds=0,
                            created_at=NOW, notified_at=NOW)
    ctx.db.add(review)
    ctx.db.flush()
    return review


def test_mark_ok_produce_los_cruces(ctx):
    review = _pending_review(ctx)
    review_svc.mark_ok(ctx.db, review, ctx.users["ana"], now=NOW)
    assert review.status == RS.OK
    assert {m.alert_id for m in _matches(ctx)} == _ids(ctx, "a1", "a2", "b_moes", "b_moyza", "pepe")
    # La captadora dio el OK: no se avisa a sí misma; Bea sí
    assert _notifications(ctx, ctx.users["ana"]) == []
    assert len(_notifications(ctx, ctx.users["bea"])) == 2


def test_mark_ok_si_el_cruce_falla_el_ok_se_guarda(ctx, monkeypatch):
    def boom(db, prop):
        raise RuntimeError("perfil roto")
    monkeypatch.setattr(svc, "candidate_alerts", boom)
    review = _pending_review(ctx)
    review_svc.mark_ok(ctx.db, review, ctx.admin, now=NOW, by_admin=True)
    ctx.db.expire_all()
    assert review_svc.review_for_property(ctx.db, ctx.prop.id).status == RS.OK
    assert _matches(ctx) == []
