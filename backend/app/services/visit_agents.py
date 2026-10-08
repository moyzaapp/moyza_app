"""Agentes de una visita: quién la realizó y si fue acompañado.

Reglas (PLAN_VISITAS_AGENTES.md §2.3 y decisiones §4):

- `agent_id` (principal) es obligatorio y debe pertenecer a la empresa activa.
- Un usuario agente no puede elegir el principal: en el alta es él mismo y
  en la edición se conserva el que ya tenía la visita. Solo el admin lo elige.
- `companion_agent_id` es opcional, de la empresa activa y distinto del
  principal. Solo se lee si `visit_mode` es "acompanado".
- Una visita firmada o completada tiene los agentes fijados: no se lee el form.
"""
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
    fixed_agent_id=None,
):
    """Valida los agentes enviados en el form y devuelve (agent_id, companion_agent_id).

    - `current_agent`: ficha de agente del usuario logueado (o None).
    - `lookup_agent(agent_id)`: devuelve el agente si pertenece a la empresa
      activa, o None.
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
        if lookup_agent(companion_agent_id) is None:
            raise VisitAgentsError("El agente acompañante no pertenece a la empresa activa")

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

    return resolve_visit_agents(
        form,
        is_admin_user=bool(is_admin(user)),
        current_agent=get_agent_from_user(user, db),
        lookup_agent=lookup_agent,
        fixed_agent_id=visit.agent_id if visit is not None else None,
    )
