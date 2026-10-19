"""Compradores que requieren atención, en horas hábiles.

PLAN_ALERTAS_DIAS_HABILES.md, ajustado por PLAN_RECORDATORIO_SIN_RESPUESTA.md
§3.1. Dos reglas sobre la **ventana de asignación**
(`alert_view.assignment_start`) y solo para alertas abiertas (`PENDING` e
`IN_PROGRESS`: abrir la alerta no apaga los avisos):

- **R3 · Volver a llamar** (`callback`, tiene prioridad): el último
  seguimiento real de la ventana es «Sin respuesta» y hay como mucho
  `settings.BUYER_CALLBACK_MAX_ATTEMPTS` (3) «Sin respuesta» en la ventana.
  Vence `settings.BUYER_CALLBACK_HOURS` (24) horas hábiles después de ese
  último «Sin respuesta». El tercer intento pide cerrar la alerta como «Sin
  interés». Cualquier seguimiento posterior la resuelve (otro «Sin respuesta»
  abre el intento siguiente).
- **R1 · Sin gestión** (`no_action`, como antes): si R3 no aplica, horas
  hábiles desde el último seguimiento real (sin notas del sistema como
  `REASIGNADA`) registrado desde la asignación o, si no hay ninguno, desde la
  asignación. Umbral `settings.BUYER_REMINDER_HOURS` (48 h hábiles). Cubre las
  alertas nunca gestionadas, las que tienen otra gestión como último
  seguimiento y las que acumulan más de 3 «Sin respuesta» seguidos.

La antigua R2 «sin avance de Primera llamada» ya no existe.

Una alerta cae en una sola regla a la vez: nunca dos avisos distintos por el
mismo comprador. Todo acepta `now` (UTC naive) inyectable para los tests y el job.
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


RULE_CALLBACK = "callback"
RULE_NO_ACTION = "no_action"

RULE_LABELS = {
    RULE_CALLBACK: "Volver a llamar",
    RULE_NO_ACTION: "Sin gestión",
}

_ORDINALS = {1: "Primer", 2: "Segundo", 3: "Tercer", 4: "Cuarto", 5: "Quinto"}


@dataclass
class BuyerAttention:
    """Reloj de la regla que gobierna una alerta. `overdue` si ya pasó `due_at`.

    `attempts` / `max_attempts`: «Sin respuesta» en la ventana y máximo (R3);
    0 en R1.
    """

    alert: PropertyAlert
    rule: str
    since: datetime
    due_at: datetime
    business_hours_elapsed: float
    threshold_hours: int
    attempts: int = 0
    max_attempts: int = 0
    now: datetime = field(default_factory=datetime.utcnow)

    @property
    def overdue(self) -> bool:
        return self.now >= self.due_at

    @property
    def is_callback(self) -> bool:
        return self.rule == RULE_CALLBACK

    @property
    def is_last_attempt(self) -> bool:
        """Tercer «Sin respuesta» (R3): toca cerrar la alerta como «Sin interés»."""
        return self.is_callback and self.attempts >= self.max_attempts

    @property
    def tone(self) -> str:
        """Color del aviso (tokens.md): rojo el último intento, ámbar el resto."""
        return "red" if self.is_last_attempt else "amber"

    @property
    def elapsed_label(self) -> str:
        """'2 d 5 h' (horas hábiles)."""
        return bc.format_business_duration(self.business_hours_elapsed)

    @property
    def due_label(self) -> str:
        """'martes 20/10 a las 12:00'."""
        return bc.format_due(self.due_at, now=self.now)

    @property
    def since_label(self) -> str:
        """Fecha del último «Sin respuesta» (R3) o de la última gestión (R1)."""
        return bc.format_due(self.since, now=self.now)

    @property
    def attempt_label(self) -> str:
        """'intento 2 de 3' (solo R3)."""
        return f"intento {self.attempts} de {self.max_attempts}" if self.is_callback else ""

    @property
    def text(self) -> str:
        """Frase completa para el Inicio, el email y las notificaciones."""
        if self.is_callback:
            if self.is_last_attempt:
                ordinal = _ORDINALS.get(self.attempts, "Último")
                return f"{ordinal} intento sin respuesta · cierra la alerta (Sin interés)"
            return f"Intento {self.attempts} de {self.max_attempts} sin respuesta · vuelve a llamar"
        return f"{self.elapsed_label} hábiles sin gestión"

    @property
    def badge(self) -> str:
        """Texto corto del badge del listado."""
        if self.is_callback:
            return f"Volver a llamar · {self.attempt_label}"
        return f"Sin gestión · {self.elapsed_label} hábiles"

    def as_dict(self) -> dict:
        """Forma de `get_pending_buyers_by_agent` (Inicio y email) + campos de la regla."""
        alert = self.alert
        return {
            "alert_id": alert.id,
            "buyer_name": alert.lead_name,
            "buyer_phone": alert.lead_phone or "—",
            "alert_status": alert.status,
            "last_action_at": self.since,
            "since_label": self.since_label,
            "hours_elapsed": int(self.business_hours_elapsed),
            "rule": self.rule,
            "rule_label": RULE_LABELS[self.rule],
            "due_at": self.due_at,
            "due_label": self.due_label,
            "business_hours_elapsed": self.business_hours_elapsed,
            "elapsed_label": self.elapsed_label,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "attempt_label": self.attempt_label,
            "is_last_attempt": self.is_last_attempt,
            "tone": self.tone,
            "text": self.text,
            "badge": self.badge,
        }


# ---------------------------------------------------------------------------
# Reglas (en Python, sobre los seguimientos ya cargados)
# ---------------------------------------------------------------------------

def _sort_key(follow_up):
    return (follow_up.created_at, follow_up.id or 0)


def callback_state(window_follow_ups: Iterable) -> tuple[int, Optional[object]]:
    """(intentos, último «Sin respuesta») si el último seguimiento real de la ventana es «Sin respuesta».

    `intentos` = «Sin respuesta» registrados en la ventana. `(0, None)` si no
    hay seguimientos o el último es de otro tipo.
    """
    window = sorted(window_follow_ups, key=_sort_key)
    if not window or window[-1].action_type != FollowUpActionType.SIN_RESPUESTA:
        return 0, None
    attempts = sum(1 for f in window if f.action_type == FollowUpActionType.SIN_RESPUESTA)
    return attempts, window[-1]


def _thresholds(no_action_hours=None, callback_hours=None, max_attempts=None) -> tuple[int, int, int]:
    return (
        settings.BUYER_REMINDER_HOURS if no_action_hours is None else no_action_hours,
        settings.BUYER_CALLBACK_HOURS if callback_hours is None else callback_hours,
        settings.BUYER_CALLBACK_MAX_ATTEMPTS if max_attempts is None else max_attempts,
    )


def alert_clock(
    alert,
    now: Optional[datetime] = None,
    no_action_hours: Optional[int] = None,
    callback_hours: Optional[int] = None,
    max_attempts: Optional[int] = None,
) -> Optional[BuyerAttention]:
    """El reloj de la regla que gobierna una alerta abierta (vencido o no).

    R3 si el último seguimiento real es «Sin respuesta» y no se ha pasado del
    máximo de intentos; si no, R1. None si la alerta está cerrada o no tiene
    agente ni fecha.
    """
    now = now or datetime.utcnow()
    no_action_hours, callback_hours, max_attempts = _thresholds(no_action_hours, callback_hours, max_attempts)

    start = alert_view.assignment_start(alert)
    if alert.status not in alert_view.OPEN_ALERT_STATUSES or start is None or alert.agent_id is None:
        return None

    window = alert_view.real_follow_ups_since(alert.follow_ups, start)

    attempts, last_no_answer = callback_state(window)
    if last_no_answer is not None and attempts <= max_attempts:
        since = max(start, last_no_answer.created_at)
        return BuyerAttention(
            alert=alert,
            rule=RULE_CALLBACK,
            since=since,
            due_at=bc.add_business_hours(since, callback_hours),
            business_hours_elapsed=bc.business_hours_between(since, now),
            threshold_hours=callback_hours,
            attempts=attempts,
            max_attempts=max_attempts,
            now=now,
        )

    last_action = max((f.created_at for f in window), default=None)
    since = max(start, last_action) if last_action else start
    return BuyerAttention(
        alert=alert,
        rule=RULE_NO_ACTION,
        since=since,
        due_at=bc.add_business_hours(since, no_action_hours),
        business_hours_elapsed=bc.business_hours_between(since, now),
        threshold_hours=no_action_hours,
        now=now,
    )


def evaluate_alert(alert, now: Optional[datetime] = None, **thresholds) -> Optional[BuyerAttention]:
    """La regla de la alerta si ya venció, o None (una sola regla por alerta)."""
    clock = alert_clock(alert, now=now, **thresholds)
    return clock if clock is not None and clock.overdue else None


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
    callback_hours: Optional[int] = None,
    max_attempts: Optional[int] = None,
) -> list:
    """Alertas abiertas con su regla vencida, una fila por alerta, de más a menos antigua.

    Prefiltro en SQL: N horas hábiles son al menos N horas de reloj y los dos
    relojes arrancan como pronto en la asignación, así que una alerta asignada
    hace menos del umbral menor no puede haber vencido. Los seguimientos se
    cargan en lote.
    """
    now = now or datetime.utcnow()
    thresholds = dict(zip(
        ("no_action_hours", "callback_hours", "max_attempts"),
        _thresholds(no_action_hours, callback_hours, max_attempts),
    ))
    min_hours = min(thresholds["no_action_hours"], thresholds["callback_hours"])

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
        item for item in (evaluate_alert(alert, now=now, **thresholds) for alert in query.all())
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
