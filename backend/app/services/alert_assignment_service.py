"""Asignación de alertas de comprador a un agente (PLAN_ASIGNACION_ALERTAS.md).

Reglas (decisiones §4):

- Por defecto la alerta va al captador de la propiedad. Solo el admin puede
  elegir otro agente al crearla (§4-2) y reasignarla después (§4-3), y solo
  mientras está abierta (pendiente o en proceso).
- Se puede elegir cualquier agente de cualquier empresa activa (§4-1, opción
  B). Si no pertenece a la empresa de la propiedad, se le añade a esa empresa
  con `add_to_company`, igual que desde la ficha del agente. Su usuario gana
  acceso porque `get_allowed_companies` suma las empresas de su ficha.
- Propiedad sin captador: se puede crear la alerta si el admin elige agente (§4-7).
- Alerta sin referencia (búsqueda general, PLAN_ALERTA_SIN_REFERENCIA.md): no
  hay captador; el admin elige el agente (obligatorio) y el agente que la crea
  queda asignado a sí mismo (`resolve_search_assignee`).
- Motivo: texto libre corto y opcional (§4-8).
- Reasignar deja la alerta pendiente y sin leer, y conserva los seguimientos
  (§4-9). Se anota en el historial y como nota automática (`REASIGNADA`) en
  los seguimientos.
- Aviso in-app `alert_assigned` solo al nuevo agente (§4-5): en el alta si no
  es el captador y siempre en la reasignación. Nunca email ni WhatsApp. El
  aviso no incluye el motivo ni dice que es una reasignación: para el agente
  la alerta es nueva (PLAN_ALERTA_COMO_NUEVA.md); el rastro solo lo ve el admin.

`resolve_assignee` y `validate_reassignment` son puras (sin base de datos)
para poder probarlas como `visit_agents.resolve_visit_agents`.
"""
import logging
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from typing import Callable
from typing import Optional

from sqlalchemy.orm import Session

from app.core.constants import AlertStatus
from app.core.constants import FollowUpActionType
from app.models.alert_assignment_log import AlertAssignmentLog
from app.models.alert_follow_up import AlertFollowUp
from app.models.company import Company
from app.services.company_scope import add_to_company
from app.services.company_scope import in_company
from app.services.notification_service import NotificationKind
from app.services.notification_service import notify
from app.services.notification_service import users_for_agent
from app.services.visit_agents import companion_agent_groups
from app.services.visit_agents import get_agent_in_any_company

logger = logging.getLogger(__name__)

# Estados en los que una alerta se puede reasignar
REASSIGNABLE_STATUSES = (AlertStatus.PENDING, AlertStatus.IN_PROGRESS)

# Motivo: un input corto; lo que pase de aquí se recorta
REASON_MAX_LENGTH = 200


class AlertAssignmentError(ValueError):
    """Error de validación con mensaje listo para el flash."""


@dataclass
class AssignmentResult:
    agent: object
    previous_agent: Optional[object] = None
    # Empresa a la que se añadió el agente por no pertenecer a la de la propiedad
    granted_company: Optional[Company] = None
    notifications: list = field(default_factory=list)


def _to_int(value):
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def clean_reason(reason) -> Optional[str]:
    text = " ".join(str(reason or "").split())
    return text[:REASON_MAX_LENGTH] or None


# ---------------------------------------------------------------------------
# Lista de agentes y validación
# ---------------------------------------------------------------------------

def assignable_agents(db: Session, company_id: int) -> list[dict]:
    """Agentes elegibles (todas las empresas activas, §4-1 B) agrupados por empresa.

    Mismo formato y orden que el acompañante de visitas:
    [{"label": "MOYZA", "agents": [...]}, {"label": "MOYZA, MOES PREMIUM", ...}, ...].
    """
    return companion_agent_groups(db, company_id)


def resolve_assignee(
    *,
    is_admin_user: bool,
    requested_agent_id,
    owner_agent_id: Optional[int],
    lookup_any_agent: Callable,
):
    """Agente al que va una alerta nueva. Devuelve el Agent.

    - `requested_agent_id`: lo que llega del formulario (vacío = captador).
    - `owner_agent_id`: captador de la propiedad (puede faltar, §4-7).
    - `lookup_any_agent(id)`: el agente si pertenece a alguna empresa activa.

    Un usuario no admin no elige: si manda un agente distinto del captador,
    se rechaza.
    """
    requested = _to_int(requested_agent_id)

    if not is_admin_user:
        if requested is not None and requested != owner_agent_id:
            raise AlertAssignmentError("Solo un administrador puede elegir el agente de la alerta")
        agent_id = owner_agent_id
        if agent_id is None:
            raise AlertAssignmentError("La propiedad no tiene agente asignado")
    else:
        agent_id = requested if requested is not None else owner_agent_id
        if agent_id is None:
            raise AlertAssignmentError(
                "La propiedad no tiene agente asignado: elige el agente de la alerta"
            )

    agent = lookup_any_agent(agent_id)
    if agent is None:
        raise AlertAssignmentError("El agente elegido no existe o no pertenece a ninguna empresa activa")
    return agent


