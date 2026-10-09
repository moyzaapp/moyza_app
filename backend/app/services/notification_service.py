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

Catálogo v1 (decisión §6-3). `target_reached`, `period_closed` y
`alert_assigned` quedan para después; el admin no tiene campana en v1.
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
from app.models.property import Property
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

    # Icono (dashboard/components/icons.html) y tono por tipo
    STYLES = {
        VISIT_ON_MY_PROPERTY: ("home", "blue"),
        VISIT_AS_COMPANION: ("users", "blue"),
        VISIT_COMPLETED: ("document", "green"),
        VISIT_SHEET_SEND_FAILED: ("chat", "red"),
        FOLLOW_UP_DUE: ("clock", "amber"),
        ADMIN_NOTE_ADDED: ("chat", "gray"),
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
        .group_by(AlertFollowUp.alert_id)
        .subquery()
    )
    rows = (
        db.query(PropertyAlert, AlertFollowUp, Property.company_id)
        .join(latest, latest.c.alert_id == PropertyAlert.id)
        .join(AlertFollowUp, AlertFollowUp.id == latest.c.follow_up_id)
        .join(Property, Property.id == PropertyAlert.property_id)
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
