"""Compradores que requieren atención, en horas hábiles (PLAN_ALERTAS_DIAS_HABILES.md §2.2).

Dos reglas sobre la **ventana de asignación** (`alert_view.assignment_start`)
y solo para alertas abiertas (`PENDING` e `IN_PROGRESS`: abrir la alerta ya
no apaga los avisos, decisión 4):

- **R1 · Sin gestión** (`no_action`): horas hábiles desde el último
  seguimiento real (sin notas del sistema como `REASIGNADA`) registrado desde
  la asignación o, si no hay ninguno, desde la asignación. Cualquier gestión
  real, también «Sin respuesta», reinicia el reloj. Umbral
  `settings.BUYER_REMINDER_HOURS` (48 h hábiles).
- **R2 · Sin avance** (`stage_stall`): solo si el comprador no tiene etapa o
  su etapa actual es Primera llamada (decisión 5). Horas hábiles desde que
  entró en Primera llamada (o desde la asignación si no tiene etapa).
  «Sin respuesta» y «Propiedad asociada» no reinician este reloj. Umbral
  `settings.BUYER_STAGE_STALL_HOURS` (48 h hábiles).

Control de ruido (decisión 4): una alerta da como mucho una fila, la de la
causa más grave (R1 antes que R2).

Todo acepta `now` (UTC naive) inyectable para los tests y el job.
"""
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from datetime import timedelta
from typing import Iterable
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy.orm import selectinload

from app.core import business_calendar as bc
from app.core.config import settings
from app.core.constants import FollowUpActionType
from app.models.property_alert import PropertyAlert
from app.services import alert_view


RULE_NO_ACTION = "no_action"
RULE_STAGE_STALL = "stage_stall"

# Orden de gravedad: la primera que venza es la que se muestra
RULE_PRIORITY = (RULE_NO_ACTION, RULE_STAGE_STALL)

RULE_LABELS = {
    RULE_NO_ACTION: "Sin gestión",
    RULE_STAGE_STALL: "Sin avance de etapa",
}

FIRST_STAGE = FollowUpActionType.PRIMERA_LLAMADA


def first_stage_label() -> str:
    return FollowUpActionType.labels()[FIRST_STAGE]


@dataclass
class BuyerAttention:
    """Reloj de una regla para una alerta. `overdue` si ya pasó `due_at`."""

    alert: PropertyAlert
    rule: str
    since: datetime
    due_at: datetime
    business_hours_elapsed: float
    threshold_hours: int
    stage_label: Optional[str] = None
    now: datetime = field(default_factory=datetime.utcnow)

    @property
    def overdue(self) -> bool:
        return self.now >= self.due_at

    @property
    def elapsed_label(self) -> str:
        """'2 d 5 h' (horas hábiles)."""
        return bc.format_business_duration(self.business_hours_elapsed)

    @property
    def due_label(self) -> str:
        """'martes 20/10 a las 12:00'."""
        return bc.format_due(self.due_at, now=self.now)

    @property
    def text(self) -> str:
        """Frase completa para el Inicio, el email y las notificaciones."""
        if self.rule == RULE_NO_ACTION:
            return f"{self.elapsed_label} hábiles sin gestión"
        return f"{bc.business_days_label(self.business_hours_elapsed)} sin pasar de {self.stage_label}"

    @property
    def badge(self) -> str:
        """Texto corto del badge del listado."""
        if self.rule == RULE_NO_ACTION:
            return f"Sin gestión · {self.elapsed_label} hábiles"
        return f"Sin avance · {self.elapsed_label} hábiles en {self.stage_label}"

    def as_dict(self) -> dict:
        """Forma de `get_pending_buyers_by_agent` (Inicio y email) + campos nuevos."""
        alert = self.alert
        return {
            "alert_id": alert.id,
            "buyer_name": alert.lead_name,
            "buyer_phone": alert.lead_phone or "—",
            "alert_status": alert.status,
            "last_action_at": self.since,
            "hours_elapsed": int(self.business_hours_elapsed),
            "rule": self.rule,
            "due_at": self.due_at,
            "due_label": self.due_label,
            "business_hours_elapsed": self.business_hours_elapsed,
            "elapsed_label": self.elapsed_label,
            "stage_label": self.stage_label,
            "text": self.text,
            "badge": self.badge,
        }


# ---------------------------------------------------------------------------
# Reglas (en Python, sobre los seguimientos ya cargados)
# ---------------------------------------------------------------------------

def _sort_key(follow_up):
    return (follow_up.created_at, follow_up.id or 0)


def is_stage_follow_up(follow_up) -> bool:
    """Seguimiento de etapa: Primera llamada, Contactado, … (no «Sin respuesta» ni notas)."""
    return (
        FollowUpActionType.STAGE_ORDER.get(follow_up.action_type, 0) >= 1
        and follow_up.action_type not in FollowUpActionType.REPEATABLE_ACTIONS
    )


