"""
Ceder comprador a otro agente (PLAN_CEDER_COMPRADORES.md §5 y §7).

- Unitarios (sin base de datos, alertas de mentira y `now` inyectado):
  ventana para ceder con el reloj de atención (R1, R3 y sin reloj por el
  corte), solo su alerta y abierta; validaciones de `validate_cession`.
- Servicio con base de datos (transacción que se deshace al terminar): `cede`
  deja Pendiente y sin leer, historial `ceded`, marca `ceded_at`, nota
  «Cedida de A a B por A: motivo», aviso al nuevo agente y `alert_ceded` a
  los admins de la empresa; una reasignación posterior quita la marca.
- Rutas contra la app levantada (patrón de test_alert_assignment_routes.py;
  se omite si la app no responde): ceder desde el detalle, destinos solo de
  la empresa, motivo y casilla obligatorios, fuera de plazo, alerta ajena,
  admin; chip «Cedido» y «Cedido por» para el receptor sin el motivo.

    docker exec moyza_backend python -m pytest tests/test_alert_cession.py -q
"""
import base64
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from datetime import timedelta
from itertools import count
from types import SimpleNamespace

import pytest

from app.core import business_calendar as bc
from app.core.constants import AlertStatus
from app.core.constants import FollowUpActionType
from app.services import alert_assignment_service as svc
from app.services.alert_assignment_service import AlertAssignmentError


def L(*args) -> datetime:
    """Hora local de Madrid -> UTC naive."""
    return bc.to_utc(datetime(*args))


_ids = count(1)


def _fu(action_type, when):
    return SimpleNamespace(id=next(_ids), action_type=action_type, created_at=when)


def _alert(assigned, follow_ups=(), status=AlertStatus.IN_PROGRESS, agent_id=1, company_id=1):
    return SimpleNamespace(
        id=next(_ids), status=status, agent_id=agent_id, company_id=company_id,
        company=SimpleNamespace(id=company_id, name="MOYZA"),
        created_at=assigned, assigned_at=assigned, follow_ups=list(follow_ups),
        lead_name="Comprador",
    )


def _agent(id, companies=(1,), name=None):
    return SimpleNamespace(id=id, name=name or f"Agente {id}",
                           companies=[SimpleNamespace(id=c) for c in companies])


# Sin corte: las alertas de mentira tienen reloj aunque sean antiguas
NO_CUTOFF = None


# ---------------------------------------------------------------------------
# Unitarios: ventana para ceder (§7-1)
# ---------------------------------------------------------------------------

def test_ventana_r1_cuenta_horas_habiles_con_fin_de_semana():
    alert = _alert(L(2026, 10, 16, 12, 0))   # viernes 12:00; vence el martes 12:00
    assert svc.can_cede(alert, 1, now=L(2026, 10, 19, 12, 0), since=NO_CUTOFF)     # lunes
    assert svc.can_cede(alert, 1, now=L(2026, 10, 20, 11, 59), since=NO_CUTOFF)
    assert not svc.can_cede(alert, 1, now=L(2026, 10, 20, 12, 0), since=NO_CUTOFF)


def test_ventana_se_reabre_con_un_seguimiento_real():
    # El reloj R1 cuenta desde el último seguimiento real: gestionar el
    # comprador también alarga el plazo para cederlo (es el mismo aviso)
    alert = _alert(L(2026, 10, 19, 9, 0), follow_ups=[_fu(FollowUpActionType.CONTACTADO, L(2026, 10, 21, 8, 0))])
    assert svc.can_cede(alert, 1, now=L(2026, 10, 22, 9, 0), since=NO_CUTOFF)


def test_ventana_r3_vence_a_las_24_horas_del_sin_respuesta():
    alert = _alert(L(2026, 10, 19, 9, 0), follow_ups=[_fu(FollowUpActionType.SIN_RESPUESTA, L(2026, 10, 19, 10, 0))])
    assert svc.can_cede(alert, 1, now=L(2026, 10, 20, 9, 59), since=NO_CUTOFF)
    assert not svc.can_cede(alert, 1, now=L(2026, 10, 20, 10, 0), since=NO_CUTOFF)


