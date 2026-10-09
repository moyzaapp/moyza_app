"""Agentes de una visita: quién la realizó y si fue acompañado.

Reglas (PLAN_VISITAS_AGENTES.md §2.3 y decisiones §4):

- `agent_id` (principal) es obligatorio y debe pertenecer a la empresa activa.
- Un usuario agente no puede elegir el principal: en el alta es él mismo y
  en la edición se conserva el que ya tenía la visita. Solo el admin lo elige.
- `companion_agent_id` es opcional, distinto del principal y puede ser de
  CUALQUIER empresa activa (un agente de MOES puede acompañar en una visita
  de MOYZA y al revés). Solo se lee si `visit_mode` es "acompanado".
- Una visita firmada o completada tiene los agentes fijados: no se lee el form.
"""
from sqlalchemy.orm import Session
from sqlalchemy.orm import selectinload

from app.models.agent import Agent
from app.models.company import Company
from app.services.company_scope import get_agent_in_company
from app.web.dependencies.auth import get_agent_from_user
from app.web.dependencies.auth import is_admin
from app.web.dependencies.company import get_active_company


VISIT_MODE_SOLO = "solo"
VISIT_MODE_ACCOMPANIED = "acompanado"

# Estados en los que los agentes ya no se pueden cambiar (decisión 9)
LOCKED_VISIT_STATUSES = ("signed", "completed")


class VisitAgentsError(ValueError):
    """Error de validación con mensaje listo para el flash."""


def visit_agents_locked(visit) -> bool:
    return visit is not None and visit.visit_status in LOCKED_VISIT_STATUSES


def _to_int(value):
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def resolve_visit_agents(
    form,
    *,
    is_admin_user: bool,
    current_agent,
    lookup_agent,
    lookup_any_agent,
    fixed_agent_id=None,
):
    """Valida los agentes enviados en el form y devuelve (agent_id, companion_agent_id).

    - `current_agent`: ficha de agente del usuario logueado (o None).
    - `lookup_agent(agent_id)`: devuelve el agente si pertenece a la empresa
      activa, o None. Valida al principal.
    - `lookup_any_agent(agent_id)`: devuelve el agente si existe en alguna
      empresa activa, sin filtrar por la activa, o None. Valida al acompañante.
    - `fixed_agent_id`: principal que un usuario no admin no puede cambiar
      (el de la visita en edición). Si es None, el principal es su agente.

    Lanza VisitAgentsError con el mensaje para el usuario.
    """
    if is_admin_user:
        agent_id = _to_int(form.get("agent_id"))
        if agent_id is None:
            raise VisitAgentsError("Selecciona el agente que realizó la visita")
    elif fixed_agent_id is not None:
        # Edición por un agente: el principal no cambia, venga lo que venga
        agent_id = fixed_agent_id
    else:
        if current_agent is None:
            raise VisitAgentsError(
                "Tu usuario no está vinculado a una ficha de agente; no puedes registrar visitas"
            )
        # Se ignora cualquier agent_id del form: nadie registra a nombre de otro
        agent_id = current_agent.id

    if lookup_agent(agent_id) is None:
        raise VisitAgentsError("El agente de la visita no pertenece a la empresa activa")

    companion_agent_id = None
    if (form.get("visit_mode") or VISIT_MODE_SOLO) == VISIT_MODE_ACCOMPANIED:
        companion_agent_id = _to_int(form.get("companion_agent_id"))
        if companion_agent_id is None:
            raise VisitAgentsError("Selecciona el agente acompañante")
        if companion_agent_id == agent_id:
            raise VisitAgentsError("El agente acompañante debe ser distinto del que realizó la visita")
        if lookup_any_agent(companion_agent_id) is None:
            raise VisitAgentsError("El agente acompañante no existe o ya no pertenece a ninguna empresa")

    return agent_id, companion_agent_id


def parse_visit_agents(form, request, db, property_item, visit=None, locked=False):
    """Agentes de la visita a partir del form, con el contexto de la petición.

    `property_item` se recibe para mantener la firma del plan y por si la
    validación necesita la propiedad; la empresa se toma de la activa, que
    ya coincide con la de la propiedad (se carga con get_property_in_company).
    Si `locked`, devuelve los agentes actuales de la visita sin leer el form.
    """
    if locked and visit is not None:
        return visit.agent_id, visit.companion_agent_id

    user = request.state.user
    company_id = get_active_company(request).id

    def lookup_agent(agent_id):
        return get_agent_in_company(db, agent_id, company_id)

    def lookup_any_agent(agent_id):
        return get_agent_in_any_company(db, agent_id)

    return resolve_visit_agents(
        form,
        is_admin_user=bool(is_admin(user)),
        current_agent=get_agent_from_user(user, db),
        lookup_agent=lookup_agent,
        lookup_any_agent=lookup_any_agent,
        fixed_agent_id=visit.agent_id if visit is not None else None,
    )


# ---------------------------------------------------------------------------
# Acompañante de cualquier empresa
# ---------------------------------------------------------------------------

def get_agent_in_any_company(db: Session, agent_id: int):
    """Agente que pertenece al menos a una empresa activa, sin mirar la activa."""
    return (
        db.query(Agent)
        .filter(Agent.id == agent_id, Agent.companies.any(Company.is_active.is_(True)))
        .first()
    )


def companion_agent_groups(db: Session, active_company_id: int) -> list[dict]:
    """Agentes de todas las empresas activas para el select de acompañante.

    Cada agente aparece una sola vez, agrupado por el conjunto de empresas a
    las que pertenece: "MOYZA", "MOES PREMIUM" o "MOYZA, MOES PREMIUM". Así
    no hay dos opciones con el mismo valor y se ve de un vistazo de qué
    empresa es cada uno. Orden: primero los grupos que incluyen la empresa
    activa (solo ella y luego compartidos) y después el resto.

    Devuelve [{"label": str, "agents": [Agent, ...]}, ...].
    """
    companies = (
        db.query(Company)
        .filter(Company.is_active.is_(True))
        .order_by(Company.id)
        .all()
    )
    names = {c.id: c.name for c in companies}

    agents = (
        db.query(Agent)
        .options(selectinload(Agent.companies))
        .filter(Agent.companies.any(Company.is_active.is_(True)))
        .order_by(Agent.name)
        .all()
    )

    groups: dict[tuple, list] = {}
    for agent in agents:
        key = tuple(sorted(c.id for c in agent.companies if c.id in names))
        groups.setdefault(key, []).append(agent)

    ordered = sorted(groups, key=lambda ids: (active_company_id not in ids, len(ids), ids))
    return [
        {"label": ", ".join(names[i] for i in ids), "agents": groups[ids]}
        for ids in ordered
    ]
