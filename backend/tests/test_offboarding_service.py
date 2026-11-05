"""
Servicio de baja lógica (PLAN_BAJA_USUARIOS.md §5, §8) contra la BD del
contenedor (`SessionLocal`), con datos propios `PYTEST-BAJA` que se borran al
empezar y al terminar (alertas, seguimientos, historial de asignaciones,
notificaciones, propiedades, usuarios, agentes y sus empresas).

    docker exec moyza_backend python -m pytest tests/test_offboarding_service.py -q
"""
from itertools import count

import pytest

TAG = "PYTEST-BAJA SVC"
EMAIL = "pytest.baja.svc.{}@example.com"
ADMIN_EMAIL = "admin@moyza.com"

_seq = count(1)


def _session():
    from app.db.session import SessionLocal
    return SessionLocal()


def _db_up() -> bool:
    try:
        from sqlalchemy import text
        db = _session()
        db.execute(text("SELECT 1"))
        db.close()
        return True
    except Exception:
        return False


def _cleanup(db):
    from sqlalchemy import delete
    from sqlalchemy import or_
    from sqlalchemy import select

    from app.models.agent import Agent
    from app.models.alert_assignment_log import AlertAssignmentLog
    from app.models.alert_follow_up import AlertFollowUp
    from app.models.company import agent_companies
    from app.models.company import user_companies
    from app.models.notification import Notification
    from app.models.property import Property
    from app.models.property_alert import PropertyAlert
    from app.models.property_price_history import PropertyPriceHistory
    from app.models.property_status_history import PropertyStatusHistory
    from app.models.user import User

    db.rollback()
    users = select(User.id).where(User.email.like(EMAIL.format("%")))
    agents = select(Agent.id).where(Agent.email.like(EMAIL.format("%")))
    props = select(Property.id).where(Property.title.like(f"{TAG}%"))
    alerts = select(PropertyAlert.id).where(or_(
        PropertyAlert.property_id.in_(props),
        PropertyAlert.agent_id.in_(agents),
        PropertyAlert.lead_name.like(f"{TAG}%"),
    ))

    db.query(Notification).filter(or_(
        Notification.user_id.in_(users),
        Notification.body.like(f"{TAG}%"),
        Notification.title.like(f"%{TAG}%"),
    )).delete(synchronize_session=False)
    db.query(AlertFollowUp).filter(or_(
        AlertFollowUp.alert_id.in_(alerts), AlertFollowUp.created_by.in_(users),
    )).delete(synchronize_session=False)
    db.query(AlertAssignmentLog).filter(or_(
        AlertAssignmentLog.alert_id.in_(alerts),
        AlertAssignmentLog.from_agent_id.in_(agents),
        AlertAssignmentLog.to_agent_id.in_(agents),
    )).delete(synchronize_session=False)
    db.query(PropertyAlert).filter(PropertyAlert.id.in_(alerts)).delete(synchronize_session=False)
    db.query(PropertyPriceHistory).filter(
        PropertyPriceHistory.property_id.in_(props)).delete(synchronize_session=False)
    db.query(PropertyStatusHistory).filter(
        PropertyStatusHistory.property_id.in_(props)).delete(synchronize_session=False)
    db.query(Property).filter(Property.title.like(f"{TAG}%")).delete(synchronize_session=False)
    db.execute(delete(agent_companies).where(agent_companies.c.agent_id.in_(agents)))
    db.execute(delete(user_companies).where(user_companies.c.user_id.in_(users)))
    db.query(User).filter(User.email.like(EMAIL.format("%"))).delete(synchronize_session=False)
    db.query(Agent).filter(Agent.email.like(EMAIL.format("%"))).delete(synchronize_session=False)
    db.commit()


@pytest.fixture(scope="module")
def ctx():
    if not _db_up():
        pytest.skip("La BD no responde; tests del servicio de baja omitidos")

    from app.models.company import Company
    from app.models.role import Role
    from app.models.user import User

    db = _session()
    _cleanup(db)
    out = {
        "moyza_id": db.query(Company).filter_by(code="MOYZA").one().id,
        "moes_id": db.query(Company).filter_by(code="MOES").one().id,
        "admin_id": db.query(User).filter_by(email=ADMIN_EMAIL).one().id,
    }
    role = db.query(Role).filter(Role.name.ilike("agent")).first()
    out["role_id"] = role.id if role else None
    db.close()
    yield out

    db = _session()
    _cleanup(db)
    db.close()


