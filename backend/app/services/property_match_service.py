"""Compradores compatibles con una propiedad nueva.

PLAN_COMPRADORES_COMPATIBLES_PROPIEDAD_NUEVA.md §4.3. Cuando el captador (o el
admin) marca una propiedad nueva como correcta
(`property_review_service.mark_ok`, PLAN_REVISION_PROPIEDADES_NUEVAS.md), se
buscan TODOS los compradores cuyo perfil encaja con ella, de cualquier agente
activo y de las dos empresas (D1), y se avisa a cada agente de cuáles de sus
compradores encajan.

- Candidatos (P2, `candidate_alerts`): alertas abiertas (`PENDING` +
  `IN_PROGRESS`) con comprador y perfil completo (`profile_is_complete`), de
  un agente activo, en las operaciones con perfil (`profile_applies`: en
  Alquiler el perfil no se muestra ni sugiere propiedades, así que tampoco
  entra aquí). Prefiltro SQL por operación y precio máximo; el cruce fino es
  `buyer_matching.criteria_matches_property`. Es el ÚNICO sitio que decide qué
  alertas entran (gancho de la futura «Reserva de compradores», §6).
- La propiedad tiene que seguir activa y con captador (las mismas condiciones
  que las sugerencias del perfil).
- Un aviso por agente y propiedad (P1), uno por empresa de la alerta (vista
  unificada: un agente con compradores compatibles en las dos empresas recibe
  uno en cada una, con su distintivo). Tipo `property_match`, violet.
- Nunca se añade la propiedad a la lista de interés ni se crea un seguimiento
  (P5). El mensaje al comprador lo manda el agente con un clic desde la página
  de compatibles (P3: «Enviar por WhatsApp», `routes/alerts.py::_send_property`).
  Nada de envío automático ni de Evolution API.
- Idempotente: una fila por propiedad y alerta; un segundo cruce solo añade
  (y avisa de) las alertas nuevas.
"""
import logging
from collections import OrderedDict
from datetime import datetime
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm import joinedload

from app.core.constants import AlertStatus
from app.core.constants import PropertyStatus
from app.models.agent import Agent
from app.models.buyer import Buyer
from app.models.buyer_search_criteria import BuyerSearchCriteria
from app.models.property_alert import PropertyAlert
from app.models.property_buyer_match import PropertyBuyerMatch
from app.services import buyer_matching
from app.services.notification_service import NotificationKind
from app.services.notification_service import notify
from app.services.notification_service import users_for_agent
from app.services.property_review_service import property_summary

logger = logging.getLogger(__name__)

ENTITY = "property"
# Estados de alerta que entran al cruce (P2). «Reserva de compradores» (§6):
# añadir aquí su estado cuando exista.
CANDIDATE_STATUSES = (AlertStatus.PENDING, AlertStatus.IN_PROGRESS)
# Nombres de comprador que se citan en el cuerpo del aviso
NOTIFY_MAX_NAMES = 3


def matches_url(prop_or_id) -> str:
    prop_id = getattr(prop_or_id, "id", prop_or_id)
    return f"/properties/{prop_id}/matches"


def buyer_name(alert) -> str:
    """Nombre del comprador de la alerta (el de la alerta o el de su ficha)."""
    name = (alert.lead_name or "").strip()
    if not name and alert.buyer is not None:
        name = (alert.buyer.name or "").strip()
    return name or "Comprador sin nombre"


# ---------------------------------------------------------------------------
# Candidatos y cruce
# ---------------------------------------------------------------------------

def is_matchable(prop) -> bool:
    """La propiedad entra al cruce: activa y con captador (como las sugerencias)."""
    return prop is not None and prop.status == PropertyStatus.ACTIVE and prop.agent_id is not None


