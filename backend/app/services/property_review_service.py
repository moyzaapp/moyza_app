"""Revisión obligatoria de las propiedades nuevas por el captador.

PLAN_REVISION_PROPIEDADES_NUEVAS.md §4.2. Cuando entra una propiedad nueva (la
carga la ETL del CRM directamente en `properties` o la crea el admin), su
captador tiene que leer la ficha y decir si está correcta. Si no lo está, lo
dice con un comentario, el admin la corrige y el captador vuelve a dar el OK.

- Detección (P1): `properties` no tiene `created_at` ni hook de inserción, así
  que «nueva» = sin fila en `property_reviews`. La migración dejó `skipped`
  todo lo que existía al desplegar. `register_new_properties` lo recoge cada
  `PROPERTY_REVIEW_POLL_MINUTES` (job) y al momento en el alta del admin.
- P7: si la propiedad trae `market_entry_date` (fecha de alta del CRM) y es
  de hace más de `PROPERTY_REVIEW_MAX_AGE_DAYS` (15) días, es una carga
  histórica: `skipped` sin avisar. Sin fecha se trata como nueva. Es también
  la fecha que se enseña («En el mercado desde …»; sin ella, «Detectada el …»
  con `created_at` de la revisión).
- Solo piden revisión las activas con captador (P3); las que entran no
  activas quedan `skipped` y las activas sin captador esperan a tenerlo. Las
  listas, contadores y el recordatorio solo cuentan las que siguen activas:
  una propiedad que se vende o archiva antes de revisarla deja de pedirlo.
- El captador es siempre el actual de la propiedad (`Property.agent_id`);
  `review.agent_id` guarda a quién se le pidió.
- Transiciones (tabla de §4.1) en `mark_ok`, `flag_issues` y `mark_fixed`:
  lanzan `ValueError` con el motivo si no proceden y confirman. Quién puede
  qué lo decide `can_review` (las rutas lo comprueban antes).
- Avisos solo in-app (campana y Novedades), tono violet (P6): uno al registrar
  (`notify_pending`), uno al corregir el admin y un único recordatorio a las
  48 h hábiles (`remind_overdue`, P5). Al resolverse, los avisos sin leer de
  esa revisión se marcan leídos para que no se queden en la campana.
- Al dar el OK se buscan los compradores compatibles
  (PLAN_COMPRADORES_COMPATIBLES_PROPIEDAD_NUEVA.md, `property_match_service`):
  import protegido y en un `try`, el OK nunca falla por eso.
"""
import logging
from datetime import datetime
from datetime import timedelta
from typing import Iterable
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm import joinedload

from app.core.business_calendar import business_hours_between
from app.core.config import settings
from app.core.constants import PropertyReviewStatus as S
from app.core.constants import PropertyStatus
from app.models.notification import Notification
from app.models.property import Property
from app.models.property_review import PropertyReview
from app.services.company_scope import company_match
from app.services.notification_service import NotificationKind
from app.services.notification_service import notify
from app.services.notification_service import users_for_agent
from app.services.property_link import _place
from app.services.property_link import _price

logger = logging.getLogger(__name__)

COMMENT_MAX = 1000
ENTITY = "property_review"
REVIEW_KINDS = (NotificationKind.PROPERTY_REVIEW_PENDING, NotificationKind.PROPERTY_REVIEW_FIXED)


# ---------------------------------------------------------------------------
# Textos
# ---------------------------------------------------------------------------

def property_summary(prop) -> str:
    """«Piso en Centro, Jaén · 120.000 €» (sin dirección ni propietario)."""
    kind = (getattr(prop, "property_type", None) or "").strip()
    place = _place(prop)
    if kind and place:
        what = f"{kind} en {place}"
    elif place:
        what = f"Inmueble en {place}"
    else:
        what = kind
    return " · ".join(part for part in (what, _price(getattr(prop, "price", None))) if part)


def review_url(prop_or_id) -> str:
    prop_id = getattr(prop_or_id, "id", prop_or_id)
    return f"/properties/{prop_id}#revision"


def _title(prop) -> str:
    return (getattr(prop, "title", None) or "Propiedad").strip()


# ---------------------------------------------------------------------------
# Registro y avisos (job + alta del admin)
# ---------------------------------------------------------------------------

