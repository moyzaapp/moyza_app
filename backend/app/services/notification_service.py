"""Notificaciones in-app. PLAN_DASHBOARD_INICIO.md §4.

Reglas:
- Solo dentro de la app: este módulo nunca envía emails ni WhatsApp.
- Cada notificación pertenece a un usuario y a una empresa; las consultas
  siempre filtran por las dos (un agente de MOYZA y MOES no ve las de una
  empresa con la otra activa).
- Nunca se notifica al propio actor.
- Deduplicación: misma `kind` + entidad + usuario + empresa, sin leer y de
  las últimas 24 h -> no se repite.
- Los avisos nacen de un evento ya guardado: `safe_notify` confirma en su
  propia transacción y, si falla, lo registra en el log sin romper el flujo.

Catálogo v1 (decisión §6-3). `target_reached` y `period_closed` quedan para
después; el admin no tiene campana en v1. `alert_assigned` llega con
PLAN_ASIGNACION_ALERTAS.md §2.4 (lo emite `alert_assignment_service`).
"""
import logging
from datetime import datetime
from datetime import time
from datetime import timedelta
from typing import Iterable
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.constants import AlertStatus
from app.core.constants import FollowUpActionType
from app.models.agent import Agent
from app.models.alert_follow_up import AlertFollowUp
from app.models.company import Company
from app.models.notification import Notification
from app.models.property_alert import PropertyAlert
from app.models.role import Role
from app.models.user import User

logger = logging.getLogger(__name__)

DEDUPE_HOURS = 24
RETENTION_DAYS = 90


class NotificationKind:
    VISIT_ON_MY_PROPERTY = "visit_on_my_property"
    VISIT_AS_COMPANION = "visit_as_companion"
    VISIT_COMPLETED = "visit_completed"
    VISIT_SHEET_SEND_FAILED = "visit_sheet_send_failed"
    FOLLOW_UP_DUE = "follow_up_due"
    ADMIN_NOTE_ADDED = "admin_note_added"
    ALERT_ASSIGNED = "alert_assigned"
    # Compradores que requieren atención (PLAN_ALERTAS_DIAS_HABILES.md §2.3)
    BUYER_NO_ACTION = "buyer_no_action"
    BUYER_STAGE_STALL = "buyer_stage_stall"

    # Icono (dashboard/components/icons.html) y tono por tipo
    STYLES = {
        VISIT_ON_MY_PROPERTY: ("home", "blue"),
        VISIT_AS_COMPANION: ("users", "blue"),
        VISIT_COMPLETED: ("document", "green"),
        VISIT_SHEET_SEND_FAILED: ("chat", "red"),
        FOLLOW_UP_DUE: ("clock", "amber"),
        ADMIN_NOTE_ADDED: ("chat", "gray"),
        ALERT_ASSIGNED: ("user", "blue"),
        BUYER_NO_ACTION: ("inbox", "amber"),
        BUYER_STAGE_STALL: ("user", "amber"),
    }

    @classmethod
    def style(cls, kind: str) -> tuple:
        return cls.STYLES.get(kind, ("bell", "gray"))


# ---------------------------------------------------------------------------
# Destinatarios
# ---------------------------------------------------------------------------

def users_for_agent(db: Session, agent: Optional[Agent]) -> list:
    """Usuarios activos de una ficha de agente (mismo email, sin distinguir mayúsculas).

    Inverso de `get_agent_from_user`.
    """
    email = (getattr(agent, "email", None) or "").strip().lower()
    if not email:
        return []
    return (
        db.query(User)
        .filter(func.lower(User.email) == email, User.is_active.isnot(False))
        .order_by(User.id)
        .all()
    )


def admins_of_company(db: Session, company_id: int) -> list:
    """Usuarios admin con pertenencia a la empresa (no se usa en v1: el admin no tiene campana)."""
    return (
        db.query(User)
        .join(Role, Role.id == User.role_id)
        .filter(
            func.lower(Role.name) == "admin",
            User.is_active.isnot(False),
            User.companies.any(Company.id == company_id),
        )
        .order_by(User.id)
        .all()
    )