def test_sin_reloj_por_el_corte_usa_48_horas_habiles_desde_la_asignacion():
    cutoff = L(2026, 10, 20, 0, 0)
    alert = _alert(L(2026, 10, 15, 12, 0))   # jueves, antes del corte: sin reloj de avisos
    assert svc.can_cede(alert, 1, now=L(2026, 10, 16, 12, 0), since=cutoff)
    # 48 h hábiles: jueves 12:00 -> lunes 12:00 (fin de semana por medio)
    assert svc.can_cede(alert, 1, now=L(2026, 10, 19, 11, 59), since=cutoff)
    assert not svc.can_cede(alert, 1, now=L(2026, 10, 19, 12, 0), since=cutoff)
    # Aunque tenga seguimientos: sin reloj, cuenta solo desde la asignación
    alert.follow_ups = [_fu(FollowUpActionType.CONTACTADO, L(2026, 10, 19, 10, 0))]
    assert not svc.can_cede(alert, 1, now=L(2026, 10, 19, 12, 0), since=cutoff)


def test_solo_su_alerta_y_abierta():
    now = L(2026, 10, 19, 10, 0)
    alert = _alert(L(2026, 10, 19, 9, 0), agent_id=1)
    assert svc.can_cede(alert, 1, now=now, since=NO_CUTOFF)
    assert not svc.can_cede(alert, 2, now=now, since=NO_CUTOFF)
    assert not svc.can_cede(alert, None, now=now, since=NO_CUTOFF)
    for status in (AlertStatus.COMPLETED, AlertStatus.CANCELLED):
        alert.status = status
        assert not svc.can_cede(alert, 1, now=now, since=NO_CUTOFF)
    alert.status = AlertStatus.PENDING
    assert svc.can_cede(alert, 1, now=now, since=NO_CUTOFF)


class TestValidateCession:
    NOW = L(2026, 10, 19, 10, 0)

    def _validate(self, alert=None, to=None, by=None, reason="Zona de Bea", now=None):
        svc.validate_cession(
            alert or _alert(L(2026, 10, 19, 9, 0)),
            to if to is not None else _agent(2),
            by_agent=by if by is not None else _agent(1),
            reason=reason, now=now or self.NOW, since=NO_CUTOFF,
        )

    def test_valida(self):
        self._validate()

    def test_sin_ficha_de_agente(self):
        with pytest.raises(AlertAssignmentError, match="ficha de agente"):
            svc.validate_cession(_alert(L(2026, 10, 19, 9, 0)), _agent(2), by_agent=None,
                                 reason="x", now=self.NOW, since=NO_CUTOFF)

    def test_alerta_ajena(self):
        with pytest.raises(AlertAssignmentError, match="tus propios compradores"):
            self._validate(by=_agent(3))

    def test_alerta_cerrada(self):
        with pytest.raises(AlertAssignmentError, match="alertas abiertas"):
            self._validate(alert=_alert(L(2026, 10, 19, 9, 0), status=AlertStatus.COMPLETED))

    def test_fuera_de_plazo(self):
        with pytest.raises(AlertAssignmentError, match="El plazo para ceder ha vencido"):
            self._validate(now=L(2026, 10, 22, 10, 0))

    def test_sin_destino_o_a_si_mismo(self):
        with pytest.raises(AlertAssignmentError, match="Elige el agente"):
            svc.validate_cession(_alert(L(2026, 10, 19, 9, 0)), None, by_agent=_agent(1),
                                 reason="x", now=self.NOW, since=NO_CUTOFF)
        with pytest.raises(AlertAssignmentError, match="ti mismo"):
            self._validate(to=_agent(1))

    def test_solo_agentes_de_la_empresa_de_la_alerta(self):
        with pytest.raises(AlertAssignmentError, match="agentes de MOYZA"):
            self._validate(to=_agent(2, companies=(2,)))
        self._validate(to=_agent(2, companies=(1, 2)))

    def test_motivo_obligatorio(self):
        for reason in (None, "", "   "):
            with pytest.raises(AlertAssignmentError, match="motivo"):
                self._validate(reason=reason)


