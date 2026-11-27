"""Seguimiento de las propiedades nuevas y de su cruce con compradores (solo admin, solo lectura).

Pantalla de diagnóstico para saber, propiedad por propiedad, en qué punto está
la revisión (PLAN_REVISION_PROPIEDADES_NUEVAS.md), qué compradores quedaron
registrados como compatibles al dar el OK (PLAN_COMPRADORES_COMPATIBLES_PROPIEDAD_NUEVA.md),
a qué agentes se avisó y, sobre todo, POR QUÉ el resto de compradores no
encajan. No escribe nada: no registra cruces, no avisa ni cambia estados.

- `reasons_not_matching(criteria, prop)`: todas las condiciones de
  `buyer_matching.criteria_matches_property` que NO se cumplen, en texto, con
  los valores de la propiedad y del perfil. Lista vacía <=> encaja. Es una
  réplica más del cruce (como `_matching_filters` y
  `criteria_matches_property`): si cambia uno, cambian los tres (el test
  cruzado lo vigila).
- `explain_alert(alert, prop, ...)`: evaluación de una alerta siguiendo el
  mismo orden que `property_match_service.candidate_alerts`: abierta, con
  comprador, agente activo, operación con perfil, perfil completo y encaje.
- `audit_rows(...)`: una fila por propiedad nueva (con revisión) del periodo,
  con la revisión, los cruces registrados, los avisos y una simulación del
  cruce con los datos de HOY (propiedad y perfiles actuales).
- `audit_detail(...)`: lo mismo para una propiedad, con todas las alertas
  evaluadas una a una.
"""
from collections import Counter
from datetime import datetime
from datetime import timedelta
from typing import Optional

from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy.orm import Session
from sqlalchemy.orm import joinedload

from app.core import geo
from app.core.config import settings
from app.core.constants import AlertStatus
from app.core.constants import PropertyReviewStatus as S
from app.core.constants import PropertyStatus
from app.models.buyer import Buyer
from app.models.notification import Notification
from app.models.property import Property
from app.models.property_alert import PropertyAlert
from app.models.property_buyer_match import PropertyBuyerMatch
from app.models.property_review import PropertyReview
from app.models.user import User
from app.services import buyer_matching
from app.services import property_match_service as pms
from app.services import property_review_service as prs
from app.services.company_scope import company_match
from app.services.notification_service import NotificationKind
from app.web.template_env import eur

# Alertas cerradas que se evalúan en el detalle: cerradas hace menos de estos días
CLOSED_ALERTS_MAX_DAYS = 90

ALERT_STATUS_LABELS = {
    AlertStatus.PENDING: "Pendiente",
    AlertStatus.IN_PROGRESS: "En proceso",
    AlertStatus.COMPLETED: "Completada",
    AlertStatus.CANCELLED: "Cancelada",
}

# Resultado de la evaluación de una alerta (`explain_alert`)
OUTCOME_MATCH = "match"            # encaja con los datos de hoy
OUTCOME_EXCLUDED = "excluded"      # queda fuera del cruce antes de mirar el perfil
OUTCOME_NO_MATCH = "no_match"      # el perfil no encaja con la propiedad

OUTCOME_LABELS = {
    OUTCOME_MATCH: "Encaja",
    OUTCOME_EXCLUDED: "Fuera del cruce",
    OUTCOME_NO_MATCH: "No encaja",
}


# ---------------------------------------------------------------------------
# Por qué no encaja (réplica explicada de criteria_matches_property)
# ---------------------------------------------------------------------------

def _num(value) -> str:
    return "sin dato" if value is None else str(value)


def _n(count: int, singular: str, plural: str) -> str:
    """«1 comprador» / «3 compradores»."""
    return f"{count} {singular if count == 1 else plural}"


def _list(values) -> str:
    return ", ".join(str(v) for v in values) if values else "—"


def _same_text_hint(prop_value, wanted) -> str:
    """Pista cuando la diferencia es solo de acentos o mayúsculas («Jaen» / «Jaén»)."""
    key = geo.city_key(prop_value)
    for value in wanted:
        if value and geo.city_key(value) == key:
            return f" (solo difiere en acentos o mayúsculas de «{value}»: el cruce compara el texto exacto)"
    return ""


