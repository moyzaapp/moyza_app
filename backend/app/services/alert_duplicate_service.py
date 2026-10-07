"""Detección de alertas de comprador duplicadas.

Una alerta se considera equivalente a otra cuando apunta al mismo comprador
y a la misma propiedad. Hay dos niveles:

- **Abiertas** (PENDING / IN_PROGRESS): duplicado fuerte. Crear otra mete una
  segunda entrada en la cola del agente por la misma situación.
- **Cerradas recientes** (COMPLETED en los últimos `RECENT_CLOSED_DAYS` días):
  aviso informativo. Repetirla puede tener sentido si el comprador vuelve a
  interesarse.

También se detectan compradores ya registrados con el mismo teléfono o correo,
para evitar dar de alta dos veces a la misma persona desde "Nuevo comprador".
"""
import re
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.constants import AlertStatus, AlertType
from app.models.buyer import Buyer
from app.models.property_alert import PropertyAlert
from app.models.user import User
from app.services.company_scope import scope_alerts, scope_buyers
from app.web.template_env import madrid_dt


OPEN_STATUSES = (AlertStatus.PENDING, AlertStatus.IN_PROGRESS)

# Ventana para considerar "reciente" una alerta ya cerrada
RECENT_CLOSED_DAYS = 30

# Dígitos finales que se comparan entre teléfonos (números españoles: 9)
PHONE_SIGNIFICANT_DIGITS = 9

STATUS_LABELS = {
    AlertStatus.PENDING: "Pendiente",
    AlertStatus.IN_PROGRESS: "En proceso",
    AlertStatus.COMPLETED: "Completada",
    AlertStatus.CANCELLED: "Cancelada",
}

ALERT_TYPE_LABELS = {
    AlertType.LEAD_INTERES: "Lead Interesado",
    AlertType.VISITA_SOLICITADA: "Visita Solicitada",
    AlertType.CAMBIO_PRECIO: "Cambio de Precio",
    AlertType.OTRO: "Otro",
}


# ---------------------------------------------------------------------------
# Normalización de contacto
# ---------------------------------------------------------------------------

def normalize_phone(value: Optional[str]) -> str:
    """Deja solo dígitos. '+34 600-11-22-33' -> '34600112233'."""
    if not value:
        return ""
    return re.sub(r"\D", "", value)


def phone_suffix(value: Optional[str]) -> str:
    """Últimos dígitos significativos del teléfono, o '' si no hay suficientes."""
    digits = normalize_phone(value)
    if len(digits) < PHONE_SIGNIFICANT_DIGITS:
        return ""
    return digits[-PHONE_SIGNIFICANT_DIGITS:]


def phones_match(a: Optional[str], b: Optional[str]) -> bool:
    """True si ambos teléfonos comparten los dígitos significativos."""
    sa, sb = phone_suffix(a), phone_suffix(b)
    return bool(sa) and sa == sb


def normalize_email(value: Optional[str]) -> str:
    return (value or "").strip().lower()


# ---------------------------------------------------------------------------
# Consultas
# ---------------------------------------------------------------------------

def find_duplicate_alerts(
    db: Session,
    company_id: int,
    buyer_id: int,
    property_id: int,
    now: Optional[datetime] = None,
) -> Dict[str, List[PropertyAlert]]:
    """Alertas del mismo comprador y propiedad, en la empresa indicada.

    Devuelve ``{"open": [...], "recent_closed": [...]}`` ordenadas de la más
    reciente a la más antigua.
    """
    now = now or datetime.utcnow()
    since = now - timedelta(days=RECENT_CLOSED_DAYS)

    candidates = (
        scope_alerts(db.query(PropertyAlert), company_id)
        .filter(
            PropertyAlert.buyer_id == buyer_id,
            PropertyAlert.property_id == property_id,
            or_(
                PropertyAlert.status.in_(OPEN_STATUSES),
                PropertyAlert.completed_at >= since,
                PropertyAlert.created_at >= since,
            ),
        )
        .order_by(PropertyAlert.created_at.desc(), PropertyAlert.id.desc())
        .all()
    )

    open_alerts = [a for a in candidates if a.status in OPEN_STATUSES]
    recent_closed = [a for a in candidates if a.status not in OPEN_STATUSES]

    return {"open": open_alerts, "recent_closed": recent_closed}


