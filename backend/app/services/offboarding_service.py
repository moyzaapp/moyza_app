"""Baja lógica de usuarios y agentes (PLAN_BAJA_USUARIOS.md §5).

Reglas (decisiones §2):

- Nadie con historial se borra: "irse" y "volver" son dos estados de la
  misma ficha (`is_active` + `deactivated_at` en `users` y `agents`).
- Las propiedades vivas (`Activa`, `Reservada`, `Pausada`) del agente en
  cualquier empresa bloquean la baja: se reasignan desde Propiedades.
- Las alertas abiertas (pendientes o en proceso) se reasignan en la baja, por
  empresa, al agente activo que elija el admin, con la reasignación de
  `alert_assignment_service` (historial, seguimiento `REASIGNADA` y aviso).
- Reactivar devuelve el acceso y la ficha; lo reasignado no vuelve solo.
- Borrado físico solo sin historial (`has_history`).

Usuario y ficha de agente se unen por email, como `get_agent_from_user`.
"""
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from typing import Iterable
from typing import Optional
from urllib.parse import quote

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.constants import PropertyStatus
from app.models.agent import Agent
from app.models.agent_performance_report import AgentPerformanceReport
from app.models.agent_performance_target import AgentPerformanceTarget
from app.models.alert_assignment_log import AlertAssignmentLog
from app.models.alert_follow_up import AlertFollowUp
from app.models.buyer import Buyer
from app.models.buyer_search_criteria import BuyerSearchCriteria
from app.models.company import Company
from app.models.property import Property
from app.models.property_alert import PropertyAlert
from app.models.property_interaction import PropertyInteraction
from app.models.property_price_history import PropertyPriceHistory
from app.models.property_status_history import PropertyStatusHistory
from app.models.property_visit import PropertyVisit
from app.models.report import Report
from app.models.user import User
from app.services import alert_assignment_service
from app.services.alert_assignment_service import REASSIGNABLE_STATUSES
from app.services.alert_assignment_service import AlertAssignmentError
from app.services.company_scope import scope_active_agents

LIVE_PROPERTY_STATUSES = {PropertyStatus.ACTIVE, PropertyStatus.RESERVED, PropertyStatus.PAUSED}
OPEN_ALERT_STATUSES = REASSIGNABLE_STATUSES  # PENDING, IN_PROGRESS


class OffboardingError(Exception):
    """Error de la baja con mensaje listo para el flash."""


@dataclass
class CompanyPending:
    company: Company
    live_properties: int          # bloquean
    open_alerts: int              # se reasignan
    targets: list                 # agentes activos de esa empresa, sin el propio


@dataclass
class Reassignment:
    """Alertas de una empresa reasignadas en la baja (para el flash)."""
    company: Company
    agent: Agent
    count: int


@dataclass
class OffboardingSummary:
    user: Optional[User]
    agent: Optional[Agent]
    pending: list                  # CompanyPending, solo empresas del agente o con pendientes
    blocked: bool                  # any(live_properties > 0)
    has_history: bool              # para decidir si se puede borrar físicamente
    reassigned: list = field(default_factory=list)  # Reassignment, lo hecho por `deactivate`

    @property
    def name(self) -> str:
        if self.user is not None:
            return self.user.full_name or self.user.email
        if self.agent is not None:
            return self.agent.name
        return ""


# ---------------------------------------------------------------------------
# Usuario <-> ficha de agente (por email)
# ---------------------------------------------------------------------------

def find_agent(db: Session, user) -> Optional[Agent]:
    """Ficha de agente del usuario, por email (como `get_agent_from_user`)."""
    if user is None or not user.email:
        return None
    return db.query(Agent).filter(Agent.email == user.email).first()


def find_user(db: Session, agent) -> Optional[User]:
    """Usuario de una ficha de agente (mismo email sin distinguir mayúsculas), activo o no."""
    email = (getattr(agent, "email", None) or "").strip().lower()
    if not email:
        return None
    return (
        db.query(User)
        .filter(func.lower(User.email) == email)
        .order_by(User.id)
        .first()
    )