@pytest.fixture
def db(ctx):
    session = _session()
    yield session
    session.rollback()
    session.close()


# ---------------------------------------------------------------------------
# Ayudantes de datos
# ---------------------------------------------------------------------------

def _companies(db, ctx, codes):
    from app.models.company import Company
    ids = [ctx["moyza_id"] if c == "MOYZA" else ctx["moes_id"] for c in codes]
    return db.query(Company).filter(Company.id.in_(ids)).all()


def _person(db, ctx, key, codes=("MOYZA",), *, with_user=True, active=True):
    """Ficha de agente (y usuario con el mismo email) en las empresas dadas."""
    from datetime import datetime

    from app.models.agent import Agent
    from app.models.user import User

    key = f"{key}{next(_seq)}"
    companies = _companies(db, ctx, codes)
    agent = Agent(name=f"{TAG} {key.upper()}", email=EMAIL.format(key), is_active=active,
                  deactivated_at=None if active else datetime.utcnow())
    agent.companies.extend(companies)
    db.add(agent)
    user = None
    if with_user:
        user = User(email=EMAIL.format(key), full_name=f"{TAG} {key.upper()}",
                    hashed_password="pytest-sin-login", role_id=ctx["role_id"],
                    is_active=active, deactivated_at=None if active else datetime.utcnow())
        user.companies.extend(companies)
        db.add(user)
    db.commit()
    return user, agent


def _property(db, ctx, agent, status, code="MOYZA"):
    from app.models.property import Property
    prop = Property(title=f"{TAG} PISO {next(_seq)}", address="Calle Test 1", city="Jaen",
                    company_id=ctx["moyza_id"] if code == "MOYZA" else ctx["moes_id"],
                    agent_id=agent.id if agent is not None else None, status=status)
    db.add(prop)
    db.commit()
    return prop


def _alert(db, ctx, agent, status, code="MOYZA", prop=None):
    from app.models.property_alert import PropertyAlert
    alert = PropertyAlert(
        property_id=prop.id if prop is not None else None,
        origin="property" if prop is not None else "search",
        company_id=ctx["moyza_id"] if code == "MOYZA" else ctx["moes_id"],
        agent_id=agent.id, lead_name=f"{TAG} COMPRADOR {next(_seq)}",
        status=status, created_by=ctx["admin_id"], business_type="Venta",
    )
    db.add(alert)
    db.commit()
    return alert


def _admin(db, ctx):
    from app.models.user import User
    return db.get(User, ctx["admin_id"])


# ---------------------------------------------------------------------------
# Bloqueo por propiedades vivas
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status", ["Activa", "Reservada", "Pausada"])
def test_propiedad_viva_bloquea_la_baja(db, ctx, status):
    from app.services import offboarding_service as svc

    user, agent = _person(db, ctx, "viva")
    _property(db, ctx, agent, status)

    summary = svc.summary_for_user(db, user)
    assert summary.blocked is True
    moyza = next(p for p in summary.pending if p.company.id == ctx["moyza_id"])
    assert moyza.live_properties == 1

    with pytest.raises(svc.OffboardingError) as exc:
        svc.deactivate(db, user=user, by_user=_admin(db, ctx), reassign_to={})
    assert "1 propiedad activa en MOYZA" in str(exc.value)
    assert "Reasígnalas desde Propiedades" in str(exc.value)

    db.expire_all()
    assert user.is_active is True and agent.is_active is True


def test_propiedad_vendida_no_bloquea(db, ctx):
    from app.services import offboarding_service as svc

    user, agent = _person(db, ctx, "vendida")
    _property(db, ctx, agent, "Vendida")
    _property(db, ctx, agent, "Retirada")

    summary = svc.summary_for_user(db, user)
    assert summary.blocked is False
    assert all(p.live_properties == 0 for p in summary.pending)
    assert summary.has_history is True   # la vendida es historial

    svc.deactivate(db, user=user, by_user=_admin(db, ctx), reassign_to={})
    db.expire_all()
    assert user.is_active is False and user.deactivated_at is not None
    assert agent.is_active is False and agent.deactivated_at is not None