def reasons_not_matching(criteria, prop) -> list:
    """Condiciones del cruce que NO se cumplen, en texto; [] si encaja.

    Mismo orden y mismas comparaciones que `buyer_matching.criteria_matches_property`.
    Un dato vacío de la propiedad nunca cumple un filtro (salvo «sin ascensor»),
    y se dice explícitamente porque es la causa más fácil de pasar por alto.
    """
    reasons = []
    if criteria is None:
        return ["Sin perfil de búsqueda"]
    if prop is None:
        return ["Sin propiedad"]
    if prop.status != PropertyStatus.ACTIVE:
        reasons.append(f"Propiedad no activa (estado «{prop.status}»)")
    if prop.agent_id is None:
        reasons.append("Propiedad sin captador")

    if criteria.province and geo.cp_prefix_for_provincia(criteria.province):
        prefix = geo.cp_prefix_for_provincia(criteria.province)
        if not buyer_matching._country_matches(prop, geo.SPAIN):
            reasons.append(f"País: la propiedad dice «{prop.pais}» y el perfil pide provincia de España ({criteria.province})")
        if not buyer_matching._province_matches(prop, criteria.province):
            cp = (prop.cod_postal or "").strip(" ")
            if not cp:
                reasons.append(f"Provincia: la propiedad no tiene código postal y el perfil pide {criteria.province} (CP {prefix}xxx)")
            else:
                reasons.append(f"Provincia: el CP «{cp}» no es de {criteria.province} (CP {prefix}xxx)")
    elif criteria.country:
        if not buyer_matching._country_matches(prop, criteria.country):
            reasons.append(f"País: la propiedad dice «{prop.pais or 'vacío'}» y el perfil pide {criteria.country}")

    if criteria.zones and (prop.zona is None or prop.zona not in criteria.zones):
        if prop.zona is None:
            reasons.append(f"Zona: la propiedad no tiene zona y el perfil pide {_list(criteria.zones)}")
        else:
            reasons.append(f"Zona: «{prop.zona}» no está en {_list(criteria.zones)}"
                           + _same_text_hint(prop.zona, criteria.zones))
    if criteria.cities and (prop.city is None or prop.city not in criteria.cities):
        if prop.city is None:
            reasons.append(f"Población: la propiedad no tiene población y el perfil pide {_list(criteria.cities)}")
        else:
            reasons.append(f"Población: «{prop.city}» no está en {_list(criteria.cities)}"
                           + _same_text_hint(prop.city, criteria.cities))
    types = buyer_matching.profile_types(criteria)
    if types and (prop.property_type is None or prop.property_type not in types):
        reasons.append(f"Tipo: «{prop.property_type or 'vacío'}» no está en {_list(types)}"
                       + (_same_text_hint(prop.property_type, types) if prop.property_type else ""))
    if criteria.business_type and prop.business_type != criteria.business_type:
        reasons.append(f"Operación: la propiedad es «{prop.business_type or 'vacía'}» y el perfil busca {criteria.business_type}")
    if criteria.min_price is not None and not buyer_matching._at_least(prop.price, criteria.min_price):
        reasons.append(f"Precio: {eur(prop.price) if prop.price is not None else 'sin precio'} por debajo del mínimo {eur(criteria.min_price)}")
    if criteria.max_price is not None and not buyer_matching._at_most(prop.price, criteria.max_price):
        reasons.append(f"Precio: {eur(prop.price) if prop.price is not None else 'sin precio'} supera el máximo {eur(criteria.max_price)}")
    if criteria.min_bedrooms is not None and not buyer_matching._at_least(prop.num_dormitorios, criteria.min_bedrooms):
        reasons.append(f"Dormitorios: {_num(prop.num_dormitorios)} y el perfil pide al menos {criteria.min_bedrooms}")
    if criteria.max_bedrooms is not None and not buyer_matching._at_most(prop.num_dormitorios, criteria.max_bedrooms):
        reasons.append(f"Dormitorios: {_num(prop.num_dormitorios)} y el perfil pide como máximo {criteria.max_bedrooms}")
    if criteria.min_bathrooms is not None and not buyer_matching._at_least(prop.num_banos_aseos, criteria.min_bathrooms):
        reasons.append(f"Baños: {_num(prop.num_banos_aseos)} y el perfil pide al menos {criteria.min_bathrooms}")
    if criteria.elevator is True and not buyer_matching._at_least(prop.num_ascensores, 1):
        reasons.append(f"Ascensor: el perfil lo pide y la propiedad tiene {_num(prop.num_ascensores)}")
    if criteria.elevator is False and not (prop.num_ascensores is None or prop.num_ascensores == 0):
        reasons.append(f"Ascensor: el perfil lo descarta y la propiedad tiene {prop.num_ascensores}")
    if criteria.garage is True and not buyer_matching._at_least(prop.num_garaje_aparcam, 1):
        reasons.append(f"Garaje: el perfil lo pide y la propiedad tiene {_num(prop.num_garaje_aparcam)} plazas")
    return reasons