def register_new_properties(db: Session, now: Optional[datetime] = None) -> list:
    """Crea la fila de las propiedades que aún no tienen (P1, P3).

    - Activa con captador -> `pending`.
    - No activa -> `skipped` (no pide revisión).
    - `market_entry_date` de hace más de `PROPERTY_REVIEW_MAX_AGE_DAYS` días
      -> `skipped` sin avisar (P7: carga histórica del CRM). Sin fecha, nueva.
    - Activa sin captador -> nada: se recoge en una pasada posterior cuando lo tenga.
    Idempotente: la fila es única por propiedad. Si otra pasada simultánea
    (job y alta del admin) ya las registró, se deshace y devuelve [].
    """
    now = now or datetime.utcnow()
    max_age = timedelta(days=settings.PROPERTY_REVIEW_MAX_AGE_DAYS)
    properties = (
        db.query(Property)
        .outerjoin(PropertyReview, PropertyReview.property_id == Property.id)
        .filter(PropertyReview.id.is_(None))
        .order_by(Property.id)
        .all()
    )
    created = []
    for prop in properties:
        if prop.status != PropertyStatus.ACTIVE:
            status = S.SKIPPED
        elif is_historical(prop, now, max_age):
            status = S.SKIPPED
        elif prop.agent_id is None:
            continue
        else:
            status = S.PENDING
        review = PropertyReview(property_id=prop.id, agent_id=prop.agent_id, status=status,
                                rounds=0, created_at=now)
        db.add(review)
        created.append(review)
    if not created:
        return []
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        logger.info("Revisiones de propiedades ya registradas por otra pasada")
        return []
    pending = sum(1 for r in created if r.status == S.PENDING)
    logger.info("Revisiones de propiedades registradas: %s (%s por revisar)", len(created), pending)
    return created


def is_historical(prop, now: datetime, max_age: Optional[timedelta] = None) -> bool:
    """P7: ¿entró en el mercado hace más de `PROPERTY_REVIEW_MAX_AGE_DAYS` días? Sin fecha, no."""
    entry = getattr(prop, "market_entry_date", None)
    if entry is None:
        return False
    if max_age is None:
        max_age = timedelta(days=settings.PROPERTY_REVIEW_MAX_AGE_DAYS)
    if not isinstance(entry, datetime):
        entry = datetime.combine(entry, datetime.min.time())
    return now - entry > max_age


def _mark_review_notifications_read(db: Session, review, now: datetime, kinds: Iterable = REVIEW_KINDS) -> int:
    """Avisos sin leer de esta revisión que ya no aplican -> leídos (sin confirmar)."""
    return (
        db.query(Notification)
        .filter(
            Notification.entity_type == ENTITY,
            Notification.entity_id == review.id,
            Notification.kind.in_(list(kinds)),
            Notification.read_at.is_(None),
        )
        .update({Notification.read_at: now}, synchronize_session=False)
    )


def notify_pending(db: Session, now: Optional[datetime] = None, actor=None) -> int:
    """Primer aviso al captador de cada revisión `pending` sin avisar.

    `property_review_pending` a los usuarios del captador, en la empresa de la
    propiedad, con enlace a la caja de revisión de la ficha. `notified_at` se
    marca aunque el captador no tenga usuario en la app (queda en el log; el
    admin lo verá en «Requiere atención» si pasa el plazo). Devuelve cuántas
    notificaciones se crearon.
    """
    now = now or datetime.utcnow()
    reviews = (
        db.query(PropertyReview)
        .options(joinedload(PropertyReview.property).joinedload(Property.agent))
        .filter(PropertyReview.status == S.PENDING, PropertyReview.notified_at.is_(None))
        .order_by(PropertyReview.id)
        .all()
    )
    created = 0
    for review in reviews:
        prop = review.property
        try:
            agent = prop.agent
            users = users_for_agent(db, agent)
            if not users:
                logger.info("Propiedad %s por revisar: el captador %s no tiene usuario activo en la app",
                            prop.id, getattr(agent, "name", None))
            created += len(notify(
                db,
                users=users,
                company_id=prop.company_id,
                kind=NotificationKind.PROPERTY_REVIEW_PENDING,
                title=f"Propiedad nueva: revisa la ficha · {_title(prop)}",
                body=" · ".join(p for p in (property_summary(prop), "Marca si está correcta o qué hay que revisar") if p),
                url=review_url(prop),
                actor=actor,
                entity=(ENTITY, review.id),
                now=now,
            ))
            review.agent_id = prop.agent_id
            review.notified_at = now
        except Exception:
            logger.exception("No se pudo avisar de la revisión de la propiedad %s", prop.id)
    db.commit()
    return created