# ---------------------------------------------------------------------------
# Reasignación de alertas abiertas
# ---------------------------------------------------------------------------

def test_reasigna_alertas_abiertas_con_historial_y_aviso(db, ctx):
    from app.models.alert_assignment_log import AlertAssignmentLog
    from app.models.alert_follow_up import AlertFollowUp
    from app.models.notification import Notification
    from app.models.property_alert import PropertyAlert
    from app.services import offboarding_service as svc

    user, leaving = _person(db, ctx, "saliente")
    target_user, target = _person(db, ctx, "destino")
    prop = _property(db, ctx, None, "Activa")   # sin captador: no bloquea a nadie
    pending = _alert(db, ctx, leaving, "PENDING", prop=prop)
    in_progress = _alert(db, ctx, leaving, "IN_PROGRESS")
    closed = _alert(db, ctx, leaving, "COMPLETED", prop=prop)
    open_ids = {pending.id, in_progress.id}

    summary = svc.summary_for_user(db, user)
    moyza = next(p for p in summary.pending if p.company.id == ctx["moyza_id"])
    assert moyza.open_alerts == 2 and moyza.live_properties == 0
    assert target.id in {a.id for a in moyza.targets}
    assert leaving.id not in {a.id for a in moyza.targets}

    # Claves y valores como llegan del formulario (texto)
    summary = svc.deactivate(db, user=user, by_user=_admin(db, ctx),
                             reassign_to={str(ctx["moyza_id"]): str(target.id)}, reason="Deja la empresa")

    assert [(r.company.id, r.agent.id, r.count) for r in summary.reassigned] == [(ctx["moyza_id"], target.id, 2)]
    message = svc.deactivation_message(summary)
    assert message.startswith(f"{user.full_name} dado de baja.")
    assert f"2 compradores reasignados a {target.name} (MOYZA)" in message

    check = _session()
    for alert_id in open_ids:
        alert = check.get(PropertyAlert, alert_id)
        assert alert.agent_id == target.id and alert.previous_agent_id == leaving.id
        assert alert.status == "PENDING" and alert.assignment_reason == "Deja la empresa"
        logs = check.query(AlertAssignmentLog).filter_by(alert_id=alert_id).all()
        assert [(l.kind, l.from_agent_id, l.to_agent_id, l.assigned_by) for l in logs] == [
            ("reassigned", leaving.id, target.id, ctx["admin_id"])]
        follow_ups = check.query(AlertFollowUp).filter_by(alert_id=alert_id).all()
        assert [f.action_type for f in follow_ups] == ["REASIGNADA"]
        assert "Deja la empresa" in follow_ups[0].notes

    notes = check.query(Notification).filter(
        Notification.user_id == target_user.id, Notification.kind == "alert_assigned").all()
    assert {n.entity_id for n in notes} == open_ids

    # Cerrada: intacta, sin historial ni seguimiento
    kept = check.get(PropertyAlert, closed.id)
    assert kept.agent_id == leaving.id and kept.status == "COMPLETED" and kept.previous_agent_id is None
    assert check.query(AlertAssignmentLog).filter_by(alert_id=closed.id).count() == 0
    assert check.query(AlertFollowUp).filter_by(alert_id=closed.id).count() == 0
    check.close()

    db.expire_all()
    assert user.is_active is False and leaving.is_active is False
    assert user.deactivated_at == leaving.deactivated_at


def test_sin_motivo_usa_baja_de_nombre(db, ctx):
    from app.models.property_alert import PropertyAlert
    from app.services import offboarding_service as svc

    user, leaving = _person(db, ctx, "sinmotivo")
    _, target = _person(db, ctx, "destinosm")
    alert = _alert(db, ctx, leaving, "PENDING")

    svc.deactivate(db, user=user, by_user=_admin(db, ctx), reassign_to={ctx["moyza_id"]: target.id})
    db.expire_all()
    assert db.get(PropertyAlert, alert.id).assignment_reason == f"Baja de {user.full_name}"


# ---------------------------------------------------------------------------
# Destinos no válidos: error y nada cambia
# ---------------------------------------------------------------------------