# ---------------------------------------------------------------------------
# Evaluación de una alerta (mismo orden que candidate_alerts)
# ---------------------------------------------------------------------------

def explain_alert(alert, prop, users_by_email: Optional[dict] = None) -> dict:
    """Evalúa una alerta contra la propiedad con los datos de hoy.

    `users_by_email`: {email en minúsculas: [User activos]} para decir si el
    agente tiene usuario en la app (sin él no hay aviso posible).
    """
    agent = alert.agent
    criteria = alert.buyer.search_criteria if alert.buyer is not None else None
    email = ((getattr(agent, "email", None) or "").strip().lower())
    users = (users_by_email or {}).get(email, []) if email else []

    excluded = []
    if alert.status not in pms.CANDIDATE_STATUSES:
        excluded.append(f"Alerta cerrada ({ALERT_STATUS_LABELS.get(alert.status, alert.status)}): solo entran pendientes y en proceso")
    if alert.buyer_id is None or alert.buyer is None:
        excluded.append("Alerta sin comprador: no puede tener perfil")
    if agent is None:
        excluded.append("Alerta sin agente")
    elif not agent.is_active:
        excluded.append(f"Agente inactivo ({agent.name})")
    if not buyer_matching.profile_applies(alert.business_type):
        excluded.append(f"Alerta de {alert.business_type}: en esa operación no hay perfil ni cruce")
    if alert.buyer is not None and buyer_matching.profile_applies(alert.business_type):
        if criteria is None:
            excluded.append("Sin perfil de búsqueda guardado")
        else:
            missing = buyer_matching.missing_profile_fields(criteria)
            if missing:
                excluded.append("Perfil incompleto: falta " + buyer_matching.missing_profile_text(missing))

    reasons = reasons_not_matching(criteria, prop) if criteria is not None else []
    if excluded:
        outcome = OUTCOME_EXCLUDED
    elif reasons:
        outcome = OUTCOME_NO_MATCH
    else:
        outcome = OUTCOME_MATCH
    return {
        "alert": alert,
        "buyer_name": pms.buyer_name(alert),
        "agent": agent,
        "agent_users": users,
        "company": alert.company,
        "criteria": criteria,
        "criteria_summary": buyer_matching.criteria_summary(criteria),
        "outcome": outcome,
        "excluded": excluded,
        "reasons": reasons,
        # Encajaría si no estuviera fuera del cruce (cerrada, agente inactivo…)
        "fits_profile": criteria is not None and not reasons,
    }


# ---------------------------------------------------------------------------
# Carga de datos
# ---------------------------------------------------------------------------

def _alerts_query(db: Session):
    return (
        db.query(PropertyAlert)
        .options(
            joinedload(PropertyAlert.buyer).joinedload(Buyer.search_criteria),
            joinedload(PropertyAlert.agent),
            joinedload(PropertyAlert.company),
        )
        .order_by(PropertyAlert.id)
    )


def open_alerts_with_buyer(db: Session) -> list:
    """Alertas abiertas con comprador, de cualquier agente (activo o no) y empresa."""
    return (
        _alerts_query(db)
        .filter(PropertyAlert.status.in_(pms.CANDIDATE_STATUSES), PropertyAlert.buyer_id.isnot(None))
        .all()
    )