def user_ids_by_agent_email(db: Session, agents: Iterable[Agent]) -> dict:
    """{agent.email: user.id} de las fichas que tienen usuario (§7.2, listado de Agentes).

    Las claves son exactamente `agent.email` aunque el usuario tenga otras mayúsculas.
    """
    by_lower = {}
    for agent in agents:
        if agent.email:
            by_lower.setdefault(agent.email.strip().lower(), []).append(agent.email)
    if not by_lower:
        return {}
    rows = (
        db.query(func.lower(User.email), User.id)
        .filter(func.lower(User.email).in_(list(by_lower)))
        .order_by(User.id.desc())
        .all()
    )
    result = {}
    for lower_email, user_id in rows:  # el id más bajo gana: se escribe el último
        for email in by_lower.get(lower_email, []):
            result[email] = user_id
    return result


# ---------------------------------------------------------------------------
# Historial (borrado físico solo sin historial, §2-6)
# ---------------------------------------------------------------------------

# Columnas que apuntan al usuario. Además de las del plan (§5), las FK sin
# ON DELETE que harían fallar el borrado (historial de precio y de estado,
# objetivos creados).
_USER_COLUMNS = (
    PropertyAlert.created_by,
    AlertFollowUp.created_by,
    PropertyVisit.created_by,
    Buyer.created_by,
    PropertyInteraction.created_by,
    Report.uploaded_by,
    PropertyPriceHistory.created_by,
    PropertyStatusHistory.changed_by,
    AgentPerformanceTarget.created_by,
)

# Columnas que apuntan a la ficha de agente (§5, más los criterios de búsqueda
# de comprador, FK sin ON DELETE)
_AGENT_COLUMNS = (
    Property.agent_id,
    PropertyAlert.agent_id,
    AlertAssignmentLog.from_agent_id,
    AlertAssignmentLog.to_agent_id,
    PropertyVisit.agent_id,
    PropertyVisit.companion_agent_id,
    AgentPerformanceTarget.agent_id,
    AgentPerformanceReport.agent_id,
    BuyerSearchCriteria.agent_id,
)


def _ids_with_rows(db: Session, columns, ids: set) -> set:
    """Ids de `ids` que aparecen en alguna de las columnas (una consulta por columna)."""
    found = set()
    for column in columns:
        pending = ids - found
        if not pending:
            break
        found.update(
            value for (value,) in db.query(column).filter(column.in_(pending)).distinct()
        )
    return found


def users_with_history(db: Session, user_ids: Iterable[int]) -> set:
    """Ids de usuario con algo asociado (sin contar su ficha de agente)."""
    return _ids_with_rows(db, _USER_COLUMNS, {i for i in user_ids if i is not None})


def agents_with_history(db: Session, agent_ids: Iterable[int]) -> set:
    """Ids de ficha de agente con algo asociado."""
    return _ids_with_rows(db, _AGENT_COLUMNS, {i for i in agent_ids if i is not None})


def has_history(db: Session, user=None, agent=None) -> bool:
    """True si el usuario o su ficha tienen cualquier historial (EXISTS por tabla, §5).

    Con `user` y sin `agent` se mira también su ficha (por email).
    """
    if user is not None and agent is None:
        agent = find_agent(db, user)
    if user is not None and users_with_history(db, [user.id]):
        return True
    if agent is not None and agents_with_history(db, [agent.id]):
        return True
    return False


def history_by_user_id(db: Session, users: list) -> dict:
    """{user.id: bool} para el listado de Usuarios (§7.1); incluye la ficha de cada uno."""
    agents = user_agent_map(db, users)
    with_user = users_with_history(db, [u.id for u in users])
    with_agent = agents_with_history(db, [a.id for a in agents.values()])
    return {
        u.id: u.id in with_user or (u.id in agents and agents[u.id].id in with_agent)
        for u in users
    }


def history_by_agent_id(db: Session, agents: list) -> dict:
    """{agent.id: bool} para el listado de Agentes (§7.2)."""
    with_agent = agents_with_history(db, [a.id for a in agents])
    return {a.id: a.id in with_agent for a in agents}


def user_agent_map(db: Session, users: list) -> dict:
    """{user.id: Agent} de los usuarios con ficha (email exacto, como `find_agent`)."""
    emails = {u.email: u.id for u in users if u.email}
    if not emails:
        return {}
    agents = db.query(Agent).filter(Agent.email.in_(list(emails))).all()
    return {emails[a.email]: a for a in agents}


