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
from app.services import alert_view
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
# Ventana de asignación (PLAN_ALERTA_COMO_NUEVA.md): unitarios sin base de datos
# ---------------------------------------------------------------------------

T0 = datetime(2026, 10, 1, 9, 0)
REASSIGNED_AT = datetime(2026, 10, 10, 11, 30)


def _fu(action, created_at, notes=""):
    return SimpleNamespace(action_type=action, created_at=created_at, notes=notes)


def _alert(created_at=T0, assigned_at=REASSIGNED_AT):
    return SimpleNamespace(created_at=created_at, assigned_at=assigned_at)


def test_assignment_start_cae_a_created_at():
    assert alert_view.assignment_start(_alert()) == REASSIGNED_AT
    assert alert_view.assignment_start(_alert(assigned_at=None)) == T0


def test_display_date_por_rol():
    alert = _alert()
    assert alert_view.display_date(alert, is_admin=True) == T0
    assert alert_view.display_date(alert, is_admin=False) == REASSIGNED_AT
    assert alert_view.display_date(_alert(assigned_at=None), is_admin=False) == T0


def test_visible_follow_ups_agente_solo_desde_la_asignacion_y_sin_notas():
    alert = _alert()
    old = _fu("PRIMERA_LLAMADA", T0 + timedelta(days=1))
    note = _fu(FollowUpActionType.REASIGNADA, REASSIGNED_AT)
    mine = _fu("CONTACTADO", REASSIGNED_AT + timedelta(hours=1))
    undated = _fu("CONTACTADO", None)
    follow_ups = [mine, note, old, undated]

    assert alert_view.visible_follow_ups(follow_ups, alert, is_admin=False) == [mine]
    # El admin lo ve todo, en el mismo orden
    assert alert_view.visible_follow_ups(follow_ups, alert, is_admin=True) == follow_ups


def test_seguimiento_justo_en_la_asignacion_cuenta():
    alert = _alert()
    same_instant = _fu("CONTACTADO", REASSIGNED_AT)
    assert alert_view.visible_follow_ups([same_instant], alert, is_admin=False) == [same_instant]
    assert alert_view.has_follow_up_since_assignment([same_instant], alert)


def test_cerrar_exige_seguimiento_desde_la_asignacion():
    alert = _alert()
    assert not alert_view.has_follow_up_since_assignment(
        [_fu("PRIMERA_LLAMADA", T0 + timedelta(days=1)), _fu(FollowUpActionType.REASIGNADA, REASSIGNED_AT)],
        alert,
    )
    assert alert_view.has_follow_up_since_assignment([_fu("CONTACTADO", REASSIGNED_AT + timedelta(minutes=1))], alert)
    # Alerta nunca reasignada (assigned_at = created_at): cuenta todo lo real
    plain = _alert(assigned_at=T0)
    assert alert_view.has_follow_up_since_assignment([_fu("CONTACTADO", T0 + timedelta(days=1))], plain)


def test_real_follow_ups_since_sin_fecha_es_todo_lo_real():
    follow_ups = [_fu("CONTACTADO", T0), _fu(FollowUpActionType.REASIGNADA, T0), _fu("CALIFICADO", None)]
    assert [f.action_type for f in alert_view.real_follow_ups_since(follow_ups, None)] == ["CONTACTADO", "CALIFICADO"]


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
    # El motivo no va al agente (PLAN_ALERTA_COMO_NUEVA.md): solo la propiedad
    assert notes[0].body == "PYTEST-ASIG Piso"
    assert "Carga de trabajo" not in notes[0].body
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


# ---------------------------------------------------------------------------
# Cola secuencial, recordatorio 48 h y cierre (§2.5)
# ---------------------------------------------------------------------------

def test_cola_ordena_por_asignacion_y_la_nota_no_desbloquea(ctx):
    from app.models.alert_follow_up import AlertFollowUp
    from app.web.routes.alerts import _get_agent_open_alerts_ordered, get_locked_alert_ids

    base = datetime.utcnow() - timedelta(days=10)
    # Y: la más antigua, de Ana; X: de Bea, posterior
    y, _ = _new_alert(ctx, ctx.ana, created_at=base, name="PYTEST-ASIG Y")
    x, _ = _new_alert(ctx, ctx.bea, created_at=base + timedelta(days=1), name="PYTEST-ASIG X")
    # Y se reasigna a Bea después: entra al final de su cola
    svc.assign(ctx.db, y, ctx.bea, ctx.admin, None, is_new=False, now=base + timedelta(days=2))
    ctx.db.flush()

    queue = [a.id for a in _get_agent_open_alerts_ordered(ctx.bea.id, ctx.db, ctx.moyza.id)]
    assert queue == [x.id, y.id]
    assert get_locked_alert_ids(ctx.bea.id, ctx.db, ctx.moyza.id) == {y.id}

    # Un seguimiento real en X desbloquea Y; la nota REASIGNADA de Y no cuenta como gestión
    ctx.db.add(AlertFollowUp(alert_id=x.id, action_type="PRIMERA_LLAMADA", created_by=ctx.users["bea"].id))
    z, _ = _new_alert(ctx, ctx.bea, created_at=base + timedelta(days=3), name="PYTEST-ASIG Z")
    ctx.db.flush()
    assert get_locked_alert_ids(ctx.bea.id, ctx.db, ctx.moyza.id) == {z.id}
    # Ana ya no tiene Y en su cola
    assert y.id not in [a.id for a in _get_agent_open_alerts_ordered(ctx.ana.id, ctx.db, ctx.moyza.id)]