def find_matching_buyers(
    db: Session,
    company_id: int,
    phone: Optional[str] = None,
    email: Optional[str] = None,
    limit: int = 5,
) -> List[Buyer]:
    """Compradores de la empresa con el mismo teléfono o correo."""
    suffix = phone_suffix(phone)
    mail = normalize_email(email)

    clauses = []
    if suffix:
        digits_only = func.regexp_replace(Buyer.phone, r"\D", "", "g")
        clauses.append(digits_only.like(f"%{suffix}"))
    if mail:
        clauses.append(func.lower(func.trim(Buyer.email)) == mail)

    if not clauses:
        return []

    return (
        scope_buyers(db.query(Buyer), company_id)
        .filter(or_(*clauses))
        .order_by(Buyer.created_at.desc())
        .limit(limit)
        .all()
    )


# ---------------------------------------------------------------------------
# Serialización para la interfaz
# ---------------------------------------------------------------------------

def _user_names(db: Session, user_ids: Iterable[int]) -> Dict[int, str]:
    ids = {uid for uid in user_ids if uid}
    if not ids:
        return {}
    users = db.query(User).filter(User.id.in_(ids)).all()
    return {u.id: u.full_name for u in users}


def serialize_alert(alert: PropertyAlert, user_names: Dict[int, str]) -> dict:
    return {
        "id": alert.id,
        "url": f"/alerts/{alert.id}",
        "status": alert.status,
        "status_label": STATUS_LABELS.get(alert.status, alert.status),
        "alert_type": alert.alert_type,
        "alert_type_label": ALERT_TYPE_LABELS.get(alert.alert_type, alert.alert_type),
        "source": alert.source or "",
        "priority": alert.priority,
        "created_at": madrid_dt(alert.created_at, "%d/%m/%Y"),
        "completed_at": madrid_dt(alert.completed_at, "%d/%m/%Y") if alert.completed_at else "",
        "created_by": user_names.get(alert.created_by, ""),
        "agent": alert.agent.name if alert.agent else "",
        "follow_ups": len(alert.follow_ups or []),
    }


def serialize_duplicates(db: Session, duplicates: Dict[str, List[PropertyAlert]]) -> dict:
    all_alerts = duplicates["open"] + duplicates["recent_closed"]
    names = _user_names(db, (a.created_by for a in all_alerts))
    return {
        "open": [serialize_alert(a, names) for a in duplicates["open"]],
        "recent_closed": [serialize_alert(a, names) for a in duplicates["recent_closed"]],
        "recent_days": RECENT_CLOSED_DAYS,
    }


def serialize_buyer(buyer: Buyer) -> dict:
    return {
        "id": buyer.id,
        "name": buyer.name,
        "phone": buyer.phone or "",
        "email": buyer.email or "",
        "url": f"/buyers/{buyer.id}",
    }


# ---------------------------------------------------------------------------
# Textos
# ---------------------------------------------------------------------------

def duplicate_note(existing: PropertyAlert) -> str:
    """Nota que se añade al mensaje cuando el usuario confirma el duplicado."""
    fecha = madrid_dt(existing.created_at, "%d/%m/%Y")
    return f"Duplicado confirmado de la alerta #{existing.id} ({fecha})."


def new_contact_note(
    source: Optional[str],
    user_name: str,
    notes: Optional[str],
    when: Optional[datetime] = None,
) -> str:
    """Nota que se añade a la alerta existente al registrar un nuevo contacto."""
    when = when or datetime.utcnow()
    stamp = madrid_dt(when, "%d/%m/%Y %H:%M")
    via = f" vía {source.strip()}" if source and source.strip() else ""
    text = f"Nuevo contacto {stamp}{via} (registrado por {user_name})."
    if notes and notes.strip():
        text += f" {notes.strip()}"
    return text


def append_note(message: Optional[str], note: str) -> str:
    base = (message or "").strip()
    return f"{base}\n\n{note}" if base else note