# ---------------------------------------------------------------------------
# Resumen de lo pendiente (§5, §6.1)
# ---------------------------------------------------------------------------

def _counts_by_company(query, company_column) -> dict:
    return dict(query.with_entities(company_column, func.count()).group_by(company_column).all())


def _targets(db: Session, company_id: int, agent_id: Optional[int]) -> list:
    query = scope_active_agents(db.query(Agent), company_id)
    if agent_id is not None:
        query = query.filter(Agent.id != agent_id)
    return query.order_by(Agent.name).all()


def _pending(db: Session, agent: Optional[Agent]) -> list:
    """Una entrada por empresa del agente o con propiedades vivas / alertas abiertas suyas."""
    if agent is None:
        return []

    live = _counts_by_company(
        db.query(Property).filter(
            Property.agent_id == agent.id,
            Property.status.in_(LIVE_PROPERTY_STATUSES),
        ),
        Property.company_id,
    )
    open_alerts = _counts_by_company(
        db.query(PropertyAlert).filter(
            PropertyAlert.agent_id == agent.id,
            PropertyAlert.status.in_(OPEN_ALERT_STATUSES),
        ),
        PropertyAlert.company_id,
    )

    company_ids = {c.id for c in agent.companies} | set(live) | set(open_alerts)
    company_ids.discard(None)
    companies = (
        db.query(Company).filter(Company.id.in_(company_ids)).order_by(Company.id).all()
        if company_ids else []
    )

    return [
        CompanyPending(
            company=company,
            live_properties=live.get(company.id, 0),
            open_alerts=open_alerts.get(company.id, 0),
            targets=_targets(db, company.id, agent.id),
        )
        for company in companies
    ]


def _summary(db: Session, user: Optional[User], agent: Optional[Agent]) -> OffboardingSummary:
    pending = _pending(db, agent)
    return OffboardingSummary(
        user=user,
        agent=agent,
        pending=pending,
        blocked=any(p.live_properties > 0 for p in pending),
        has_history=has_history(db, user=user, agent=agent) if (user or agent) else False,
    )


def summary_for_user(db: Session, user: User) -> OffboardingSummary:
    """Resumen de la baja de un usuario y de su ficha de agente (si la tiene)."""
    return _summary(db, user, find_agent(db, user))


def summary_for_agent(db: Session, agent: Agent) -> OffboardingSummary:
    """Resumen de la baja de una ficha de agente sin usuario (§2-7)."""
    return _summary(db, None, agent)


def properties_url(agent: Optional[Agent]) -> Optional[str]:
    """Listado de Propiedades buscando por el nombre del agente (cruza `Agent.name`).

    El listado no tiene filtro por agente y está acotado a la empresa activa.
    """
    if agent is None:
        return None
    return f"/properties?search={quote(agent.name or '')}"


def summary_to_dict(summary: OffboardingSummary) -> dict:
    """JSON del resumen para el modal de baja (§6.1)."""
    url = properties_url(summary.agent)
    return {
        "name": summary.name,
        "blocked": summary.blocked,
        "has_history": summary.has_history,
        "companies": [
            {
                "id": p.company.id,
                "code": p.company.code,
                "name": p.company.name,
                "live_properties": p.live_properties,
                "open_alerts": p.open_alerts,
                "properties_url": url,
                "targets": [{"id": a.id, "name": a.name} for a in p.targets],
            }
            for p in summary.pending
        ],
    }


def blocked_message(summary: OffboardingSummary) -> str:
    """'Tiene 3 propiedades activas en MOYZA. Reasígnalas desde Propiedades antes de dar de baja.'"""
    parts = []
    for p in summary.pending:
        if p.live_properties > 0:
            noun = "propiedad activa" if p.live_properties == 1 else "propiedades activas"
            parts.append(f"{p.live_properties} {noun} en {p.company.name}")
    return f"Tiene {' y '.join(parts)}. Reasígnalas desde Propiedades antes de dar de baja."


def deactivation_message(summary: OffboardingSummary) -> str:
    """Flash: 'Juan Pérez dado de baja. 5 compradores reasignados a Ana (MOYZA)'."""
    message = f"{summary.name} dado de baja."
    parts = []
    for r in summary.reassigned:
        noun = "comprador reasignado" if r.count == 1 else "compradores reasignados"
        parts.append(f"{r.count} {noun} a {r.agent.name} ({r.company.name})")
    if parts:
        message += " " + ", ".join(parts) + "."
    return message