# ---------------------------------------------------------------------------
# Emisión
# ---------------------------------------------------------------------------

def notify(
    db: Session,
    *,
    users: Iterable,
    company_id: int,
    kind: str,
    title: str,
    body: Optional[str] = None,
    url: Optional[str] = None,
    actor=None,
    entity: Optional[tuple] = None,
    now: Optional[datetime] = None,
) -> list:
    """Crea una notificación por usuario (sin confirmar: solo `flush`).

    - Nunca al actor (`actor`: User o None).
    - Sin repetir: si el usuario ya tiene una sin leer de la misma `kind` y
      entidad (o del mismo título si no hay entidad) en las últimas 24 h.
    Devuelve las notificaciones creadas.
    """
    if company_id is None:
        return []
    now = now or datetime.utcnow()
    actor_id = getattr(actor, "id", None)
    entity_type, entity_id = entity if entity else (None, None)
    since = now - timedelta(hours=DEDUPE_HOURS)

    created = []
    seen = set()
    for user in users:
        user_id = getattr(user, "id", None)
        if user_id is None or user_id in seen or user_id == actor_id:
            continue
        seen.add(user_id)

        duplicate = db.query(Notification.id).filter(
            Notification.user_id == user_id,
            Notification.company_id == company_id,
            Notification.kind == kind,
            Notification.read_at.is_(None),
            Notification.created_at >= since,
        )
        if entity_type:
            duplicate = duplicate.filter(
                Notification.entity_type == entity_type,
                Notification.entity_id == entity_id,
            )
        else:
            duplicate = duplicate.filter(Notification.title == title)
        if duplicate.first() is not None:
            continue

        notification = Notification(
            user_id=user_id,
            company_id=company_id,
            kind=kind,
            title=title[:255],
            body=body[:500] if body else None,
            url=url,
            actor_user_id=actor_id,
            entity_type=entity_type,
            entity_id=entity_id,
            created_at=now,
        )
        db.add(notification)
        created.append(notification)

    if created:
        db.flush()
    return created


def safe_notify(db: Session, **kwargs) -> list:
    """`notify` + commit; si algo falla, rollback y log (el evento ya está guardado)."""
    try:
        created = notify(db, **kwargs)
        db.commit()
        return created
    except Exception:
        db.rollback()
        logger.exception("No se pudo crear la notificación %s", kwargs.get("kind"))
        return []


def _visit_place(visit) -> str:
    prop = visit.property
    title = prop.title if prop is not None and prop.title else "Propiedad"
    return f"{title} · visitante: {visit.visitor_name}" if visit.visitor_name else title


def notify_visit_created(db: Session, visit, actor=None) -> list:
    """Alta de visita: al captador si no participó y al acompañante.

    `visit_on_my_property`: el captador no es ni el principal ni el acompañante.
    `visit_as_companion`: hay acompañante.
    """
    try:
        prop = visit.property
        if prop is None:
            return []
        company_id = prop.company_id
        visitor_agent = visit.signing_agent
        visitor_name = visitor_agent.name if visitor_agent is not None else "Otro agente"
        created = []

        owner = prop.agent
        if owner is not None and owner.id not in visit.participating_agent_ids:
            created += notify(
                db,
                users=users_for_agent(db, owner),
                company_id=company_id,
                kind=NotificationKind.VISIT_ON_MY_PROPERTY,
                title=f"{visitor_name} visitó tu inmueble",
                body=_visit_place(visit),
                url=f"/properties/{prop.id}",
                actor=actor,
                entity=("visit", visit.id),
            )

        if visit.companion_agent is not None:
            created += notify(
                db,
                users=users_for_agent(db, visit.companion_agent),
                company_id=company_id,
                kind=NotificationKind.VISIT_AS_COMPANION,
                title=f"{visitor_name} registró una visita contigo como acompañante",
                body=_visit_place(visit),
                url=f"/properties/{prop.id}",
                actor=actor,
                entity=("visit", visit.id),
            )

        db.commit()
        return created
    except Exception:
        db.rollback()
        logger.exception("No se pudieron crear las notificaciones de la visita %s", getattr(visit, "id", None))
        return []