def test_nota_de_cesion():
    assert svc.cession_note(_agent(1, name="Ana"), _agent(2, name="Bea"), "Zona") == "Cedida de Ana a Bea por Ana: Zona"


# ---------------------------------------------------------------------------
# Servicio con base de datos
# ---------------------------------------------------------------------------

NOW = datetime(2026, 10, 21, 9, 0)


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
    """Ana (captadora) y Bea en MOYZA, Carla solo en MOES, un admin de MOYZA y otro de MOES."""
    from app.models.agent import Agent
    from app.models.company import Company
    from app.models.property import Property
    from app.models.role import Role
    from app.models.user import User

    moyza = db.query(Company).filter_by(code="MOYZA").one()
    moes = db.query(Company).filter_by(code="MOES").one()
    admin_role = db.query(Role).filter(Role.name.ilike("admin")).first()

    ana = Agent(name="PYTEST-CEDER ANA", email="pytest.ceder.ana@example.com")
    bea = Agent(name="PYTEST-CEDER BEA", email="pytest.ceder.bea@example.com")
    carla = Agent(name="PYTEST-CEDER CARLA", email="pytest.ceder.carla@example.com")
    ana.companies.append(moyza)
    bea.companies.append(moyza)
    carla.companies.append(moes)
    users = {
        name: User(email=f"pytest.ceder.{name}@example.com", full_name=name.title(), hashed_password="x", is_active=True)
        for name in ("ana", "bea", "carla")
    }
    admin = User(email="pytest.ceder.admin@example.com", full_name="Admin", hashed_password="x",
                 is_active=True, role_id=admin_role.id)
    admin.companies.append(moyza)
    admin_moes = User(email="pytest.ceder.adminmoes@example.com", full_name="Admin MOES", hashed_password="x",
                      is_active=True, role_id=admin_role.id)
    admin_moes.companies.append(moes)
    db.add_all([ana, bea, carla, admin, admin_moes, *users.values()])
    db.flush()

    prop = Property(title="PYTEST-CEDER Piso", address="Calle Test 1", city="Jaén",
                    agent_id=ana.id, company_id=moyza.id)
    db.add(prop)
    db.flush()
    return SimpleNamespace(db=db, moyza=moyza, moes=moes, ana=ana, bea=bea, carla=carla,
                           users=users, admin=admin, admin_moes=admin_moes, prop=prop)


def _new_alert(ctx, agent, created_at=NOW):
    from app.models.property_alert import PropertyAlert
    alert = PropertyAlert(property=ctx.prop, lead_name="PYTEST-CEDER Comprador", status=AlertStatus.IN_PROGRESS,
                          created_by=ctx.admin.id, created_at=created_at, read_at=created_at)
    ctx.db.add(alert)
    svc.assign(ctx.db, alert, agent, ctx.admin, None, is_new=True, now=created_at)
    return alert


def _notifications(ctx, user, kind):
    from app.models.notification import Notification
    return ctx.db.query(Notification).filter(Notification.user_id == user.id, Notification.kind == kind).all()