def resolve_search_assignee(
    *,
    is_admin_user: bool,
    requested_agent_id,
    own_agent,
    lookup_any_agent: Callable,
):
    """Agente de una alerta sin referencia (búsqueda general). Devuelve el Agent.

    Sin propiedad no hay captador del que deducirlo: el admin debe elegirlo
    (cualquier agente activo, §4-1 B) y el agente queda asignado a sí mismo.
    Un agente que manda otro `agent_id` recibe un error, como en el alta con
    referencia.
    """
    requested = _to_int(requested_agent_id)

    if not is_admin_user:
        if own_agent is None:
            raise AlertAssignmentError("Tu usuario no tiene ficha de agente asociada")
        if requested is not None and requested != own_agent.id:
            raise AlertAssignmentError("Solo un administrador puede elegir el agente de la alerta")
        return own_agent

    if requested is None:
        raise AlertAssignmentError(
            "Sin propiedad, elige el agente que atenderá al comprador"
        )
    agent = lookup_any_agent(requested)
    if agent is None:
        raise AlertAssignmentError("El agente elegido no existe o no pertenece a ninguna empresa activa")
    return agent


def validate_reassignment(alert, agent, *, is_admin_user: bool) -> None:
    """Comprueba que la reasignación es posible; lanza AlertAssignmentError si no."""
    if not is_admin_user:
        raise AlertAssignmentError("Solo un administrador puede reasignar alertas")
    if alert.status not in REASSIGNABLE_STATUSES:
        raise AlertAssignmentError("Solo se pueden reasignar alertas abiertas (pendientes o en proceso)")
    if agent is None:
        raise AlertAssignmentError("El agente elegido no existe o no pertenece a ninguna empresa activa")
    if agent.id == alert.agent_id:
        raise AlertAssignmentError(f"La alerta ya está asignada a {agent.name}")


def lookup_any_agent(db: Session):
    """`lookup_any_agent` para `resolve_assignee` con la sesión dada."""
    return lambda agent_id: get_agent_in_any_company(db, agent_id)


# ---------------------------------------------------------------------------
# Asignación
# ---------------------------------------------------------------------------

def reassignment_note(previous_agent, agent, by_user, reason: Optional[str]) -> str:
    previous_name = previous_agent.name if previous_agent is not None else "sin agente"
    by_name = getattr(by_user, "full_name", None) or getattr(by_user, "email", None) or "administrador"
    note = f"Reasignada de {previous_name} a {agent.name} por {by_name}"
    return f"{note}: {reason}" if reason else note


def assign(
    db: Session,
    alert,
    agent,
    by_user,
    reason=None,
    *,
    is_new: bool,
    now: Optional[datetime] = None,
) -> AssignmentResult:
    """Asigna `alert` a `agent` (sin confirmar: solo `flush`).

    `is_new`: alta de la alerta (ya añadida a la sesión). Si no, es una
    reasignación ya validada con `validate_reassignment`.
    """
    now = now or datetime.utcnow()
    reason = clean_reason(reason)
    prop = alert.property
    # Empresa de la alerta; una búsqueda general (PLAN_ALERTA_SIN_REFERENCIA.md)
    # no tiene propiedad ni, por tanto, captador
    company_id = alert.company_id if alert.company_id is not None else (
        prop.company_id if prop is not None else None
    )
    owner_agent_id = prop.agent_id if prop is not None else None

    result = AssignmentResult(agent=agent)

    # §4-1 B: acceso a la empresa de la propiedad si no lo tenía
    if company_id is not None and not in_company(agent, company_id):
        add_to_company(db, agent, company_id)
        result.granted_company = db.get(Company, company_id)

    previous_agent = None if is_new else alert.agent
    result.previous_agent = previous_agent

    alert.agent = agent
    alert.assigned_at = now
    alert.assigned_by = getattr(by_user, "id", None)
    alert.assignment_reason = reason

    if not is_new:
        alert.previous_agent = previous_agent
        # Para el nuevo agente es una alerta nueva (§4-9)
        alert.read_at = None
        alert.status = AlertStatus.PENDING

    db.flush()  # alert.id para el historial y la notificación

    db.add(AlertAssignmentLog(
        alert_id=alert.id,
        from_agent_id=previous_agent.id if previous_agent is not None else None,
        to_agent_id=agent.id,
        assigned_by=getattr(by_user, "id", None),
        reason=reason,
        created_at=now,
    ))

    if not is_new:
        db.add(AlertFollowUp(
            alert_id=alert.id,
            action_type=FollowUpActionType.REASIGNADA,
            notes=reassignment_note(previous_agent, agent, by_user, reason),
            created_at=now,
            created_by=by_user.id,
        ))

    if not is_new or agent.id != owner_agent_id:
        result.notifications = _notify_assigned(db, alert, agent, by_user, company_id, now)

    db.flush()
    return result


def alert_subject(alert) -> str:
    """Texto corto de qué trata la alerta: el título de la propiedad o la búsqueda."""
    prop = alert.property
    if prop is not None:
        return prop.title or "Propiedad"
    if alert.business_type:
        return f"Búsqueda general · {alert.business_type}"
    return "Búsqueda general"


def _notify_assigned(db: Session, alert, agent, by_user, company_id, now) -> list:
    """`alert_assigned` al nuevo agente; un fallo no deshace la asignación.

    Cuerpo: solo el título de la propiedad o, en una búsqueda sin propiedad,
    "Búsqueda general · {operación}". El motivo de la asignación no se envía
    al agente (PLAN_ALERTA_COMO_NUEVA.md): se guarda en la alerta y en el
    historial, que solo ve el admin.
    """
    body = alert_subject(alert)
    try:
        with db.begin_nested():
            return notify(
                db,
                users=users_for_agent(db, agent),
                company_id=company_id,
                kind=NotificationKind.ALERT_ASSIGNED,
                title=f"Te han asignado un comprador: {alert.lead_name or 'Comprador'}",
                body=body,
                url=f"/alerts/{alert.id}",
                actor=by_user,
                entity=("alert", alert.id),
                now=now,
            )
    except Exception:
        logger.exception("No se pudo notificar la asignación de la alerta %s", alert.id)
        return []
