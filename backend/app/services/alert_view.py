"""Qué ve cada rol de una alerta y cómo cuenta para la cola (PLAN_ALERTA_COMO_NUEVA.md).

Concepto central: la **ventana de asignación**. Para una alerta,
`assignment_start = assigned_at or created_at` (las alertas anteriores a la
asignación manual tienen `assigned_at = created_at`). Para el agente, una
alerta reasignada es nueva: todo lo que ve y todo lo que cuenta para él se
calcula desde ese momento.

- El agente solo ve los seguimientos reales (sin notas del sistema como
  `REASIGNADA`) registrados desde `assignment_start`, y la fecha que se le
  muestra es `assignment_start`.
- El admin lo ve todo: todos los seguimientos y la fecha de creación (la de
  asignación aparte).
- La cola secuencial y el cierre (para ambos roles) exigen un seguimiento real
  desde `assignment_start`: una alerta reasignada con seguimientos del agente
  anterior cuenta como "sin gestionar" hasta que el nuevo registre uno.

Nada de esto cambia lo que se guarda en base de datos: el rastro de la
asignación (historial, nota REASIGNADA, agente anterior, motivo) se conserva
íntegro y solo se filtra al mostrarlo.

Comparación de fechas igual en SQL y en Python: un seguimiento cuenta si
`created_at >= assignment_start`; si `created_at` es NULL no cuenta (en SQL la
comparación con NULL es falsa).
"""
from datetime import datetime
from typing import Iterable
from typing import Optional

from sqlalchemy import and_
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.constants import AlertStatus
from app.core.constants import FollowUpActionType
from app.models.alert_follow_up import AlertFollowUp
from app.models.property_alert import PropertyAlert
from app.services.company_scope import scope_alerts


# Estados que se consideran "abiertos" para la cola secuencial del agente
OPEN_ALERT_STATUSES = [AlertStatus.PENDING, AlertStatus.IN_PROGRESS]


# ---------------------------------------------------------------------------
# Ventana de asignación
# ---------------------------------------------------------------------------

def assignment_start(alert) -> Optional[datetime]:
    """Inicio de la ventana del agente actual: `assigned_at`, o `created_at` si falta."""
    return alert.assigned_at or alert.created_at


def assignment_start_expr():
    """`assignment_start` en SQL. Exige que la consulta tenga `PropertyAlert` en el FROM."""
    return func.coalesce(PropertyAlert.assigned_at, PropertyAlert.created_at)


def display_date(alert, is_admin: bool) -> Optional[datetime]:
    """Fecha de la alerta que se muestra: creación para el admin, asignación para el agente."""
    return alert.created_at if is_admin else assignment_start(alert)


# ---------------------------------------------------------------------------
# Seguimientos (SQL)
# ---------------------------------------------------------------------------

def real_follow_ups_clause(since=None):
    """Condición SQL de "seguimiento real": sin notas del sistema y, si se da
    `since`, registrado desde entonces.

    `since` puede ser una fecha o una expresión SQL como `assignment_start_expr()`
    (en ese caso la consulta debe incluir `PropertyAlert`).
    """
    clause = AlertFollowUp.action_type.notin_(FollowUpActionType.SYSTEM_ACTIONS)
    if since is None:
        return clause
    return and_(clause, AlertFollowUp.created_at >= since)


def follow_ups_since_assignment(db: Session, alert):
    """Consulta de los seguimientos reales de `alert` desde su `assignment_start`."""
    return db.query(AlertFollowUp).filter(
        AlertFollowUp.alert_id == alert.id,
        real_follow_ups_clause(assignment_start(alert)),
    )


# ---------------------------------------------------------------------------
# Seguimientos (en Python, sobre una lista ya cargada)
# ---------------------------------------------------------------------------

def is_real_follow_up(follow_up) -> bool:
    """Seguimiento registrado por un agente o admin (no una nota del sistema)."""
    return follow_up.action_type not in FollowUpActionType.SYSTEM_ACTIONS


def real_follow_ups_since(follow_ups: Iterable, since: Optional[datetime]) -> list:
    """Seguimientos reales de la lista registrados desde `since` (None = todos)."""
    return [
        f for f in follow_ups
        if is_real_follow_up(f)
        and (since is None or (f.created_at is not None and f.created_at >= since))
    ]


def visible_follow_ups(follow_ups: Iterable, alert, is_admin: bool) -> list:
    """Seguimientos que ve cada rol, conservando el orden de la lista.

    El admin, todos (incluidas las notas de reasignación y los del agente
    anterior). El agente, solo los reales desde `assignment_start`.
    """
    if is_admin:
        return list(follow_ups)
    return real_follow_ups_since(follow_ups, assignment_start(alert))


def has_follow_up_since_assignment(follow_ups: Iterable, alert) -> bool:
    """True si hay algún seguimiento real desde `assignment_start` (cerrar, cola)."""
    return bool(real_follow_ups_since(follow_ups, assignment_start(alert)))


# ---------------------------------------------------------------------------
# Cola secuencial
# ---------------------------------------------------------------------------

def agent_open_alerts_ordered(agent_id: int, db: Session, company_id: int):
    """Alertas abiertas del agente en la empresa, ordenadas FIFO por fecha de asignación.

    La cola secuencial es por empresa: una alerta pendiente en MOYZA no
    bloquea el trabajo del mismo agente en MOES (y viceversa).
    """
    return (
        scope_alerts(db.query(PropertyAlert), company_id)
        .filter(
            PropertyAlert.agent_id == agent_id,
            PropertyAlert.status.in_(OPEN_ALERT_STATUSES),
        )
        # Una alerta reasignada entra en la cola del nuevo agente por la fecha
        # de asignación (PLAN_ASIGNACION_ALERTAS.md §2.5); las no reasignadas
        # tienen assigned_at = created_at, así que su orden no cambia.
        .order_by(
            assignment_start_expr().asc(),
            PropertyAlert.id.asc(),
        )
        .all()
    )


def get_locked_alert_ids(agent_id: int, db: Session, company_id: int) -> set:
    """IDs de las alertas bloqueadas para un agente en la empresa.

    Una alerta de la cola está bloqueada si alguna anterior aún no tiene un
    seguimiento real registrado **desde su asignación**: los seguimientos del
    agente anterior de una alerta reasignada no cuentan, así que esa alerta
    bloquea las siguientes hasta que el nuevo agente registre uno.

    Dos consultas: la cola y, agrupada, qué alertas de la cola ya se iniciaron.
    """
    open_alerts = agent_open_alerts_ordered(agent_id, db, company_id)
    if not open_alerts:
        return set()

    started_ids = {
        row[0]
        for row in db.query(AlertFollowUp.alert_id)
        .join(PropertyAlert, PropertyAlert.id == AlertFollowUp.alert_id)
        .filter(
            AlertFollowUp.alert_id.in_([a.id for a in open_alerts]),
            real_follow_ups_clause(assignment_start_expr()),
        )
        .distinct()
    }

    locked = set()
    all_preceding_started = True
    for alert in open_alerts:
        if not all_preceding_started:
            locked.add(alert.id)
        elif alert.id not in started_ids:
            all_preceding_started = False
    return locked
