"""
Asignación de alertas de comprador a un agente (PLAN_ASIGNACION_ALERTAS.md).

- Unitarios (sin base de datos): `resolve_assignee`, `validate_reassignment`,
  `clean_reason` y `FollowUpActionType.REASIGNADA`.
- Servicio con base de datos, dentro de una transacción que se deshace al
  terminar: alta con el captador o con otro agente, reasignación (estado,
  historial, nota, aviso) y alta automática en la empresa (§4-1 B).

    docker exec moyza_backend python -m pytest tests/test_alert_assignment.py -q
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.core.constants import AlertStatus
from app.core.constants import FollowUpActionType
from app.services import alert_assignment_service as svc
from app.services.alert_assignment_service import AlertAssignmentError


NOW = datetime(2026, 10, 13, 9, 0)


# ---------------------------------------------------------------------------
# Unitarios
# ---------------------------------------------------------------------------

def _agent(id, name=None):
    return SimpleNamespace(id=id, name=name or f"Agente {id}")


AGENTS = {1: _agent(1, "Captador"), 2: _agent(2, "Otro"), 3: _agent(3, "MOES")}


def _resolve(requested=None, owner=1, admin=True):
    return svc.resolve_assignee(
        is_admin_user=admin,
        requested_agent_id=requested,
        owner_agent_id=owner,
        lookup_any_agent=AGENTS.get,
    )


class TestResolveAssignee:
    def test_sin_agente_va_al_captador(self):
        assert _resolve(None).id == 1
        assert _resolve("").id == 1

    def test_admin_elige_otro_agente(self):
        assert _resolve("2").id == 2
        assert _resolve(3).id == 3

    def test_admin_agente_inexistente(self):
        with pytest.raises(AlertAssignmentError, match="no existe"):
            _resolve(99)

    def test_admin_propiedad_sin_captador_exige_elegir(self):
        with pytest.raises(AlertAssignmentError, match="elige el agente"):
            _resolve(None, owner=None)
        assert _resolve(2, owner=None).id == 2

    def test_agente_no_puede_elegir(self):
        assert _resolve(None, admin=False).id == 1
        assert _resolve("1", admin=False).id == 1
        with pytest.raises(AlertAssignmentError, match="Solo un administrador"):
            _resolve(2, admin=False)

    def test_agente_propiedad_sin_captador(self):
        with pytest.raises(AlertAssignmentError, match="no tiene agente"):
            _resolve(None, owner=None, admin=False)


class TestValidateReassignment:
    def _alert(self, status=AlertStatus.PENDING, agent_id=1):
        return SimpleNamespace(status=status, agent_id=agent_id)

    def test_solo_admin(self):
        with pytest.raises(AlertAssignmentError, match="Solo un administrador"):
            svc.validate_reassignment(self._alert(), AGENTS[2], is_admin_user=False)

    def test_solo_abiertas(self):
        for status in (AlertStatus.COMPLETED, AlertStatus.CANCELLED):
            with pytest.raises(AlertAssignmentError, match="abiertas"):
                svc.validate_reassignment(self._alert(status), AGENTS[2], is_admin_user=True)
        for status in (AlertStatus.PENDING, AlertStatus.IN_PROGRESS):
            svc.validate_reassignment(self._alert(status), AGENTS[2], is_admin_user=True)

    def test_mismo_agente_o_inexistente(self):
        with pytest.raises(AlertAssignmentError, match="ya está asignada"):
            svc.validate_reassignment(self._alert(), AGENTS[1], is_admin_user=True)
        with pytest.raises(AlertAssignmentError, match="no existe"):
            svc.validate_reassignment(self._alert(), None, is_admin_user=True)


def test_motivo_opcional_y_corto():
    assert svc.clean_reason(None) is None
    assert svc.clean_reason("   ") is None
    assert svc.clean_reason("  Carga   de trabajo ") == "Carga de trabajo"
    assert len(svc.clean_reason("x" * 500)) == svc.REASON_MAX_LENGTH


def test_reasignada_es_nota_del_sistema():
    assert FollowUpActionType.REASIGNADA in FollowUpActionType.SYSTEM_ACTIONS
    # El formulario de seguimiento no la acepta
    assert not FollowUpActionType.is_valid(FollowUpActionType.REASIGNADA)
    assert FollowUpActionType.labels()[FollowUpActionType.REASIGNADA] == "Reasignada"
    assert "amber" not in FollowUpActionType.stage_badge_color("REASIGNADA")


# ---------------------------------------------------------------------------
# Servicio con base de datos
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
    """Propiedad MOYZA de Ana (captadora), Bea en MOYZA, Carla solo en MOES, y un admin."""
    from app.models.agent import Agent
    from app.models.company import Company
    from app.models.property import Property
    from app.models.user import User

    moyza = db.query(Company).filter_by(code="MOYZA").one()
    moes = db.query(Company).filter_by(code="MOES").one()

    ana = Agent(name="PYTEST-ASIG ANA", email="pytest.asig.ana@example.com")
    bea = Agent(name="PYTEST-ASIG BEA", email="pytest.asig.bea@example.com")
    carla = Agent(name="PYTEST-ASIG CARLA", email="pytest.asig.carla@example.com")
    ana.companies.append(moyza)
    bea.companies.append(moyza)
    carla.companies.append(moes)
    users = {
        name: User(email=f"pytest.asig.{name}@example.com", full_name=name.title(), hashed_password="x", is_active=True)
        for name in ("ana", "bea", "carla", "admin")
    }
    db.add_all([ana, bea, carla, *users.values()])
    db.flush()

    prop = Property(title="PYTEST-ASIG Piso", address="Calle Test 1", city="Jaén",
                    agent_id=ana.id, company_id=moyza.id)
    db.add(prop)
    db.flush()
    return SimpleNamespace(db=db, moyza=moyza, moes=moes, ana=ana, bea=bea, carla=carla,
                           users=users, admin=users["admin"], prop=prop)


def _new_alert(ctx, agent, reason=None, created_at=NOW, name="PYTEST-ASIG Comprador"):
    from app.models.property_alert import PropertyAlert
    alert = PropertyAlert(property=ctx.prop, lead_name=name, status=AlertStatus.PENDING,
                          created_by=ctx.admin.id, created_at=created_at)
    ctx.db.add(alert)
    result = svc.assign(ctx.db, alert, agent, ctx.admin, reason, is_new=True, now=created_at)
    return alert, result


def _notifications(ctx, user):
    from app.models.notification import Notification
    return ctx.db.query(Notification).filter(
        Notification.user_id == user.id, Notification.kind == "alert_assigned"
    ).all()


def test_alta_con_el_captador_no_notifica(ctx):
    alert, result = _new_alert(ctx, ctx.ana)
    assert alert.agent_id == ctx.ana.id
    assert alert.assigned_at == NOW and alert.assigned_by == ctx.admin.id
    assert alert.previous_agent_id is None and alert.assignment_reason is None
    assert [(log.from_agent_id, log.to_agent_id) for log in alert.assignment_logs] == [(None, ctx.ana.id)]
    assert result.notifications == [] and _notifications(ctx, ctx.users["ana"]) == []
    assert alert.follow_ups == []


def test_alta_con_otro_agente_notifica_solo_al_nuevo(ctx):
    alert, result = _new_alert(ctx, ctx.bea, reason="  Carga de trabajo ")
    assert alert.agent_id == ctx.bea.id
    assert alert.assignment_reason == "Carga de trabajo"
    assert result.granted_company is None
    notes = _notifications(ctx, ctx.users["bea"])
    assert len(notes) == 1
    assert notes[0].company_id == ctx.moyza.id
    assert notes[0].url == f"/alerts/{alert.id}"
    assert "PYTEST-ASIG Comprador" in notes[0].title
    assert "Carga de trabajo" in notes[0].body
    assert _notifications(ctx, ctx.users["ana"]) == []
    # El alta no escribe nota en los seguimientos
    assert alert.follow_ups == []


def test_reasignar_resetea_estado_y_deja_rastro(ctx):
    from app.models.alert_follow_up import AlertFollowUp

    alert, _ = _new_alert(ctx, ctx.ana)
    alert.status = AlertStatus.IN_PROGRESS
    alert.read_at = NOW
    ctx.db.add(AlertFollowUp(alert_id=alert.id, action_type="PRIMERA_LLAMADA", created_by=ctx.users["ana"].id,
                             created_at=NOW + timedelta(minutes=5)))
    ctx.db.flush()

    later = NOW + timedelta(days=1)
    svc.validate_reassignment(alert, ctx.bea, is_admin_user=True)
    result = svc.assign(ctx.db, alert, ctx.bea, ctx.admin, "Sin respuesta", is_new=False, now=later)
    ctx.db.refresh(alert)

    assert alert.agent_id == ctx.bea.id
    assert alert.previous_agent_id == ctx.ana.id and result.previous_agent.id == ctx.ana.id
    assert alert.status == AlertStatus.PENDING and alert.read_at is None
    assert alert.assigned_at == later
    # Historial: alta + reasignación (la más reciente primero)
    assert [(log.from_agent_id, log.to_agent_id) for log in alert.assignment_logs] == [
        (ctx.ana.id, ctx.bea.id), (None, ctx.ana.id)
    ]
    # Se conservan los seguimientos y se añade la nota del sistema
    types = sorted(f.action_type for f in alert.follow_ups)
    assert types == ["PRIMERA_LLAMADA", "REASIGNADA"]
    note = next(f for f in alert.follow_ups if f.action_type == "REASIGNADA")
    assert note.notes == "Reasignada de PYTEST-ASIG ANA a PYTEST-ASIG BEA por Admin: Sin respuesta"
    # Aviso solo al nuevo
    assert len(_notifications(ctx, ctx.users["bea"])) == 1
    assert _notifications(ctx, ctx.users["ana"]) == []


def test_reasignar_al_captador_tambien_notifica(ctx):
    alert, _ = _new_alert(ctx, ctx.bea)
    svc.assign(ctx.db, alert, ctx.ana, ctx.admin, None, is_new=False, now=NOW + timedelta(hours=1))
    assert len(_notifications(ctx, ctx.users["ana"])) == 1
    note = next(f for f in alert.follow_ups if f.action_type == "REASIGNADA")
    assert note.notes.endswith("por Admin")  # sin motivo, sin ":"


def test_agente_de_otra_empresa_gana_acceso(ctx):
    from app.models.user import User
    from app.web.dependencies.company import get_allowed_companies

    alert, result = _new_alert(ctx, ctx.carla)
    assert result.granted_company.id == ctx.moyza.id
    assert {c.code for c in ctx.carla.companies} == {"MOYZA", "MOES"}
    # El usuario vinculado por email ve ya la empresa (no hace falta user_companies)
    carla_user = ctx.db.query(User).filter_by(email="pytest.asig.carla@example.com").one()
    assert carla_user.companies == []
    assert {c.code for c in get_allowed_companies(carla_user, ctx.db)} == {"MOYZA", "MOES"}
    # La notificación vive en la empresa de la propiedad
    assert [n.company_id for n in _notifications(ctx, ctx.users["carla"])] == [ctx.moyza.id]


def test_lista_de_agentes_agrupada_por_empresa(ctx):
    groups = svc.assignable_agents(ctx.db, ctx.moyza.id)
    by_agent = {a.id: g["label"] for g in groups for a in g["agents"]}
    assert ctx.carla.id in by_agent and ctx.ana.id in by_agent
    # Cada agente una sola vez; primero los grupos con la empresa activa
    assert len(by_agent) == sum(len(g["agents"]) for g in groups)
    assert "MOYZA" in groups[0]["label"]