def notify_visit_completed(db: Session, visit, actor=None, sent: bool = True) -> list:
    """Ficha firmada (y enviada si `sent`): al agente principal y al acompañante."""
    try:
        prop = visit.property
        if prop is None:
            return []
        users = users_for_agent(db, visit.signing_agent) + users_for_agent(db, visit.companion_agent)
        created = notify(
            db,
            users=users,
            company_id=prop.company_id,
            kind=NotificationKind.VISIT_COMPLETED,
            title="Ficha de visita firmada y enviada" if sent else "Ficha de visita firmada",
            body=_visit_place(visit),
            url=f"/properties/{prop.id}",
            actor=actor,
            entity=("visit", visit.id),
        )
        db.commit()
        return created
    except Exception:
        db.rollback()
        logger.exception("No se pudo notificar la visita completada %s", getattr(visit, "id", None))
        return []


def notify_visit_sheet_failed(db: Session, visit, actor=None) -> list:
    """WhatsApp de la ficha en ERROR: al agente principal (el admin lo ve en "Requiere atención")."""
    try:
        prop = visit.property
        if prop is None:
            return []
        created = notify(
            db,
            users=users_for_agent(db, visit.signing_agent),
            company_id=prop.company_id,
            kind=NotificationKind.VISIT_SHEET_SEND_FAILED,
            title="No se pudo enviar la ficha de visita por WhatsApp",
            body=_visit_place(visit) + (f" · {visit.phone}" if visit.phone else ""),
            url="/visits",
            actor=actor,
            entity=("visit", visit.id),
        )
        db.commit()
        return created
    except Exception:
        db.rollback()
        logger.exception("No se pudo notificar el envío fallido de la visita %s", getattr(visit, "id", None))
        return []


def notify_admin_note(db: Session, *, agent, company_id: int, period, report=None, actor=None) -> list:
    """Observación del admin guardada en Resultados Comerciales."""
    url = f"/dashboard?period_type={period.period_type}&period_start={period.start_str}"
    return safe_notify(
        db,
        users=users_for_agent(db, agent),
        company_id=company_id,
        kind=NotificationKind.ADMIN_NOTE_ADDED,
        title=f"Nueva observación del administrador · {period.label}",
        body=None,
        url=url,
        actor=actor,
        entity=("performance_report", report.id) if report is not None and report.id else None,
    )


# ---------------------------------------------------------------------------
# Job diario: seguimientos que tocan hoy o vencidos
# ---------------------------------------------------------------------------