def remind_overdue(db: Session, now: Optional[datetime] = None, hours: Optional[int] = None) -> int:
    """Un único recordatorio al captador (P5).

    `pending` (desde `notified_at`) o `fixed` (desde `fixed_at`) con más de
    `PROPERTY_REVIEW_REMINDER_BUSINESS_HOURS` horas hábiles y sin recordatorio
    aún. Mismo tipo que el aviso de su estado; el anterior sin leer se marca
    leído (lo sustituye el recordatorio). `reminded_at` se marca aunque no
    haya usuario. Al corregirla el admin (`mark_fixed`) se puede volver a
    recordar una vez. Devuelve cuántas notificaciones se crearon.
    """
    now = now or datetime.utcnow()
    hours = settings.PROPERTY_REVIEW_REMINDER_BUSINESS_HOURS if hours is None else hours
    reviews = (
        db.query(PropertyReview)
        .join(Property, Property.id == PropertyReview.property_id)
        .options(joinedload(PropertyReview.property).joinedload(Property.agent))
        .filter(
            PropertyReview.status.in_(S.AWAITING_AGENT),
            PropertyReview.reminded_at.is_(None),
            Property.status == PropertyStatus.ACTIVE,
        )
        .order_by(PropertyReview.id)
        .all()
    )
    created = 0
    for review in reviews:
        start = waiting_since(review)
        if start is None or business_hours_between(start, now) < hours:
            continue
        prop = review.property
        try:
            if review.status == S.FIXED:
                kind = NotificationKind.PROPERTY_REVIEW_FIXED
                title = f"Sigue pendiente: confirma que está correcta · {_title(prop)}"
            else:
                kind = NotificationKind.PROPERTY_REVIEW_PENDING
                title = f"Sigue pendiente: revisa la propiedad · {_title(prop)}"
            _mark_review_notifications_read(db, review, now, kinds=[kind])
            created += len(notify(
                db,
                users=users_for_agent(db, prop.agent),
                company_id=prop.company_id,
                kind=kind,
                title=title,
                body=" · ".join(p for p in (property_summary(prop), "Marca si está correcta o qué hay que revisar") if p),
                url=review_url(prop),
                entity=(ENTITY, review.id),
                now=now,
            ))
            review.reminded_at = now
        except Exception:
            logger.exception("No se pudo recordar la revisión de la propiedad %s", prop.id)
    db.commit()
    return created


def safe_register_and_notify(db: Session, now: Optional[datetime] = None, actor=None) -> int:
    """Alta del admin: registra y avisa al momento; nunca rompe el alta."""
    try:
        register_new_properties(db, now=now)
        return notify_pending(db, now=now, actor=actor)
    except Exception:
        db.rollback()
        logger.exception("No se pudo registrar la revisión de las propiedades nuevas")
        return 0


# ---------------------------------------------------------------------------
# Transiciones (tabla de §4.1)
# ---------------------------------------------------------------------------

def _clean_comment(comment) -> str:
    return (comment or "").strip()


def mark_ok(db: Session, review: PropertyReview, user, now: Optional[datetime] = None,
            by_admin: bool = False) -> PropertyReview:
    """`pending`/`fixed` -> `ok` (captador o admin); `issues` -> `ok` solo el admin (P4).

    Guarda quién y cuándo, marca leídos los avisos de la revisión y, ya
    confirmado el OK, busca los compradores compatibles (plan 2).
    """
    now = now or datetime.utcnow()
    allowed = S.OPEN if by_admin else S.AWAITING_AGENT
    if review.status not in allowed:
        raise ValueError(_transition_error(review.status, "ok"))
    review.status = S.OK
    review.ok_at = now
    review.ok_by = getattr(user, "id", None)
    _mark_review_notifications_read(db, review, now)
    db.commit()
    _match_compatible_buyers(db, review, user, now)
    return review