def test_recordatorio_48h_cuenta_desde_la_reasignacion(ctx):
    from app.services.buyer_reminder_service import get_pending_buyers_by_agent

    old = datetime.utcnow() - timedelta(days=10)
    kept, _ = _new_alert(ctx, ctx.ana, created_at=old, name="PYTEST-ASIG SIGUE")
    moved, _ = _new_alert(ctx, ctx.ana, created_at=old, name="PYTEST-ASIG REASIGNADA")
    svc.assign(ctx.db, moved, ctx.bea, ctx.admin, None, is_new=False, now=datetime.utcnow())
    ctx.db.flush()

    pending = get_pending_buyers_by_agent(ctx.db, 48)
    ana_ids = [b["alert_id"] for b in pending.get((ctx.ana.id, ctx.moyza.id), [])]
    bea_ids = [b["alert_id"] for b in pending.get((ctx.bea.id, ctx.moyza.id), [])]
    assert kept.id in ana_ids
    assert moved.id not in ana_ids and moved.id not in bea_ids


def test_nota_de_reasignacion_no_es_seguimiento(ctx):
    """La nota REASIGNADA no es actividad del nuevo agente y no cuenta en el
    aviso de duplicados. La próxima acción del agente anterior no entra en la
    agenda del nuevo (PLAN_ALERTA_COMO_NUEVA.md); la suya sí."""
    from app.models.alert_follow_up import AlertFollowUp
    from app.services.alert_duplicate_service import serialize_alert
    from app.services.dashboard_service import DashboardService

    now = datetime.utcnow()
    alert, _ = _new_alert(ctx, ctx.ana, created_at=now - timedelta(days=2))
    ctx.db.add(AlertFollowUp(alert_id=alert.id, action_type="CONTACTADO", created_by=ctx.users["ana"].id,
                             created_at=now - timedelta(days=1), next_action_date=now - timedelta(hours=30)))
    ctx.db.flush()
    svc.assign(ctx.db, alert, ctx.bea, ctx.admin, None, is_new=False, now=now - timedelta(hours=2))
    ctx.db.flush()
    ctx.db.refresh(alert)

    dashboard = DashboardService(ctx.db, ctx.moyza.id)
    assert dashboard.agenda(ctx.bea, now=now)["due"] == []
    assert dashboard.last_activity_by_agent([ctx.bea.id]).get(ctx.bea.id) is None
    assert serialize_alert(alert, {})["follow_ups"] == 1

    ctx.db.add(AlertFollowUp(alert_id=alert.id, action_type="CALIFICADO", created_by=ctx.users["bea"].id,
                             created_at=now - timedelta(hours=1), next_action_date=now - timedelta(minutes=30)))
    ctx.db.flush()
    due = dashboard.agenda(ctx.bea, now=now)["due"]
    assert [d["alert_id"] for d in due] == [alert.id]


def test_seguimientos_del_anterior_no_desbloquean_la_cola_del_nuevo(ctx):
    """PLAN_ALERTA_COMO_NUEVA.md: la reasignada cuenta como "sin gestionar"
    para el nuevo agente hasta que él registre un seguimiento."""
    from app.models.alert_follow_up import AlertFollowUp
    from app.web.routes.alerts import get_locked_alert_ids

    base = datetime.utcnow() - timedelta(days=10)
    moved, _ = _new_alert(ctx, ctx.ana, created_at=base, name="PYTEST-ASIG MOVIDA")
    ctx.db.add(AlertFollowUp(alert_id=moved.id, action_type="PRIMERA_LLAMADA", created_by=ctx.users["ana"].id,
                             created_at=base + timedelta(hours=1)))
    ctx.db.flush()
    svc.assign(ctx.db, moved, ctx.bea, ctx.admin, None, is_new=False, now=base + timedelta(days=1))
    later, _ = _new_alert(ctx, ctx.bea, created_at=base + timedelta(days=2), name="PYTEST-ASIG POSTERIOR")
    ctx.db.flush()

    assert get_locked_alert_ids(ctx.bea.id, ctx.db, ctx.moyza.id) == {later.id}

    ctx.db.add(AlertFollowUp(alert_id=moved.id, action_type="CONTACTADO", created_by=ctx.users["bea"].id,
                             created_at=base + timedelta(days=3)))
    ctx.db.flush()
    assert get_locked_alert_ids(ctx.bea.id, ctx.db, ctx.moyza.id) == set()
    # El rastro se sigue guardando entero
    ctx.db.refresh(moved)
    assert sorted(f.action_type for f in moved.follow_ups) == ["CONTACTADO", "PRIMERA_LLAMADA", "REASIGNADA"]
    assert alert_view.visible_follow_ups(moved.follow_ups, moved, is_admin=False)[0].action_type == "CONTACTADO"
    assert len(alert_view.visible_follow_ups(moved.follow_ups, moved, is_admin=True)) == 3