def run_follow_up_due(db: Session, now: Optional[datetime] = None) -> int:
    """Una notificación por alerta abierta cuyo último seguimiento tiene la
    próxima acción hoy o vencida. Devuelve cuántas se crearon.

    `next_action_date` guarda la hora local que el agente escribe, así que se
    compara con el final del día de hoy en Madrid.
    """
    from app.services.dashboard_service import madrid_now

    local_now = madrid_now(now)
    end_of_today = datetime.combine(local_now.date(), time(23, 59, 59))
    start_of_today = datetime.combine(local_now.date(), time.min)
    labels = FollowUpActionType.labels()

    latest = (
        db.query(AlertFollowUp.alert_id.label("alert_id"), func.max(AlertFollowUp.id).label("follow_up_id"))
        .filter(AlertFollowUp.action_type.notin_(FollowUpActionType.SYSTEM_ACTIONS))
        .group_by(AlertFollowUp.alert_id)
        .subquery()
    )
    # Empresa de la propia alerta: las búsquedas sin propiedad también avisan
    # (PLAN_ALERTA_SIN_REFERENCIA.md)
    rows = (
        db.query(PropertyAlert, AlertFollowUp, PropertyAlert.company_id)
        .join(latest, latest.c.alert_id == PropertyAlert.id)
        .join(AlertFollowUp, AlertFollowUp.id == latest.c.follow_up_id)
        .filter(
            PropertyAlert.status.in_([AlertStatus.PENDING, AlertStatus.IN_PROGRESS]),
            PropertyAlert.agent_id.isnot(None),
            AlertFollowUp.next_action_date.isnot(None),
            AlertFollowUp.next_action_date <= end_of_today,
        )
        .all()
    )

    created = 0
    for alert, follow_up, company_id in rows:
        overdue = follow_up.next_action_date < start_of_today
        when = follow_up.next_action_date.strftime("%d/%m %H:%M")
        try:
            created += len(notify(
                db,
                users=users_for_agent(db, alert.agent),
                company_id=company_id,
                kind=NotificationKind.FOLLOW_UP_DUE,
                title=f"Seguimiento {'vencido' if overdue else 'para hoy'} · {alert.lead_name or 'Comprador'}",
                body=f"Tras «{labels.get(follow_up.action_type, follow_up.action_type)}» · próxima acción {when}",
                url=f"/alerts/{alert.id}",
                entity=("alert", alert.id),
                now=now,
            ))
        except Exception:
            logger.exception("Error notificando seguimiento de la alerta %s", alert.id)
    db.commit()
    return created


# ---------------------------------------------------------------------------
# Job diario: compradores que requieren atención (horas hábiles)
# ---------------------------------------------------------------------------

def buyer_kind(rule: str) -> str:
    """Tipo de notificación de una regla de `buyer_attention_service`."""
    from app.services.buyer_attention_service import RULE_NO_ACTION
    return NotificationKind.BUYER_NO_ACTION if rule == RULE_NO_ACTION else NotificationKind.BUYER_STAGE_STALL


BUYER_KINDS = (NotificationKind.BUYER_NO_ACTION, NotificationKind.BUYER_STAGE_STALL)


def buyer_reminder_due(last_created_at: Optional[datetime], now: datetime, repeat_business_days: int) -> bool:
    """¿Toca avisar otra vez? Cadencia de la campana (decisión 7).

    `last_created_at`: el último aviso de esa alerta y regla **del vencimiento
    en curso** (creado desde `due_at`), o None si aún no hay ninguno. Se
    avisa al cruzar el umbral y luego cuando han pasado al menos
    `repeat_business_days` días hábiles desde el último aviso.
    """
    from app.core.business_calendar import business_hours_between

    if last_created_at is None:
        return True
    return business_hours_between(last_created_at, now) >= max(repeat_business_days, 1) * 24