def _assert_untouched(db, user, agent, alert_ids):
    from app.models.alert_assignment_log import AlertAssignmentLog
    from app.models.property_alert import PropertyAlert
    db.expire_all()
    assert user.is_active is True and user.deactivated_at is None
    assert agent.is_active is True and agent.deactivated_at is None
    for alert_id in alert_ids:
        assert db.get(PropertyAlert, alert_id).agent_id == agent.id
        assert db.query(AlertAssignmentLog).filter_by(alert_id=alert_id).count() == 0


def test_destino_ausente_inactivo_otra_empresa_o_el_propio(db, ctx):
    from app.services import offboarding_service as svc

    user, leaving = _person(db, ctx, "rechazos", codes=("MOYZA", "MOES"))
    _, ok_moyza = _person(db, ctx, "okmoyza")
    _, ok_moes = _person(db, ctx, "okmoes", codes=("MOES",))
    _, inactive = _person(db, ctx, "inactivo", active=False)
    a1 = _alert(db, ctx, leaving, "PENDING")
    a2 = _alert(db, ctx, leaving, "IN_PROGRESS", code="MOES")
    admin = _admin(db, ctx)
    moyza, moes = ctx["moyza_id"], ctx["moes_id"]

    summary = svc.summary_for_user(db, user)
    by_company = {p.company.id: p for p in summary.pending}
    assert by_company[moyza].open_alerts == 1 and by_company[moes].open_alerts == 1
    assert inactive.id not in {a.id for a in by_company[moyza].targets}
    assert ok_moes.id not in {a.id for a in by_company[moyza].targets}

    cases = [
        ({}, "Elige a quién reasignar"),
        ({moyza: ok_moyza.id}, "Elige a quién reasignar sus compradores abiertos de MOES PREMIUM"),
        ({moyza: "", moes: ok_moes.id}, "Elige a quién reasignar sus compradores abiertos de MOYZA"),
        ({moyza: inactive.id, moes: ok_moes.id}, "no es un agente activo de esa empresa"),
        ({moyza: ok_moes.id, moes: ok_moes.id}, "no es un agente activo de esa empresa"),
        ({moyza: leaving.id, moes: ok_moes.id}, "no es un agente activo de esa empresa"),
        ({moyza: 999999999, moes: ok_moes.id}, "no es un agente activo de esa empresa"),
    ]
    for reassign_to, text in cases:
        with pytest.raises(svc.OffboardingError) as exc:
            svc.deactivate(db, user=user, by_user=admin, reassign_to=reassign_to)
        assert text in str(exc.value), (reassign_to, str(exc.value))
        _assert_untouched(db, user, leaving, [a1.id, a2.id])

    # Con los dos destinos correctos sí
    summary = svc.deactivate(db, user=user, by_user=admin, reassign_to={moyza: ok_moyza.id, moes: ok_moes.id})
    assert sorted((r.company.id, r.agent.id) for r in summary.reassigned) == sorted(
        [(moyza, ok_moyza.id), (moes, ok_moes.id)])


def test_no_puede_darse_de_baja_a_si_mismo_ni_dos_veces(db, ctx):
    from app.services import offboarding_service as svc

    user, agent = _person(db, ctx, "propio")
    with pytest.raises(svc.OffboardingError, match="a ti mismo"):
        svc.deactivate(db, user=user, by_user=user, reassign_to={})
    _assert_untouched(db, user, agent, [])

    svc.deactivate(db, user=user, by_user=_admin(db, ctx), reassign_to={})
    with pytest.raises(svc.OffboardingError, match="ya está dado de baja"):
        svc.deactivate(db, user=user, by_user=_admin(db, ctx), reassign_to={})


# ---------------------------------------------------------------------------
# Reactivar
# ---------------------------------------------------------------------------

def test_reactivate_restaura_usuario_y_ficha_sin_devolver_lo_reasignado(db, ctx):
    from app.models.property_alert import PropertyAlert
    from app.services import offboarding_service as svc

    user, agent = _person(db, ctx, "vuelve")
    _, target = _person(db, ctx, "recibe")
    alert = _alert(db, ctx, agent, "PENDING")
    svc.deactivate(db, user=user, by_user=_admin(db, ctx), reassign_to={ctx["moyza_id"]: target.id})

    svc.reactivate(db, user=user)
    db.expire_all()
    assert user.is_active is True and user.deactivated_at is None
    assert agent.is_active is True and agent.deactivated_at is None
    assert {c.id for c in agent.companies} == {ctx["moyza_id"]}
    assert db.get(PropertyAlert, alert.id).agent_id == target.id