def candidate_alerts(db: Session, prop) -> list:
    """Alertas cuyo comprador encaja con `prop` (P2), de todos los agentes y empresas.

    Gancho para «Reserva de compradores» (§6): esta función es el ÚNICO sitio
    que decide qué alertas entran al cruce. Para incluir a los compradores en
    reserva basta con añadir su estado a `CANDIDATE_STATUSES` (y, si se quiere
    un aviso distinto, decidir el `kind` en `match_property` según el estado).

    Prefiltro en SQL (operación y precio máximo, para no evaluar todos los
    perfiles en Python); después perfil completo y `criteria_matches_property`.
    Orden estable por id de alerta.
    """
    if not is_matchable(prop):
        return []
    query = (
        db.query(PropertyAlert)
        .join(Buyer, Buyer.id == PropertyAlert.buyer_id)
        .join(BuyerSearchCriteria, BuyerSearchCriteria.buyer_id == Buyer.id)
        .join(Agent, Agent.id == PropertyAlert.agent_id)
        .options(
            joinedload(PropertyAlert.buyer).joinedload(Buyer.search_criteria),
            joinedload(PropertyAlert.agent),
        )
        .filter(
            PropertyAlert.status.in_(CANDIDATE_STATUSES),
            Agent.is_active.is_(True),
        )
    )
    # La operación del perfil, si la tiene, debe ser la de la propiedad
    if prop.business_type:
        query = query.filter(or_(BuyerSearchCriteria.business_type.is_(None),
                                 BuyerSearchCriteria.business_type == prop.business_type))
    else:
        query = query.filter(BuyerSearchCriteria.business_type.is_(None))
    # Precio máximo (mínimo del perfil completo): la propiedad no puede pasarlo
    if prop.price is not None:
        query = query.filter(or_(BuyerSearchCriteria.max_price.is_(None),
                                 BuyerSearchCriteria.max_price >= prop.price))
    else:
        query = query.filter(BuyerSearchCriteria.max_price.is_(None))

    result = []
    for alert in query.order_by(PropertyAlert.id).all():
        criteria = alert.buyer.search_criteria
        if not buyer_matching.profile_applies(alert.business_type):
            continue
        if not buyer_matching.profile_is_complete(criteria):
            continue
        if buyer_matching.criteria_matches_property(criteria, prop):
            result.append(alert)
    return result


def _notification_text(prop, alerts: list) -> tuple:
    """(título, cuerpo) del aviso `property_match` de un agente (§4.4)."""
    count = len(alerts)
    verb = "comprador encaja" if count == 1 else "compradores encajan"
    title = f"{count} {verb} con una propiedad nueva · {(prop.title or 'Propiedad').strip()}"
    names = [buyer_name(a) for a in alerts]
    shown = ", ".join(names[:NOTIFY_MAX_NAMES])
    extra = count - NOTIFY_MAX_NAMES
    if extra > 0:
        shown += f" y {extra} más"
    body = " · ".join(part for part in (property_summary(prop), shown) if part)
    return title, body