def recently_closed_alerts_with_buyer(db: Session, now: datetime) -> list:
    """Cerradas (completadas o canceladas) hace menos de `CLOSED_ALERTS_MAX_DAYS` días, con comprador."""
    since = now - timedelta(days=CLOSED_ALERTS_MAX_DAYS)
    return (
        _alerts_query(db)
        .filter(
            PropertyAlert.status.notin_(pms.CANDIDATE_STATUSES),
            PropertyAlert.buyer_id.isnot(None),
            or_(PropertyAlert.completed_at >= since,
                PropertyAlert.completed_at.is_(None) & (PropertyAlert.created_at >= since)),
        )
        .all()
    )


def agent_email(agent) -> str:
    return ((getattr(agent, "email", None) or "").strip().lower())


def users_by_agent_email(db: Session, agents) -> dict:
    """{email en minúsculas: [User activos]} de esos agentes (una consulta; None se ignora)."""
    emails = {agent_email(a) for a in agents if agent_email(a)}
    if not emails:
        return {}
    users = (
        db.query(User)
        .filter(func.lower(User.email).in_(emails), User.is_active.isnot(False))
        .order_by(User.id)
        .all()
    )
    result = {}
    for user in users:
        result.setdefault((user.email or "").strip().lower(), []).append(user)
    return result


def _notifications_by_entity(db: Session, kind: str, entity_type: str, entity_ids) -> dict:
    """{entity_id: [Notification]} de ese tipo, con usuario y empresa cargados."""
    ids = [i for i in entity_ids if i is not None]
    if not ids:
        return {}
    rows = (
        db.query(Notification)
        .options(joinedload(Notification.user), joinedload(Notification.company))
        .filter(Notification.kind == kind, Notification.entity_type == entity_type,
                Notification.entity_id.in_(ids))
        .order_by(Notification.created_at, Notification.id)
        .all()
    )
    result = {}
    for n in rows:
        result.setdefault(n.entity_id, []).append(n)
    return result


def _review_notifications(db: Session, review_ids) -> dict:
    ids = [i for i in review_ids if i is not None]
    if not ids:
        return {}
    rows = (
        db.query(Notification)
        .options(joinedload(Notification.user))
        .filter(Notification.entity_type == prs.ENTITY, Notification.entity_id.in_(ids),
                Notification.kind.in_(list(prs.REVIEW_KINDS)))
        .order_by(Notification.created_at, Notification.id)
        .all()
    )
    result = {}
    for n in rows:
        result.setdefault(n.entity_id, []).append(n)
    return result


def _matches_by_property(db: Session, property_ids) -> dict:
    ids = list(property_ids)
    if not ids:
        return {}
    rows = (
        db.query(PropertyBuyerMatch)
        .options(
            joinedload(PropertyBuyerMatch.alert).joinedload(PropertyAlert.agent),
            joinedload(PropertyBuyerMatch.alert).joinedload(PropertyAlert.buyer).joinedload(Buyer.search_criteria),
            joinedload(PropertyBuyerMatch.alert).joinedload(PropertyAlert.company),
            joinedload(PropertyBuyerMatch.agent),
            joinedload(PropertyBuyerMatch.company),
        )
        .filter(PropertyBuyerMatch.property_id.in_(ids))
        .order_by(PropertyBuyerMatch.property_id, PropertyBuyerMatch.id)
        .all()
    )
    result = {}
    for m in rows:
        result.setdefault(m.property_id, []).append(m)
    return result


def _search_clause(text: str):
    """Buscar una propiedad concreta: título, referencia, código, población o id."""
    text = (text or "").strip()
    if not text:
        return None
    like = f"%{text}%"
    clauses = [Property.title.ilike(like), Property.referencia.ilike(like), Property.codigo.ilike(like),
               Property.city.ilike(like)]
    if text.isdigit():
        clauses.append(Property.id == int(text))
    return or_(*clauses)


def _reviews_query(db: Session, company_ids, since: Optional[datetime], status: Optional[str],
                   search: Optional[str] = None):
    query = (
        db.query(PropertyReview)
        .join(Property, Property.id == PropertyReview.property_id)
        .options(
            joinedload(PropertyReview.property).joinedload(Property.agent),
            joinedload(PropertyReview.property).joinedload(Property.company),
            joinedload(PropertyReview.agent),
            joinedload(PropertyReview.ok_by_user),
            joinedload(PropertyReview.fixed_by_user),
        )
    )
    if company_ids is not None:
        query = query.filter(company_match(Property.company_id, company_ids))
    if since is not None:
        # Las `skipped` de la migración tienen todas el mismo `created_at` (el del
        # despliegue): solo entran por su fecha de alta en el mercado
        query = query.filter(or_(
            Property.market_entry_date >= since,
            (PropertyReview.status != S.SKIPPED) & (PropertyReview.created_at >= since),
        ))
    if status and status != "todas":
        query = query.filter(PropertyReview.status == status)
    clause = _search_clause(search)
    if clause is not None:
        query = query.filter(clause)
    return query.order_by(PropertyReview.created_at.desc(), PropertyReview.id.desc())