def test_cede_efectos(ctx):
    alert = _new_alert(ctx, ctx.ana)
    later = NOW + timedelta(hours=2)
    svc.validate_cession(alert, ctx.bea, by_agent=ctx.ana, reason="Zona de Bea", now=later)
    result = svc.cede(ctx.db, alert, ctx.bea, ctx.users["ana"], "  Zona de Bea ", now=later)

    assert alert.agent_id == ctx.bea.id and alert.previous_agent_id == ctx.ana.id
    assert alert.status == AlertStatus.PENDING and alert.read_at is None
    assert alert.assigned_at == later and alert.assignment_reason == "Zona de Bea"
    assert alert.is_ceded and alert.ceded_at == later and alert.ceded_by_agent_id == ctx.ana.id
    assert alert.ceded_by_agent.name == "PYTEST-CEDER ANA"

    ctx.db.expire(alert, ["assignment_logs", "follow_ups"])
    assert [(log.kind, log.from_agent_id, log.to_agent_id) for log in alert.assignment_logs] == [
        ("ceded", ctx.ana.id, ctx.bea.id), ("created", None, ctx.ana.id),
    ]
    assert result.log.kind == "ceded" and result.log.reason == "Zona de Bea"
    [note] = alert.follow_ups
    assert note.action_type == FollowUpActionType.REASIGNADA
    assert note.notes == "Cedida de PYTEST-CEDER ANA a PYTEST-CEDER BEA por PYTEST-CEDER ANA: Zona de Bea"

    # Aviso al nuevo agente (sin motivo) y `alert_ceded` a los admins de la empresa
    [assigned] = _notifications(ctx, ctx.users["bea"], "alert_assigned")
    assert assigned.title == "Te han cedido un comprador: PYTEST-CEDER Comprador"
    assert "Zona" not in (assigned.body or "")
    [ceded] = _notifications(ctx, ctx.admin, "alert_ceded")
    assert ceded.title == "PYTEST-CEDER ANA ha cedido el comprador PYTEST-CEDER Comprador a PYTEST-CEDER BEA"
    assert ceded.body == "Motivo: Zona de Bea" and ceded.url == f"/alerts/{alert.id}"
    assert ceded.company_id == ctx.moyza.id
    assert _notifications(ctx, ctx.admin_moes, "alert_ceded") == []
    assert _notifications(ctx, ctx.users["ana"], "alert_ceded") == []


def test_dos_cesiones_seguidas_avisan_las_dos(ctx):
    alert = _new_alert(ctx, ctx.ana)
    svc.cede(ctx.db, alert, ctx.bea, ctx.users["ana"], "Uno", now=NOW + timedelta(hours=1))
    svc.cede(ctx.db, alert, ctx.ana, ctx.users["bea"], "Dos", now=NOW + timedelta(hours=2))
    assert len(_notifications(ctx, ctx.admin, "alert_ceded")) == 2
    assert alert.ceded_by_agent_id == ctx.bea.id


def test_reasignar_despues_quita_la_marca_de_cedido(ctx):
    alert = _new_alert(ctx, ctx.ana)
    svc.cede(ctx.db, alert, ctx.bea, ctx.users["ana"], "Zona", now=NOW + timedelta(hours=1))
    svc.assign(ctx.db, alert, ctx.ana, ctx.admin, None, is_new=False, now=NOW + timedelta(hours=2))
    assert not alert.is_ceded and alert.ceded_by_agent_id is None
    ctx.db.expire(alert, ["assignment_logs"])
    assert [log.kind for log in alert.assignment_logs] == ["reassigned", "ceded", "created"]


def test_agentes_para_ceder_solo_de_la_empresa_sin_el_cedente(ctx):
    agents = svc.cession_agents(ctx.db, ctx.moyza.id, exclude_agent_id=ctx.ana.id)
    ids = {a.id for a in agents}
    assert ctx.bea.id in ids and ctx.ana.id not in ids and ctx.carla.id not in ids
    [group] = svc.assignable_agents_for_cession(ctx.db, ctx.moyza.id, ctx.ana.id)
    assert group["label"] == ctx.moyza.name


# ---------------------------------------------------------------------------
# Rutas (app levantada)
# ---------------------------------------------------------------------------

BASE_URL = os.getenv("MOYZA_TEST_BASE_URL", "http://localhost:8000")
ADMIN_EMAIL = os.getenv("MOYZA_TEST_ADMIN_EMAIL", "admin@moyza.com")
TAG = "PYTEST-CESION"
EMAIL = "pytest.cesion.{}@example.com"


def _server_up() -> bool:
    try:
        urllib.request.urlopen(BASE_URL + "/", timeout=3)
        return True
    except Exception:
        return False