def flag_issues(db: Session, review: PropertyReview, user, comment, now: Optional[datetime] = None) -> PropertyReview:
    """`pending`/`fixed` -> `issues` (captador): comentario obligatorio, `rounds` + 1."""
    now = now or datetime.utcnow()
    if review.status not in S.AWAITING_AGENT:
        raise ValueError(_transition_error(review.status, "issues"))
    text = _clean_comment(comment)
    if not text:
        raise ValueError("Escribe qué hay que revisar en la ficha.")
    if len(text) > COMMENT_MAX:
        raise ValueError(f"El comentario no puede pasar de {COMMENT_MAX} caracteres.")
    review.status = S.ISSUES
    review.agent_comment = text
    review.rounds = (review.rounds or 0) + 1
    review.flagged_at = now
    _mark_review_notifications_read(db, review, now)
    db.commit()
    return review


def mark_fixed(db: Session, review: PropertyReview, user, comment=None, now: Optional[datetime] = None) -> PropertyReview:
    """`issues` -> `fixed` (admin): comentario opcional y aviso al captador para el OK.

    El recordatorio vuelve a estar disponible (una vez) contando desde `fixed_at`.
    """
    now = now or datetime.utcnow()
    if review.status != S.ISSUES:
        raise ValueError(_transition_error(review.status, "fixed"))
    text = _clean_comment(comment)
    if len(text) > COMMENT_MAX:
        raise ValueError(f"El comentario no puede pasar de {COMMENT_MAX} caracteres.")
    prop = review.property
    review.status = S.FIXED
    review.admin_comment = text or None
    review.fixed_at = now
    review.fixed_by = getattr(user, "id", None)
    review.reminded_at = None
    _mark_review_notifications_read(db, review, now)
    try:
        notify(
            db,
            users=users_for_agent(db, prop.agent),
            company_id=prop.company_id,
            kind=NotificationKind.PROPERTY_REVIEW_FIXED,
            title=f"Propiedad corregida: confirma que está correcta · {_title(prop)}",
            body=review.admin_comment,
            url=review_url(prop),
            actor=user,
            entity=(ENTITY, review.id),
            now=now,
        )
    except Exception:
        logger.exception("No se pudo avisar de la corrección de la propiedad %s", prop.id)
    db.commit()
    return review


_ERRORS = {
    S.OK: "Esta propiedad ya está revisada.",
    S.SKIPPED: "Esta propiedad no necesita revisión.",
    S.ISSUES: "La propiedad está pendiente de que el administrador la corrija.",
    S.PENDING: "La propiedad aún no tiene observaciones que corregir.",
    S.FIXED: "La propiedad ya está marcada como corregida.",
}


def _transition_error(current: str, target: str) -> str:
    if current == S.PENDING and target == "fixed":
        return _ERRORS[S.PENDING]
    if current == S.FIXED and target == "fixed":
        return _ERRORS[S.FIXED]
    return _ERRORS.get(current, "No se puede cambiar el estado de la revisión.")


def _match_compatible_buyers(db: Session, review: PropertyReview, user, now: datetime):
    """Gancho al plan 2 (compradores compatibles). Nunca rompe el OK, que ya está confirmado.

    `property_match_service` aún puede no existir: import protegido.
    """
    try:
        from app.services import property_match_service
    except ImportError:
        return None
    try:
        return property_match_service.match_property(db, review.property, now, actor=user)
    except Exception:
        db.rollback()
        logger.exception("No se pudieron buscar compradores compatibles con la propiedad %s", review.property_id)
        return None


# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------

def waiting_since(review: PropertyReview) -> Optional[datetime]:
    """Desde cuándo espera al captador: `fixed_at` si la corrigió el admin; si no, el primer aviso."""
    if review.status == S.FIXED and review.fixed_at is not None:
        return review.fixed_at
    return review.notified_at or review.created_at


def is_overdue(review: PropertyReview, now: Optional[datetime] = None, hours: Optional[int] = None) -> bool:
    if review.status not in S.AWAITING_AGENT:
        return False
    hours = settings.PROPERTY_REVIEW_REMINDER_BUSINESS_HOURS if hours is None else hours
    start = waiting_since(review)
    return start is not None and business_hours_between(start, now or datetime.utcnow()) >= hours


def _open_query(db: Session, statuses, company_ids=None):
    """Revisiones en `statuses` de propiedades que siguen activas (P3)."""
    query = (
        db.query(PropertyReview)
        .join(Property, Property.id == PropertyReview.property_id)
        .filter(PropertyReview.status.in_(list(statuses)), Property.status == PropertyStatus.ACTIVE)
    )
    if company_ids is not None:
        query = query.filter(company_match(Property.company_id, company_ids))
    return query