# ---------------------------------------------------------------------------
# Filas del listado
# ---------------------------------------------------------------------------

def _review_facts(review, prop, now: datetime) -> dict:
    """Lo que hay que saber de la revisión de un vistazo (y por qué está así)."""
    facts = {
        "historical": prs.is_historical(prop, now),
        "overdue": prs.is_overdue(review, now),
        "waiting_since": prs.waiting_since(review),
        "cross_ran": review.status == S.OK,
    }
    if review.status == S.SKIPPED:
        if facts["historical"]:
            facts["skipped_why"] = (f"Entró en el mercado hace más de {settings.PROPERTY_REVIEW_MAX_AGE_DAYS} días: "
                                    "se trató como carga histórica, sin revisión ni cruce")
        elif prop.status != PropertyStatus.ACTIVE:
            facts["skipped_why"] = f"Entró con estado «{prop.status}»: no pide revisión"
        else:
            facts["skipped_why"] = "Existía antes del despliegue de la revisión (o entró no activa): sin revisión ni cruce"
    return facts


def _simulate(prop, pool: list, users_by_email: dict) -> list:
    """Evalúa todas las alertas abiertas con comprador contra la propiedad (datos de hoy)."""
    return [explain_alert(alert, prop, users_by_email) for alert in pool]


def _diagnosis(review, prop, registered: list, simulated_matches: list, match_notifications: list,
               review_notifications: list, facts: dict) -> list:
    """Conclusiones en texto para la fila: qué pasó y qué no, con la causa más probable."""
    notes = []
    captador_users = {u.id for u in (facts.get("captador_users") or [])}
    if review.status == S.SKIPPED:
        notes.append(facts.get("skipped_why") or "Sin revisión")
        if simulated_matches:
            notes.append(f"Aun así, hoy {_n(len(simulated_matches), 'comprador encajaría', 'compradores encajarían')}: "
                         "nadie fue avisado porque sin OK no hay cruce")
        return notes
    if review.status in S.OPEN:
        notes.append("Sin OK todavía: el cruce con compradores no se ha hecho")
        if not captador_users and review.status in S.AWAITING_AGENT:
            notes.append("El captador no tiene usuario activo en la app: no puede ver el aviso ni dar el OK")
        if review.status in S.AWAITING_AGENT and not review_notifications:
            notes.append("No hay aviso de revisión registrado para el captador")
        if simulated_matches:
            notes.append(f"Cuando se confirme, hoy {_n(len(simulated_matches), 'comprador encajaría', 'compradores encajarían')}")
        else:
            notes.append("Con los datos de hoy ningún comprador encajaría")
        return notes

    # status == ok
    registered_ids = {m.alert_id for m in registered}
    simulated_ids = {r["alert"].id for r in simulated_matches}
    if not registered:
        if simulated_matches:
            notes.append(f"Se dio el OK pero no quedó ningún cruce registrado, y hoy {_n(len(simulated_matches), 'comprador encajaría', 'compradores encajarían')}: "
                         "o la propiedad / los perfiles cambiaron después del OK, o el cruce falló (revisar el log del servidor)")
        else:
            notes.append("Se dio el OK y ningún comprador encajó: con los datos de hoy tampoco encaja ninguno")
    else:
        agents = {m.agent_id for m in registered}
        notes.append(f"{_n(len(registered), 'comprador registrado', 'compradores registrados')} de {_n(len(agents), 'agente', 'agentes')}")
        unnotified = [m for m in registered if m.notified_at is None]
        if unnotified:
            notes.append(f"{len(unnotified)} sin aviso: su agente no tenía usuario activo en la app al cruzar")
        if not match_notifications:
            notes.append("No se creó ninguna notificación: todos los compradores son del captador que dio el OK "
                         "(nunca se avisa a sí mismo) o sus agentes no tienen usuario")
        else:
            unread = [n for n in match_notifications if n.read_at is None]
            notes.append(f"{_n(len(match_notifications), 'aviso creado', 'avisos creados')}, {len(match_notifications) - len(unread)} leídos")
    new_now = simulated_ids - registered_ids
    gone_now = registered_ids - simulated_ids
    if registered and new_now:
        notes.append(f"{_n(len(new_now), 'comprador encaja', 'compradores encajan')} hoy pero no al dar el OK (perfil o alerta posterior): "
                     "no se les avisó, el cruce solo corre al dar el OK")
    if gone_now:
        notes.append(f"{_n(len(gone_now), 'registrado ya no encaja', 'registrados ya no encajan')} con los datos de hoy (perfil, alerta o propiedad cambiados)")
    return notes