def match_property(db: Session, prop, now: Optional[datetime] = None, actor=None) -> list:
    """Cruza la propiedad con los perfiles y avisa a los agentes (§4.3). Devuelve las filas NUEVAS.

    - Propiedad no activa o sin captador -> [].
    - Inserta una fila por alerta compatible que aún no la tuviera.
    - Una notificación `property_match` por agente y empresa de la alerta,
      con las alertas nuevas de ese agente. `actor` (quien dio el OK) nunca se
      avisa a sí mismo (`notify` lo excluye); su `notified_at` se marca igual.
      Sin usuario activo del agente: `notified_at` queda nulo.
    - Commit propio. Nunca lanza: lo llama `mark_ok` con el OK ya confirmado;
      ante un error deshace lo suyo, lo deja en el log y devuelve [].
    """
    now = now or datetime.utcnow()
    try:
        if not is_matchable(prop):
            return []
        alerts = candidate_alerts(db, prop)
        if not alerts:
            return []
        existing = {
            alert_id for (alert_id,) in
            db.query(PropertyBuyerMatch.alert_id).filter(PropertyBuyerMatch.property_id == prop.id)
        }
        new_alerts = [a for a in alerts if a.id not in existing]
        if not new_alerts:
            return []

        created = []
        groups = OrderedDict()
        for alert in new_alerts:
            match = PropertyBuyerMatch(property_id=prop.id, alert_id=alert.id, agent_id=alert.agent_id,
                                       company_id=alert.company_id, created_at=now)
            db.add(match)
            created.append(match)
            groups.setdefault((alert.agent_id, alert.company_id), []).append((alert, match))
        db.flush()

        notified = 0
        for (agent_id, company_id), rows in groups.items():
            group_alerts = [alert for alert, _ in rows]
            agent = group_alerts[0].agent
            users = users_for_agent(db, agent)
            if not users:
                logger.info("Compradores compatibles con la propiedad %s: el agente %s no tiene usuario activo",
                            prop.id, getattr(agent, "name", agent_id))
                continue
            title, body = _notification_text(prop, group_alerts)
            notified += len(notify(
                db,
                users=users,
                company_id=company_id,
                kind=NotificationKind.PROPERTY_MATCH,
                title=title,
                body=body,
                url=matches_url(prop),
                actor=actor,
                entity=(ENTITY, prop.id),
                now=now,
            ))
            for _, match in rows:
                match.notified_at = now
        db.commit()
        logger.info("Propiedad %s: %s compradores compatibles nuevos, %s agentes, %s avisos",
                    prop.id, len(created), len(groups), notified)
        return created
    except IntegrityError:
        db.rollback()
        logger.info("Compradores compatibles con la propiedad %s ya registrados por otra pasada",
                    getattr(prop, "id", None))
        return []
    except Exception:
        db.rollback()
        logger.exception("No se pudieron cruzar compradores con la propiedad %s", getattr(prop, "id", None))
        return []


# ---------------------------------------------------------------------------
# Lectura (página de compatibles y bloque del detalle)
# ---------------------------------------------------------------------------

def _matches_query(db: Session, prop, agent_id: Optional[int] = None):
    prop_id = getattr(prop, "id", prop)
    query = (
        db.query(PropertyBuyerMatch)
        .join(PropertyAlert, PropertyAlert.id == PropertyBuyerMatch.alert_id)
        .filter(PropertyBuyerMatch.property_id == prop_id)
    )
    if agent_id is not None:
        # El agente ve los compradores que lleva HOY (si la alerta se reasignó,
        # los ve el nuevo agente): son los que puede trabajar
        query = query.filter(PropertyAlert.agent_id == agent_id)
    return query


def matches_for_property(db: Session, prop, agent_id: Optional[int] = None) -> list:
    """Cruces de la propiedad, con alerta, comprador, perfil, agente, empresa y seguimientos
    cargados en una tanda. `agent_id`: solo las alertas que lleva ese agente.

    Orden: agente (nombre), comprador (nombre) e id.
    """
    rows = (
        _matches_query(db, prop, agent_id)
        .options(
            joinedload(PropertyBuyerMatch.alert).joinedload(PropertyAlert.buyer).joinedload(Buyer.search_criteria),
            joinedload(PropertyBuyerMatch.alert).joinedload(PropertyAlert.agent),
            joinedload(PropertyBuyerMatch.alert).joinedload(PropertyAlert.company),
            joinedload(PropertyBuyerMatch.alert).selectinload(PropertyAlert.follow_ups),
            joinedload(PropertyBuyerMatch.agent),
        )
        .all()
    )
    rows.sort(key=lambda m: (
        ((m.alert.agent.name if m.alert.agent else "") or "").lower(),
        buyer_name(m.alert).lower(),
        m.id,
    ))
    return rows


def matches_count_for_property(db: Session, prop, agent_id: Optional[int] = None) -> int:
    return _matches_query(db, prop, agent_id).count()


def notified_agents_count(db: Session, prop) -> int:
    """Agentes distintos avisados de esta propiedad («N agentes avisados» del admin)."""
    prop_id = getattr(prop, "id", prop)
    return (
        db.query(PropertyBuyerMatch.agent_id)
        .filter(PropertyBuyerMatch.property_id == prop_id, PropertyBuyerMatch.notified_at.isnot(None))
        .distinct()
        .count()
    )