def pending_for_agent(db: Session, agent_id: Optional[int], company_ids=None) -> list:
    """Las que esperan al captador (`pending` + `fixed`), de la más antigua a la más nueva.

    Con la propiedad y su empresa cargadas (ventana al entrar, bloque del
    Inicio). `company_ids`: un id o una lista (vista unificada); None = todas.
    """
    if agent_id is None:
        return []
    return (
        _open_query(db, S.AWAITING_AGENT, company_ids)
        .options(joinedload(PropertyReview.property).joinedload(Property.company))
        .filter(Property.agent_id == agent_id)
        .order_by(PropertyReview.created_at, PropertyReview.id)
        .all()
    )


def pending_count_for_agent(db: Session, agent_id: Optional[int], company_ids=None) -> int:
    if agent_id is None:
        return 0
    return _open_query(db, S.AWAITING_AGENT, company_ids).filter(Property.agent_id == agent_id).count()


def pending_count_for_user(db: Session, user, company_ids=None) -> int:
    """Cuántas esperan a la ficha de agente del usuario (mismo email)."""
    from app.web.dependencies.auth import get_agent_from_user
    agent = get_agent_from_user(user, db)
    return pending_count_for_agent(db, agent.id if agent is not None else None, company_ids)


def issues_for_admin(db: Session, company_ids) -> list:
    """Las que el captador pidió revisar (`issues`) y le toca corregir al admin,
    de la más antigua a la más nueva, con la propiedad, su captador y su
    empresa cargados (ventana al entrar y bloque del Inicio del admin)."""
    return (
        _open_query(db, (S.ISSUES,), company_ids)
        .options(joinedload(PropertyReview.property).joinedload(Property.company),
                 joinedload(PropertyReview.property).joinedload(Property.agent))
        .order_by(PropertyReview.flagged_at, PropertyReview.id)
        .all()
    )


def open_count_for_company(db: Session, company_ids) -> int:
    """Admin: abiertas (`pending` + `issues` + `fixed`) de la empresa (tarjeta del listado)."""
    return _open_query(db, S.OPEN, company_ids).count()


def counts_for_admin(db: Session, company_ids, now: Optional[datetime] = None) -> dict:
    """«Requiere atención» del admin: `issues` (le toca corregir) y `overdue`
    (esperan al captador desde hace más del plazo en horas hábiles)."""
    now = now or datetime.utcnow()
    issues = _open_query(db, (S.ISSUES,), company_ids).count()
    overdue = sum(1 for review in _open_query(db, S.AWAITING_AGENT, company_ids).all() if is_overdue(review, now))
    return {"issues": issues, "overdue": overdue}


def review_for_property(db: Session, property_id: int) -> Optional[PropertyReview]:
    return db.query(PropertyReview).filter(PropertyReview.property_id == property_id).first()


def is_captador(review: Optional[PropertyReview], agent) -> bool:
    prop = getattr(review, "property", None)
    return agent is not None and prop is not None and prop.agent_id is not None and prop.agent_id == agent.id


def can_review(review: Optional[PropertyReview], user, agent, is_admin: bool) -> dict:
    """Qué botones se pintan y qué rutas se aceptan.

    Captador con `pending`/`fixed`: Correcta / Revisar. Admin con `issues`:
    Corregida / Correcta; con `pending`/`fixed`: Correcta (P4). `captador`: puede
    revisarla ahora; `is_captador`: es suya, en cualquier estado. El admin tiene
    que poder ver la propiedad (lo comprueba la ruta con su empresa activa).
    """
    actions = {"ok": False, "issues": False, "fixed": False, "captador": False, "is_captador": False}
    if review is None or user is None:
        return actions
    status = review.status
    # Es el captador (en cualquier estado): ve lo que pidió mientras espera al admin
    actions["is_captador"] = is_captador(review, agent)
    if is_captador(review, agent) and status in S.AWAITING_AGENT:
        actions.update(ok=True, issues=True, captador=True)
    if is_admin:
        if status in S.OPEN:
            actions["ok"] = True
        if status == S.ISSUES:
            actions["fixed"] = True
    return actions