def audit_rows(db: Session, company_ids, days: int = 30, status: Optional[str] = None,
               now: Optional[datetime] = None, search: Optional[str] = None) -> dict:
    """Filas del listado y resumen. `company_ids`: id, lista o None (todas).
    `search`: una propiedad concreta (título, referencia, código, población o id); con
    búsqueda no se limita el periodo, para encontrarla aunque sea antigua."""
    now = now or datetime.utcnow()
    since = now - timedelta(days=days) if days and not (search or "").strip() else None
    reviews = _reviews_query(db, company_ids, since, status, search).all()
    props = [r.property for r in reviews]
    prop_ids = [p.id for p in props]

    pool = open_alerts_with_buyer(db)
    users_by_email = users_by_agent_email(db, [a.agent for a in pool] + [p.agent for p in props])
    matches_by_prop = _matches_by_property(db, prop_ids)
    match_notifs = _notifications_by_entity(db, NotificationKind.PROPERTY_MATCH, pms.ENTITY, prop_ids)
    review_notifs = _review_notifications(db, [r.id for r in reviews])

    rows = []
    for review in reviews:
        prop = review.property
        facts = _review_facts(review, prop, now)
        facts["captador_users"] = users_by_email.get(agent_email(prop.agent), [])
        registered = matches_by_prop.get(prop.id, [])
        evaluated = _simulate(prop, pool, users_by_email)
        simulated = [r for r in evaluated if r["outcome"] == OUTCOME_MATCH]
        m_notifs = match_notifs.get(prop.id, [])
        r_notifs = review_notifs.get(review.id, [])
        rows.append({
            "review": review,
            "property": prop,
            "facts": facts,
            "registered": registered,
            "registered_agents": len({m.agent_id for m in registered}),
            "registered_notified": sum(1 for m in registered if m.notified_at is not None),
            "simulated": simulated,
            "simulated_agents": len({r["alert"].agent_id for r in simulated}),
            "match_notifications": m_notifs,
            "match_read": sum(1 for n in m_notifs if n.read_at is not None),
            "review_notifications": r_notifs,
            "diagnosis": _diagnosis(review, prop, registered, simulated, m_notifs, r_notifs, facts),
        })

    counts = Counter(r.status for r in reviews)
    summary = {
        "total": len(reviews),
        "ok": counts.get(S.OK, 0),
        "pending": counts.get(S.PENDING, 0),
        "issues": counts.get(S.ISSUES, 0),
        "fixed": counts.get(S.FIXED, 0),
        "skipped": counts.get(S.SKIPPED, 0),
        "with_registered": sum(1 for r in rows if r["registered"]),
        "with_simulated": sum(1 for r in rows if r["simulated"]),
        "notifications": sum(len(r["match_notifications"]) for r in rows),
        "pool": pool_summary(pool, users_by_email),
    }
    return {"rows": rows, "summary": summary, "now": now}


def pool_summary(pool: list, users_by_email: dict) -> dict:
    """Cuántos compradores pueden entrar hoy al cruce, y dónde se van quedando por el camino."""
    total = len(pool)
    active = [a for a in pool if a.agent is not None and a.agent.is_active]
    with_profile_op = [a for a in active if buyer_matching.profile_applies(a.business_type)]
    with_criteria = [a for a in with_profile_op if a.buyer is not None and a.buyer.search_criteria is not None]
    complete = [a for a in with_criteria if buyer_matching.profile_is_complete(a.buyer.search_criteria)]
    with_user = [a for a in complete if users_by_email.get(agent_email(a.agent))]
    by_company = Counter((a.company.name if a.company is not None else "—") for a in complete)
    return {
        "total": total,
        "active_agent": len(active),
        "profile_operation": len(with_profile_op),
        "with_criteria": len(with_criteria),
        "complete": len(complete),
        "with_user": len(with_user),
        "by_company": sorted(by_company.items()),
    }