def first_stage_since(window_follow_ups: Iterable) -> tuple[bool, Optional[datetime]]:
    """¿Sigue en la primera etapa? y desde cuándo.

    Devuelve `(aplica, desde)`: `aplica` es False si la etapa actual (último
    seguimiento de etapa) es posterior a Primera llamada. `desde` es el
    momento en que entró en Primera llamada (registrarla otra vez no la
    avanza ni reinicia el reloj) o None si aún no tiene etapa.
    """
    stages = sorted((f for f in window_follow_ups if is_stage_follow_up(f)), key=_sort_key)
    if not stages:
        return True, None
    if stages[-1].action_type != FIRST_STAGE:
        return False, None
    since = stages[-1].created_at
    for follow_up in reversed(stages):
        if follow_up.action_type != FIRST_STAGE:
            break
        since = follow_up.created_at
    return True, since


def alert_clocks(
    alert,
    now: Optional[datetime] = None,
    no_action_hours: Optional[int] = None,
    stall_hours: Optional[int] = None,
) -> list:
    """Relojes que corren para una alerta abierta (vencidos o no), en orden de gravedad.

    R1 siempre; R2 solo mientras siga en la primera etapa. Lista vacía si la
    alerta está cerrada o no tiene agente ni fecha.
    """
    now = now or datetime.utcnow()
    no_action_hours = settings.BUYER_REMINDER_HOURS if no_action_hours is None else no_action_hours
    stall_hours = settings.BUYER_STAGE_STALL_HOURS if stall_hours is None else stall_hours

    start = alert_view.assignment_start(alert)
    if alert.status not in alert_view.OPEN_ALERT_STATUSES or start is None or alert.agent_id is None:
        return []

    window = alert_view.real_follow_ups_since(alert.follow_ups, start)
    clocks = []

    last_action = max((f.created_at for f in window), default=None)
    since = max(start, last_action) if last_action else start
    clocks.append(BuyerAttention(
        alert=alert,
        rule=RULE_NO_ACTION,
        since=since,
        due_at=bc.add_business_hours(since, no_action_hours),
        business_hours_elapsed=bc.business_hours_between(since, now),
        threshold_hours=no_action_hours,
        now=now,
    ))

    applies, stage_since = first_stage_since(window)
    if applies:
        since = max(start, stage_since) if stage_since else start
        clocks.append(BuyerAttention(
            alert=alert,
            rule=RULE_STAGE_STALL,
            since=since,
            due_at=bc.add_business_hours(since, stall_hours),
            business_hours_elapsed=bc.business_hours_between(since, now),
            threshold_hours=stall_hours,
            stage_label=first_stage_label(),
            now=now,
        ))
    return clocks


def evaluate_alert(alert, now: Optional[datetime] = None, **thresholds) -> Optional[BuyerAttention]:
    """La causa más grave ya vencida de la alerta, o None (una sola fila por alerta)."""
    for clock in alert_clocks(alert, now=now, **thresholds):
        if clock.overdue:
            return clock
    return None


def evaluate_alerts(alerts: Iterable, now: Optional[datetime] = None, **thresholds) -> dict:
    """{alert.id: BuyerAttention} de las alertas vencidas (listado de /alerts)."""
    result = {}
    for alert in alerts:
        item = evaluate_alert(alert, now=now, **thresholds)
        if item is not None:
            result[alert.id] = item
    return result


# ---------------------------------------------------------------------------
# Consulta
# ---------------------------------------------------------------------------

def find_buyers_needing_attention(
    db: Session,
    company_id: Optional[int] = None,
    agent_id: Optional[int] = None,
    now: Optional[datetime] = None,
    alert_ids: Optional[Iterable[int]] = None,
    no_action_hours: Optional[int] = None,
    stall_hours: Optional[int] = None,
) -> list:
    """Alertas abiertas con una regla vencida, una fila por alerta, de más a menos antigua.

    Prefiltro en SQL: 48 h hábiles son al menos 48 h de reloj y los dos relojes
    arrancan como pronto en la asignación, así que una alerta asignada hace
    menos del umbral menor no puede haber vencido. Los seguimientos se cargan
    en lote.
    """
    now = now or datetime.utcnow()
    no_action_hours = settings.BUYER_REMINDER_HOURS if no_action_hours is None else no_action_hours
    stall_hours = settings.BUYER_STAGE_STALL_HOURS if stall_hours is None else stall_hours
    min_hours = min(no_action_hours, stall_hours)

    query = (
        db.query(PropertyAlert)
        .options(selectinload(PropertyAlert.follow_ups))
        .filter(
            PropertyAlert.status.in_(alert_view.OPEN_ALERT_STATUSES),
            PropertyAlert.agent_id.isnot(None),
            alert_view.assignment_start_expr() <= now - timedelta(hours=min_hours),
        )
    )
    if company_id is not None:
        query = query.filter(PropertyAlert.company_id == company_id)
    if agent_id is not None:
        query = query.filter(PropertyAlert.agent_id == agent_id)
    if alert_ids is not None:
        query = query.filter(PropertyAlert.id.in_(list(alert_ids)))

    items = [
        item for item in (
            evaluate_alert(alert, now=now, no_action_hours=no_action_hours, stall_hours=stall_hours)
            for alert in query.all()
        )
        if item is not None
    ]
    items.sort(key=lambda item: (-item.business_hours_elapsed, item.alert.id))
    return items


def group_by_agent_and_company(items: Iterable[BuyerAttention]) -> dict:
    """{(agent_id, company_id): [BuyerAttention]} conservando el orden."""
    result: dict = {}
    for item in items:
        result.setdefault((item.alert.agent_id, item.alert.company_id), []).append(item)
    return result