# ---------------------------------------------------------------------------
# Baja y reactivación
# ---------------------------------------------------------------------------

def _to_int(value) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def deactivate(
    db: Session,
    *,
    user: Optional[User] = None,
    agent: Optional[Agent] = None,
    by_user,
    reassign_to: dict,
    reason: Optional[str] = None,
    now: Optional[datetime] = None,
) -> OffboardingSummary:
    """Da de baja al usuario (y su ficha) o a una ficha sin usuario (§5).

    `reassign_to`: {company_id: agent_id} para cada empresa con alertas
    abiertas. Reasigna con `alert_assignment_service` (solo `flush`) y hace
    un único `commit` al final; si algo falla, `rollback` y `OffboardingError`.
    """
    if user is None and agent is None:
        raise OffboardingError("Nada que dar de baja")

    if user is not None:
        if by_user is not None and by_user.id == user.id:
            raise OffboardingError("No puedes darte de baja a ti mismo")
        if user.is_active is False:
            raise OffboardingError(f"{user.full_name} ya está dado de baja")
        summary = summary_for_user(db, user)
    else:
        if find_user(db, agent) is not None:
            raise OffboardingError(
                f"{agent.name} tiene usuario: dale de baja desde Usuarios"
            )
        if agent.is_active is False:
            raise OffboardingError(f"{agent.name} ya está dado de baja")
        summary = summary_for_agent(db, agent)

    if summary.blocked:
        raise OffboardingError(blocked_message(summary))

    leaving = summary.agent
    reassign_to = {_to_int(k): _to_int(v) for k, v in (reassign_to or {}).items()}
    reason = alert_assignment_service.clean_reason(reason) or f"Baja de {summary.name}"
    now = now or datetime.utcnow()

    # Destinos validados antes de tocar nada
    plan = []
    for pending in summary.pending:
        if pending.open_alerts == 0:
            continue
        company = pending.company
        target_id = reassign_to.get(company.id)
        if target_id is None:
            raise OffboardingError(
                f"Elige a quién reasignar sus compradores abiertos de {company.name}"
            )
        target = (
            scope_active_agents(db.query(Agent), company.id)
            .filter(Agent.id == target_id, Agent.id != leaving.id)
            .first()
        )
        if target is None:
            raise OffboardingError(
                f"El agente elegido para {company.name} no es un agente activo de esa empresa"
            )
        plan.append((company, target))

    try:
        for company, target in plan:
            alerts = (
                db.query(PropertyAlert)
                .filter(
                    PropertyAlert.agent_id == leaving.id,
                    PropertyAlert.company_id == company.id,
                    PropertyAlert.status.in_(OPEN_ALERT_STATUSES),
                )
                .order_by(PropertyAlert.id)
                .all()
            )
            for alert in alerts:
                alert_assignment_service.validate_reassignment(alert, target, is_admin_user=True)
                alert_assignment_service.assign(
                    db, alert, target, by_user, reason, is_new=False, now=now,
                )
            if alerts:
                summary.reassigned.append(Reassignment(company=company, agent=target, count=len(alerts)))

        if summary.user is not None:
            summary.user.is_active = False
            summary.user.deactivated_at = now
        if leaving is not None:
            leaving.is_active = False
            leaving.deactivated_at = now

        db.commit()
    except AlertAssignmentError as exc:
        db.rollback()
        raise OffboardingError(str(exc)) from exc
    except Exception:
        db.rollback()
        raise

    return summary


def reactivate(db: Session, *, user: Optional[User] = None, agent: Optional[Agent] = None) -> None:
    """Devuelve el acceso y la ficha (§2-5). Lo reasignado en la baja no vuelve."""
    if user is None and agent is None:
        raise OffboardingError("Nada que reactivar")
    if user is not None:
        agent = agent or find_agent(db, user)
        user.is_active = True
        user.deactivated_at = None
    elif find_user(db, agent) is not None:
        raise OffboardingError(f"{agent.name} tiene usuario: reactívalo desde Usuarios")
    if agent is not None:
        agent.is_active = True
        agent.deactivated_at = None
    db.commit()