def test_ficha_sin_usuario_baja_y_reactivacion(db, ctx):
    from app.services import offboarding_service as svc

    _, agent = _person(db, ctx, "ficha", with_user=False)
    summary = svc.summary_for_agent(db, agent)
    assert summary.user is None and summary.name == agent.name and summary.blocked is False

    svc.deactivate(db, agent=agent, by_user=_admin(db, ctx), reassign_to={})
    db.expire_all()
    assert agent.is_active is False and agent.deactivated_at is not None

    svc.reactivate(db, agent=agent)
    db.expire_all()
    assert agent.is_active is True and agent.deactivated_at is None


def test_ficha_con_usuario_se_gestiona_desde_usuarios(db, ctx):
    from app.services import offboarding_service as svc

    user, agent = _person(db, ctx, "conusuario")
    assert svc.find_user(db, agent).id == user.id
    with pytest.raises(svc.OffboardingError, match="desde Usuarios"):
        svc.deactivate(db, agent=agent, by_user=_admin(db, ctx), reassign_to={})
    with pytest.raises(svc.OffboardingError, match="desde Usuarios"):
        svc.reactivate(db, agent=agent)


# ---------------------------------------------------------------------------
# Historial y JSON del modal
# ---------------------------------------------------------------------------

def test_has_history(db, ctx):
    from app.services import offboarding_service as svc

    user, agent = _person(db, ctx, "limpio")
    assert svc.has_history(db, user=user) is False
    assert svc.has_history(db, agent=agent) is False
    assert svc.history_by_user_id(db, [user]) == {user.id: False}
    assert svc.history_by_agent_id(db, [agent]) == {agent.id: False}

    # Una alerta cerrada a su nombre ya es historial (por la ficha)
    _alert(db, ctx, agent, "COMPLETED")
    assert svc.has_history(db, user=user) is True
    assert svc.has_history(db, agent=agent) is True
    assert svc.history_by_user_id(db, [user]) == {user.id: True}

    # Por el usuario: alerta creada por él
    other_user, other_agent = _person(db, ctx, "creador")
    assert svc.has_history(db, user=other_user) is False
    _alert(db, {**ctx, "admin_id": other_user.id}, agent, "COMPLETED")
    assert svc.has_history(db, user=other_user) is True
    assert svc.has_history(db, agent=other_agent) is False


def test_summary_to_dict(db, ctx):
    from urllib.parse import quote

    from app.services import offboarding_service as svc

    user, agent = _person(db, ctx, "json", codes=("MOYZA", "MOES"))
    _, target = _person(db, ctx, "jsondestino")
    _property(db, ctx, agent, "Activa")
    _alert(db, ctx, agent, "PENDING")

    data = svc.summary_to_dict(svc.summary_for_user(db, user))
    assert data["name"] == user.full_name
    assert data["blocked"] is True and data["has_history"] is True
    by_code = {c["code"]: c for c in data["companies"]}
    assert set(by_code) == {"MOYZA", "MOES"}
    moyza = by_code["MOYZA"]
    assert moyza["id"] == ctx["moyza_id"] and moyza["name"] == "MOYZA"
    assert moyza["live_properties"] == 1 and moyza["open_alerts"] == 1
    assert moyza["properties_url"] == f"/properties?search={quote(agent.name)}"
    target_ids = {t["id"] for t in moyza["targets"]}
    assert target.id in target_ids and agent.id not in target_ids
    assert all(set(t) == {"id", "name"} for t in moyza["targets"])
    assert by_code["MOES"]["live_properties"] == 0 and by_code["MOES"]["open_alerts"] == 0

    # Usuario sin ficha de agente: sin empresas ni enlace
    from app.models.user import User
    lonely = User(email=EMAIL.format(f"sinficha{next(_seq)}"), full_name=f"{TAG} SIN FICHA",
                  hashed_password="x", role_id=ctx["role_id"], is_active=True)
    db.add(lonely)
    db.commit()
    data = svc.summary_to_dict(svc.summary_for_user(db, lonely))
    assert data == {"name": f"{TAG} SIN FICHA", "blocked": False, "has_history": False, "companies": []}