def run_buyer_attention(db: Session, items: Iterable, now: Optional[datetime] = None,
                        repeat_business_days: Optional[int] = None) -> int:
    """Una notificación por alerta vencida (`items` de `find_buyers_needing_attention`).

    Deduplicación por alerta + regla + vencimiento (`due_at`): solo cuentan
    los avisos de esa alerta y regla creados desde `due_at` (los de un ciclo
    anterior, antes de una gestión o una reasignación, no). Se avisa al
    cruzar el umbral y otra vez cuando han pasado `repeat_business_days`
    días hábiles desde el último aviso, lo haya leído o no. Al repetir, el
    aviso anterior que siga sin leer se marca leído para que no se acumulen.
    Devuelve cuántas se crearon. Solo in-app: sin email ni WhatsApp.
    """
    from app.core.config import settings

    now = now or datetime.utcnow()
    repeat = settings.BUYER_REMINDER_REPEAT_BUSINESS_DAYS if repeat_business_days is None else repeat_business_days
    created = 0
    for item in items:
        alert = item.alert
        kind = buyer_kind(item.rule)
        try:
            users = []
            for user in users_for_agent(db, alert.agent):
                last = db.query(func.max(Notification.created_at)).filter(
                    Notification.user_id == user.id,
                    Notification.company_id == alert.company_id,
                    Notification.kind == kind,
                    Notification.entity_type == "alert",
                    Notification.entity_id == alert.id,
                    Notification.created_at >= item.due_at,
                ).scalar()
                if buyer_reminder_due(last, now, repeat):
                    users.append(user)
            if not users:
                continue
            # El aviso anterior que siga sin leer queda superado por el nuevo
            db.query(Notification).filter(
                Notification.user_id.in_([u.id for u in users]),
                Notification.company_id == alert.company_id,
                Notification.kind == kind,
                Notification.entity_type == "alert",
                Notification.entity_id == alert.id,
                Notification.read_at.is_(None),
            ).update({Notification.read_at: now}, synchronize_session=False)
            name = alert.lead_name or "Comprador"
            if kind == NotificationKind.BUYER_NO_ACTION:
                title = f"Comprador sin gestión · {name}"
                body = f"{item.text} · venció el {item.due_label}. Registra un seguimiento."
            else:
                title = f"Comprador sin avanzar · {name}"
                body = f"{item.text} · venció el {item.due_label}."
            created += len(notify(
                db,
                users=users,
                company_id=alert.company_id,
                kind=kind,
                title=title,
                body=body,
                url=f"/alerts/{alert.id}",
                entity=("alert", alert.id),
                now=now,
            ))
        except Exception:
            logger.exception("Error notificando comprador sin atender de la alerta %s", alert.id)
    db.commit()
    return created


def resolve_buyer_notifications(db: Session, items: Optional[Iterable] = None, alert_ids=None,
                                now: Optional[datetime] = None) -> int:
    """Marca leídas las notificaciones de compradores que ya no aplican.

    Una notificación de `buyer_no_action` / `buyer_stage_stall` sin leer deja
    de aplicar si la alerta ya no tiene esa regla vencida (se cerró, se
    gestionó, avanzó de etapa, se reasignó o se borró) o si su reloj se
    reinició después de crearla. No se borran: quedan en el historial como
    leídas y dejan de contar en la campana.

    - Con `items` (la pasada completa del job): revisa todas.
    - Con `alert_ids` (tras gestionar una alerta): solo las de esas alertas,
      y recalcula su estado.
    Devuelve cuántas se marcaron.
    """
    from app.services.buyer_attention_service import find_buyers_needing_attention

    now = now or datetime.utcnow()
    query = db.query(Notification).filter(
        Notification.kind.in_(BUYER_KINDS),
        Notification.entity_type == "alert",
        Notification.read_at.is_(None),
    )
    if alert_ids is not None:
        alert_ids = [int(i) for i in alert_ids]
        if not alert_ids:
            return 0
        query = query.filter(Notification.entity_id.in_(alert_ids))
        if items is None:
            items = find_buyers_needing_attention(db, now=now, alert_ids=alert_ids)
    elif items is None:
        items = find_buyers_needing_attention(db, now=now)

    current = {(item.alert.id, buyer_kind(item.rule)): item for item in items}
    recipients = {}
    stale_ids = []
    for notification in query.all():
        item = current.get((notification.entity_id, notification.kind))
        if item is not None and notification.created_at >= item.due_at:
            agent_id = item.alert.agent_id
            if agent_id not in recipients:
                recipients[agent_id] = {u.id for u in users_for_agent(db, item.alert.agent)}
            if notification.user_id in recipients[agent_id]:
                continue
        stale_ids.append(notification.id)

    if stale_ids:
        db.query(Notification).filter(Notification.id.in_(stale_ids)).update(
            {Notification.read_at: now}, synchronize_session=False
        )
    db.commit()
    return len(stale_ids)