# ---------------------------------------------------------------------------
# Detalle de una propiedad
# ---------------------------------------------------------------------------

def audit_detail(db: Session, prop, now: Optional[datetime] = None) -> dict:
    now = now or datetime.utcnow()
    review = (
        db.query(PropertyReview)
        .options(joinedload(PropertyReview.agent), joinedload(PropertyReview.ok_by_user),
                 joinedload(PropertyReview.fixed_by_user))
        .filter(PropertyReview.property_id == prop.id)
        .first()
    )
    pool = open_alerts_with_buyer(db)
    closed = recently_closed_alerts_with_buyer(db, now)
    users_by_email = users_by_agent_email(db, [a.agent for a in pool + closed] + [prop.agent])
    captador_users = users_by_email.get(agent_email(prop.agent), [])

    registered = _matches_by_property(db, [prop.id]).get(prop.id, [])
    registered_by_alert = {m.alert_id: m for m in registered}
    evaluated = _simulate(prop, pool, users_by_email)
    for row in evaluated:
        row["match"] = registered_by_alert.get(row["alert"].id)
    closed_rows = [r for r in (explain_alert(a, prop, users_by_email) for a in closed) if r["fits_profile"]]
    for row in closed_rows:
        row["match"] = registered_by_alert.get(row["alert"].id)

    matches_now = [r for r in evaluated if r["outcome"] == OUTCOME_MATCH]
    excluded = [r for r in evaluated if r["outcome"] == OUTCOME_EXCLUDED]
    no_match = [r for r in evaluated if r["outcome"] == OUTCOME_NO_MATCH]
    # Registrados cuya alerta ya no está en el grupo de abiertas (cerrada después) o que ya no encaja
    registered_rows = []
    for m in registered:
        row = next((r for r in evaluated if r["alert"].id == m.alert_id), None)
        if row is None:
            row = explain_alert(m.alert, prop, users_by_email)
            row["match"] = m
        registered_rows.append(row)

    # Qué condición del perfil falla más veces (para ver de un vistazo el motivo dominante)
    reason_counter = Counter()
    for r in no_match:
        for reason in r["reasons"]:
            reason_counter[reason.split(":", 1)[0]] += 1
    excluded_counter = Counter()
    for r in excluded:
        for reason in r["excluded"]:
            excluded_counter[reason.split(":", 1)[0].split(" (")[0]] += 1

    m_notifs = _notifications_by_entity(db, NotificationKind.PROPERTY_MATCH, pms.ENTITY, [prop.id]).get(prop.id, [])
    r_notifs = _review_notifications(db, [review.id] if review else []).get(review.id, []) if review else []
    facts = _review_facts(review, prop, now) if review else {}
    facts["captador_users"] = captador_users
    return {
        "now": now,
        "property": prop,
        "review": review,
        "facts": facts,
        "registered": registered_rows,
        "matches_now": matches_now,
        "excluded": excluded,
        "no_match": no_match,
        "closed_fit": closed_rows,
        "reason_counter": reason_counter.most_common(),
        "excluded_counter": excluded_counter.most_common(),
        "match_notifications": m_notifs,
        "review_notifications": r_notifs,
        "pool_total": len(pool),
        "diagnosis": _diagnosis(review, prop, registered, matches_now, m_notifs, r_notifs, facts) if review
        else ["La propiedad no tiene fila de revisión: el job aún no la ha registrado (o está sin captador)"],
        "settings": {
            "max_age_days": settings.PROPERTY_REVIEW_MAX_AGE_DAYS,
            "poll_minutes": settings.PROPERTY_REVIEW_POLL_MINUTES,
            "enabled": settings.PROPERTY_REVIEW_ENABLED,
            "closed_days": CLOSED_ALERTS_MAX_DAYS,
        },
    }