class _Client:
    """Peticiones con cookies de sesión y empresa, sin seguir redirecciones."""

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    def __init__(self, email: str, company: str = "MOYZA"):
        from app.core.security import create_access_token
        token = create_access_token({"sub": email})
        self.cookie = f"access_token={token}; active_company={company}"
        self.opener = urllib.request.build_opener(self._NoRedirect)

    def _request(self, method, path, data=None):
        body = urllib.parse.urlencode(data).encode() if data is not None else None
        req = urllib.request.Request(BASE_URL + path, data=body, method=method)
        req.add_header("Cookie", self.cookie)
        try:
            resp = self.opener.open(req, timeout=20)
            return resp.status, resp.read().decode("utf-8", "replace"), dict(resp.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace"), dict(e.headers)

    def get(self, path):
        return self._request("GET", path)

    def post(self, path, data):
        return self._request("POST", path, data)


def _flash(headers) -> dict:
    match = re.search(r'moyza_flash="?([^";]+)', headers.get("set-cookie", ""))
    if not match:
        return {}
    messages = json.loads(base64.urlsafe_b64decode(match.group(1)).decode("utf-8"))
    return messages[0] if messages else {}


def _session():
    from app.db.session import SessionLocal
    return SessionLocal()


@pytest.fixture(scope="module")
def data():
    if not _server_up():
        pytest.skip(f"La app no responde en {BASE_URL}; tests de integración omitidos")

    from app.models.agent import Agent
    from app.models.company import Company
    from app.models.property import Property
    from app.models.role import Role
    from app.models.user import User

    db = _session()
    _cleanup(db)
    moyza = db.query(Company).filter_by(code="MOYZA").one()
    moes = db.query(Company).filter_by(code="MOES").one()
    role = db.query(Role).filter(Role.name.ilike("agent")).first()

    agents = {}
    for key, companies in (("ana", [moyza]), ("bea", [moyza]), ("dani", [moyza]), ("carla", [moes])):
        ag = Agent(name=f"{TAG} {key.upper()}", email=EMAIL.format(key))
        ag.companies.extend(companies)
        user = User(email=EMAIL.format(key), full_name=f"{TAG} {key}", hashed_password="pytest-sin-login",
                    role_id=role.id if role else None, is_active=True)
        user.companies.extend(companies)
        db.add_all([ag, user])
        agents[key] = ag
    db.flush()

    prop = Property(title=f"{TAG} PISO", address="Calle Test 9", city="Jaen",
                    company_id=moyza.id, agent_id=agents["ana"].id)
    db.add(prop)
    db.commit()

    out = {key: ag.id for key, ag in agents.items()}
    out.update(property_id=prop.id, moyza_id=moyza.id, moes_id=moes.id)
    yield out

    _cleanup(db)
    db.close()


def _cleanup(db):
    from sqlalchemy import or_
    from sqlalchemy import select

    from app.models.agent import Agent
    from app.models.alert_follow_up import AlertFollowUp
    from app.models.buyer import Buyer
    from app.models.notification import Notification
    from app.models.property import Property
    from app.models.property_alert import PropertyAlert
    from app.models.user import User

    db.rollback()
    users = select(User.id).where(User.email.like(EMAIL.format("%")))
    props = select(Property.id).where(Property.title.like(f"{TAG}%"))
    alerts = select(PropertyAlert.id).where(PropertyAlert.property_id.in_(props))
    # Avisos a los usuarios de prueba y los `alert_ceded` de los admins reales
    db.query(Notification).filter(or_(
        Notification.user_id.in_(users),
        Notification.title.like(f"%{TAG}%"),
    )).delete(synchronize_session=False)
    db.query(AlertFollowUp).filter(AlertFollowUp.alert_id.in_(alerts)).delete(synchronize_session=False)
    db.query(PropertyAlert).filter(PropertyAlert.property_id.in_(props)).delete(synchronize_session=False)
    db.query(Buyer).filter(Buyer.name.like(f"{TAG}%")).delete(synchronize_session=False)
    db.query(Property).filter(Property.title.like(f"{TAG}%")).delete(synchronize_session=False)
    db.query(User).filter(User.email.like(EMAIL.format("%"))).delete(synchronize_session=False)
    db.query(Agent).filter(Agent.email.like(EMAIL.format("%"))).delete(synchronize_session=False)
    db.commit()


def _clear_queue(data, *agent_keys):
    from app.models.property_alert import PropertyAlert
    db = _session()
    db.query(PropertyAlert).filter(
        PropertyAlert.agent_id.in_([data[k] for k in agent_keys]),
        PropertyAlert.status.in_(["PENDING", "IN_PROGRESS"]),
    ).update({"status": "COMPLETED"}, synchronize_session=False)
    db.commit()
    db.close()


def _new_alert_for(data, name, agent_key, assigned_ago=None):
    """Alerta creada por el admin para `agent_key`; `assigned_ago` la envejece."""
    from app.models.buyer import Buyer
    admin = _Client(ADMIN_EMAIL)
    status, _, headers = admin.post("/alerts/create", {
        "property_id": data["property_id"], "buyer_name": name, "buyer_phone": "",
        "confirm_new_buyer": "1", "business_type": "Venta", "agent_id": data[agent_key],
    })
    assert status == 302 and _flash(headers).get("category") == "success", _flash(headers)
    db = _session()
    [alert] = db.query(Buyer).filter(Buyer.name == name).one().alerts
    if assigned_ago is not None:
        alert.assigned_at = alert.created_at = datetime.utcnow() - assigned_ago
        db.commit()
    alert_id = alert.id
    db.close()
    return alert_id


def _get_alert(alert_id):
    from app.models.property_alert import PropertyAlert
    db = _session()
    alert = db.get(PropertyAlert, alert_id)
    return db, alert


def _cede(client, alert_id, agent_id, reason="Vive en su zona", confirm="1", next_url=None):
    form = {"agent_id": agent_id, "assignment_reason": reason, "next": next_url or f"/alerts/{alert_id}"}
    if confirm:
        form["confirm_cession"] = confirm
    return client.post(f"/alerts/{alert_id}/cede", form)


def test_ceder_desde_el_detalle(data):
    _clear_queue(data, "ana", "bea")
    alert_id = _new_alert_for(data, f"{TAG} CEDER DETALLE", "ana")
    ana = _Client(EMAIL.format("ana"))
    bea = _Client(EMAIL.format("bea"))

    # El detalle de Ana tiene el botón y el modal con solo agentes de MOYZA, sin ella
    status, body, _ = ana.get(f"/alerts/{alert_id}")
    assert status == 200
    assert 'data-modal-open="cedeModal"' in body and 'id="ceAgentSelect"' in body
    assert "Los compradores cedidos no te generan comisión en caso de venta" in body
    assert "Entiendo que cedo este comprador" in body
    modal = body[body.index('id="ceAgentSelect"'):]
    modal = modal[:modal.index("</select>")]
    assert f'value="{data["bea"]}"' in modal
    assert f'value="{data["carla"]}"' not in modal and f'value="{data["ana"]}"' not in modal

    status, _, headers = _cede(ana, alert_id, data["bea"])
    assert status == 302 and headers.get("location") == "/alerts"
    flash = _flash(headers)
    assert flash.get("category") == "success"
    assert flash.get("message") == f"Has cedido el comprador {TAG} CEDER DETALLE a {TAG} BEA"

    db, alert = _get_alert(alert_id)
    assert alert.agent_id == data["bea"] and alert.status == "PENDING" and alert.read_at is None
    assert alert.is_ceded and alert.ceded_by_agent_id == data["ana"]
    assert alert.assignment_logs[0].kind == "ceded" and alert.assignment_logs[0].reason == "Vive en su zona"
    from app.models.notification import Notification
    titles = [n.title for n in db.query(Notification).filter(Notification.kind == "alert_ceded").all()]
    assert f"{TAG} ANA ha cedido el comprador {TAG} CEDER DETALLE a {TAG} BEA" in titles
    db.close()

    # Ana ya no la ve
    status, _, headers = ana.get(f"/alerts/{alert_id}")
    assert status == 302 and "permisos" in _flash(headers).get("message", "")

    # Bea: chip «Cedido» en el listado y «Cedido por» en el detalle, sin el motivo
    status, body, _ = bea.get("/alerts")
    assert status == 200 and f"{TAG} CEDER DETALLE" in body and "Cedido" in body
    status, body, _ = bea.get(f"/alerts/{alert_id}")
    assert status == 200 and f"Cedido por {TAG} ANA el " in body
    assert "Vive en su zona" not in body

    # Admin: chip en el listado y el motivo en el historial del detalle
    admin = _Client(ADMIN_EMAIL)
    status, body, _ = admin.get("/alerts?q=" + urllib.parse.quote(f"{TAG} CEDER DETALLE"))
    assert status == 200 and "Cedido" in body
    status, body, _ = admin.get(f"/alerts/{alert_id}")
    assert status == 200 and "Vive en su zona" in body and "Cedida de" in body


def test_ceder_desde_el_listado(data):
    _clear_queue(data, "ana", "bea")
    alert_id = _new_alert_for(data, f"{TAG} CEDER LISTADO", "ana")
    ana = _Client(EMAIL.format("ana"))

    status, body, _ = ana.get("/alerts")
    assert status == 200 and "data-cede" in body and 'id="cedeModal"' in body
    assert f'data-alert-id="{alert_id}"' in body

    status, _, headers = _cede(ana, alert_id, data["bea"], next_url="/alerts?page=1")
    assert status == 302 and headers.get("location") == "/alerts?page=1"
    assert _flash(headers).get("category") == "success"


def test_destino_motivo_y_casilla_obligatorios(data):
    _clear_queue(data, "ana")
    alert_id = _new_alert_for(data, f"{TAG} VALIDACIONES", "ana")
    ana = _Client(EMAIL.format("ana"))

    cases = [
        (dict(agent_id=data["carla"]), "Solo puedes ceder el comprador a agentes de"),
        (dict(agent_id=""), "Elige el agente"),
        (dict(agent_id=data["ana"]), "ti mismo"),
        (dict(agent_id=data["bea"], reason="  "), "motivo"),
        (dict(agent_id=data["bea"], confirm=None), "Entiendo que cedo este comprador"),
    ]
    for kwargs, message in cases:
        status, _, headers = _cede(ana, alert_id, **kwargs)
        flash = _flash(headers)
        assert status == 302 and flash.get("category") == "error", kwargs
        assert message in flash.get("message", ""), (kwargs, flash)
        assert headers.get("location") == f"/alerts/{alert_id}"

    db, alert = _get_alert(alert_id)
    assert alert.agent_id == data["ana"] and not alert.is_ceded
    db.close()


def test_fuera_de_plazo_boton_desactivado_y_ruta_rechaza(data):
    _clear_queue(data, "dani")
    alert_id = _new_alert_for(data, f"{TAG} VENCIDA", "dani", assigned_ago=timedelta(days=15))
    dani = _Client(EMAIL.format("dani"))

    status, body, _ = dani.get(f"/alerts/{alert_id}")
    assert status == 200
    assert svc.CESSION_EXPIRED_MESSAGE in body and 'data-modal-open="cedeModal"' not in body
    # En el listado no hay acción de ceder (su única alerta abierta está fuera de plazo)
    status, body, _ = dani.get("/alerts")
    assert status == 200 and f"{TAG} VENCIDA" in body and 'id="cedeModal"' not in body

    status, _, headers = _cede(dani, alert_id, data["bea"])
    assert status == 302 and svc.CESSION_EXPIRED_MESSAGE in _flash(headers).get("message", "")
    db, alert = _get_alert(alert_id)
    assert alert.agent_id == data["dani"]
    db.close()


def test_alerta_ajena_y_admin_no_ceden(data):
    _clear_queue(data, "ana")
    alert_id = _new_alert_for(data, f"{TAG} AJENA", "ana")

    status, _, headers = _cede(_Client(EMAIL.format("dani")), alert_id, data["bea"])
    assert status == 302 and "tus propios compradores" in _flash(headers).get("message", "")
    assert headers.get("location") == "/alerts"

    status, _, headers = _cede(_Client(ADMIN_EMAIL), alert_id, data["bea"])
    assert status == 302 and "Reasignar" in _flash(headers).get("message", "")

    # El admin no ve el botón de ceder en el detalle
    status, body, _ = _Client(ADMIN_EMAIL).get(f"/alerts/{alert_id}")
    assert status == 200 and "cedeModal" not in body and "Ceder comprador" not in body

    db, alert = _get_alert(alert_id)
    assert alert.agent_id == data["ana"]
    db.close()


# ---------------------------------------------------------------------------
# Fase F: historial para el admin y bloque del Inicio
# ---------------------------------------------------------------------------

def test_resumen_y_cesiones_recientes_por_empresa(ctx):
    alert = _new_alert(ctx, ctx.ana)
    svc.cede(ctx.db, alert, ctx.bea, ctx.users["ana"], "Uno", now=NOW + timedelta(hours=1))
    svc.cede(ctx.db, alert, ctx.ana, ctx.users["bea"], "Dos", now=NOW + timedelta(hours=2))
    svc.assign(ctx.db, alert, ctx.bea, ctx.admin, None, is_new=False, now=NOW + timedelta(hours=3))

    start, end = NOW - timedelta(days=1), NOW + timedelta(days=1)
    rows = {r["agent_id"]: (r["ceded"], r["received"])
            for r in svc.cession_summary(ctx.db, ctx.moyza.id, start=start, end=end)}
    assert rows[ctx.ana.id] == (1, 1) and rows[ctx.bea.id] == (1, 1)
    moes_ids = {r["agent_id"] for r in svc.cession_summary(ctx.db, ctx.moes.id, start=start, end=end)}
    assert ctx.ana.id not in moes_ids and ctx.bea.id not in moes_ids

    recent = [log for log in svc.recent_cessions(ctx.db, ctx.moyza.id, since=start, limit=50) if log.alert_id == alert.id]
    assert [log.reason for log in recent] == ["Dos", "Uno"]

    history = svc.with_history_details(svc.history_query(ctx.db, ctx.moyza.id, start=start, end=end)).all()
    kinds = [log.kind for log in history if log.alert_id == alert.id]
    assert kinds == ["reassigned", "ceded", "ceded", "created"]
    only_bea_received = svc.history_query(ctx.db, ctx.moyza.id, start=start, end=end, agent_id=ctx.bea.id,
                                          kind="ceded").all()
    assert {log.reason for log in only_bea_received if log.alert_id == alert.id} == {"Uno", "Dos"}


def test_historial_solo_admin_y_de_la_empresa_activa(data):
    _clear_queue(data, "ana", "bea")
    name = f"{TAG} HISTORIAL"
    alert_id = _new_alert_for(data, name, "ana")
    status, _, headers = _cede(_Client(EMAIL.format("ana")), alert_id, data["bea"], reason="Motivo historial")
    assert status == 302 and _flash(headers).get("category") == "success"

    # Agente: fuera
    status, _, headers = _Client(EMAIL.format("bea")).get("/alerts/assignments")
    assert status == 302 and headers.get("location") == "/alerts"
    assert "Solo un administrador" in _flash(headers).get("message", "")

    admin = _Client(ADMIN_EMAIL)
    status, body, _ = admin.get("/alerts/assignments")
    assert status == 200
    assert "Historial de cesiones" in body and "Cesiones por agente" in body
    assert name in body and "Motivo historial" in body and "Cedida" in body
    assert f"{TAG} ANA" in body and f"{TAG} BEA" in body

    # Filtros: tipo y agente
    status, body, _ = admin.get(f"/alerts/assignments?kind=created&agent_id={data['bea']}")
    assert status == 200 and "Motivo historial" not in body
    status, body, _ = admin.get(f"/alerts/assignments?kind=ceded&agent_id={data['bea']}")
    assert status == 200 and "Motivo historial" in body
    # Rango sin la cesión
    status, body, _ = admin.get("/alerts/assignments?date_from=2020-01-01&date_to=2020-01-31")
    assert status == 200 and name not in body and "No hay asignaciones con estos filtros" in body

    # Con MOES activa no aparecen las de MOYZA
    status, body, _ = _Client(ADMIN_EMAIL, "MOES").get("/alerts/assignments")
    assert status == 200 and name not in body

    # Enlace desde Compradores e Inicio del admin con el bloque de cesiones recientes
    status, body, _ = admin.get("/alerts")
    assert status == 200 and 'href="/alerts/assignments"' in body
    status, body, _ = admin.get("/dashboard")
    assert status == 200 and "Cesiones recientes" in body and name in body
    assert 'href="/alerts/assignments?kind=ceded"' in body