def safe_resolve_buyer_notifications(db: Session, alert_id: int, now: Optional[datetime] = None) -> int:
    """`resolve_buyer_notifications` de una alerta tras gestionarla; nunca rompe el flujo."""
    try:
        return resolve_buyer_notifications(db, alert_ids=[alert_id], now=now)
    except Exception:
        db.rollback()
        logger.exception("No se pudieron revisar los avisos de comprador de la alerta %s", alert_id)
        return 0


def cleanup_read(db: Session, now: Optional[datetime] = None, days: int = RETENTION_DAYS) -> int:
    """Borra las notificaciones leídas hace más de `days` días."""
    cutoff = (now or datetime.utcnow()) - timedelta(days=days)
    deleted = (
        db.query(Notification)
        .filter(Notification.read_at.isnot(None), Notification.read_at < cutoff)
        .delete(synchronize_session=False)
    )
    db.commit()
    return deleted


# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------

def _scoped(db: Session, user_id: int, company_id: int):
    return db.query(Notification).filter(
        Notification.user_id == user_id,
        Notification.company_id == company_id,
    )


def unread_count(db: Session, user_id: int, company_id: int) -> int:
    return _scoped(db, user_id, company_id).filter(Notification.read_at.is_(None)).count()


def recent(db: Session, user_id: int, company_id: int, limit: int = 8) -> list:
    """Las últimas `limit`, con las no leídas primero."""
    return (
        _scoped(db, user_id, company_id)
        .order_by(Notification.read_at.isnot(None), Notification.created_at.desc())
        .limit(limit)
        .all()
    )


def page(db: Session, user_id: int, company_id: int, status: str = "all", page_number: int = 1, per_page: int = 25):
    """(notificaciones, total) de una página; `status`: all | unread | read."""
    query = _scoped(db, user_id, company_id)
    if status == "unread":
        query = query.filter(Notification.read_at.is_(None))
    elif status == "read":
        query = query.filter(Notification.read_at.isnot(None))
    total = query.count()
    items = (
        query.order_by(Notification.created_at.desc())
        .offset((max(page_number, 1) - 1) * per_page)
        .limit(per_page)
        .all()
    )
    return items, total


def get_for_user(db: Session, notification_id: int, user_id: int, company_id: int) -> Optional[Notification]:
    return _scoped(db, user_id, company_id).filter(Notification.id == notification_id).first()


def mark_read(db: Session, user_id: int, company_id: int, ids=None, all_: bool = False,
              now: Optional[datetime] = None) -> int:
    """Marca como leídas las indicadas (o todas) del usuario en la empresa. Devuelve cuántas."""
    query = _scoped(db, user_id, company_id).filter(Notification.read_at.is_(None))
    if not all_:
        ids = [int(i) for i in (ids or []) if str(i).isdigit()]
        if not ids:
            return 0
        query = query.filter(Notification.id.in_(ids))
    count = query.update({Notification.read_at: now or datetime.utcnow()}, synchronize_session=False)
    db.commit()
    return count


def serialize(notification: Notification) -> dict:
    icon, tone = NotificationKind.style(notification.kind)
    return {
        "id": notification.id,
        "kind": notification.kind,
        "title": notification.title,
        "body": notification.body,
        "url": f"/notifications/{notification.id}/open",
        "icon": icon,
        "tone": tone,
        "created_at": notification.created_at.isoformat() + "Z" if notification.created_at else None,
        "when": _madrid_label(notification.created_at),
        "read": notification.read_at is not None,
    }


def _madrid_label(value: Optional[datetime]) -> str:
    """UTC naive -> 'dd/mm/aaaa HH:MM' en hora de Madrid."""
    if value is None:
        return ""
    from zoneinfo import ZoneInfo
    local = value.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo("Europe/Madrid"))
    return local.strftime("%d/%m/%Y %H:%M")


def safe_redirect_url(url: Optional[str], default: str = "/notifications") -> str:
    """Solo rutas internas ("/algo", no "//dominio")."""
    if url and url.startswith("/") and not url.startswith("//") and "\\" not in url:
        return url
    return default
