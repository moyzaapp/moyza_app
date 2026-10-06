import os
import base64
import logging
from datetime import datetime

from fastapi import APIRouter
from fastapi import Request
from fastapi import Depends
from fastapi import Form
from fastapi import File
from fastapi import UploadFile

from fastapi.responses import HTMLResponse
from fastapi.responses import RedirectResponse

from app.web.template_env import templates

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.deps import get_db

from app.models.agent import Agent
from app.models.property import Property

from app.web.dependencies.auth import is_admin, get_agent_from_user, deny_if_not_admin
from app.web.dependencies.company import get_active_company
from app.services.company_scope import (
    scope_agents,
    scope_properties,
    get_agent_in_company,
    add_to_company,
    remove_from_company,
)
from app.services.company_service import (
    list_active_companies,
    resolve_companies,
    companies_label,
    company_ids_from_form,
)
from app.web.utils.flash import set_flash


router = APIRouter()
logger = logging.getLogger(__name__)



def _clean(value):
    """Normaliza un campo opcional de formulario: '' o espacios -> None."""
    if value is None:
        return None

    value = value.strip()

    return value or None


def _can_edit_agent(request: Request, agent: Agent, db: Session) -> bool:
    """El admin puede editar cualquier agente; el agente solo su propio perfil."""
    current_user = getattr(request.state, "user", None)

    if is_admin(current_user):
        return True

    own_agent = get_agent_from_user(current_user, db)

    return bool(own_agent and own_agent.id == agent.id)


@router.get("/agents", response_class=HTMLResponse)
async def agents_page(
    request: Request,
    db: Session = Depends(get_db)
):
    error = request.query_params.get("error")

    current_user = request.state.user
    company = get_active_company(request)

    search = (request.query_params.get("search") or "").strip()

    # Solo el admin ve el listado completo, así que solo él necesita buscador
    # y es el único que puede crear o eliminar agentes
    can_manage = is_admin(current_user)

    # Si es admin, mostrar todos los agentes de la empresa activa
    # Si es agente, mostrar solo su propio perfil
    if can_manage:

        base_query = scope_agents(db.query(Agent), company.id)

        if search:
            pattern = f"%{search}%"
            base_query = base_query.filter(
                or_(
                    Agent.name.ilike(pattern),
                    Agent.email.ilike(pattern),
                    Agent.dni.ilike(pattern),
                    Agent.phone.ilike(pattern),
                    Agent.zone.ilike(pattern),
                    Agent.company.ilike(pattern)
                )
            )

        agents = base_query.order_by(Agent.name).all()

    else:
        agent = get_agent_from_user(current_user, db)
        agents = [agent] if agent else []

    return templates.TemplateResponse(
        request=request,
        name="agents/home.html",
        context={
            "request": request,
            "agents": agents,
            "current_user": current_user,
            "error": error,
            "search": search,
            "can_manage": can_manage,
            # Empresas asignables en el formulario de agente
            "all_companies": list_active_companies(db),
        }
    )


@router.post("/agents/create")
async def create_agent(
        request: Request,
        name: str = Form(None),
        email: str = Form(None),
        dni: str = Form(None),
        phone: str = Form(None),
        zone: str = Form(None),
        company: str = Form(None),
        db: Session = Depends(get_db)
    ):

    # Solo el admin puede crear agentes
    denied = deny_if_not_admin(request, "/agents")

    if denied:
        return denied

    active_company = get_active_company(request)

    # Empresas marcadas en el formulario; sin ninguna, la empresa activa
    form = await request.form()
    selected_companies = resolve_companies(
        db,
        company_ids_from_form(form),
        fallback=[active_company]
    )

    # Solo el nombre es obligatorio; el resto es opcional.
    # Se normaliza aquí para no depender de la validación de FastAPI, que
    # devolvería un 422 sin plantilla (la página "se caía").
    name = (name or "").strip()
    email = _clean(email)

    if not name:
        return RedirectResponse(
            url="/agents?error=missing_fields",
            status_code=302
        )

    # El correo solo debe ser único cuando se indica
    if email:

        existing_agent = db.query(Agent).filter(
            Agent.email == email
        ).first()

        if existing_agent:
            # Un agente puede trabajar en ambas empresas: si ya existe en la
            # otra, se le añade a las marcadas en vez de duplicar la ficha.
            try:
                added = [
                    c.name for c in selected_companies
                    if add_to_company(db, existing_agent, c.id)
                ]
                if added:
                    existing_agent.company = companies_label(existing_agent.companies)
                    db.commit()
                    response = RedirectResponse(url="/agents", status_code=302)
                    set_flash(
                        response,
                        "success",
                        f"{existing_agent.name} ya existía como agente y se ha añadido a {', '.join(added)}."
                    )
                    return response
            except Exception:
                db.rollback()
                logger.exception("Error añadiendo agente existente a empresa: email=%s", email)
                return RedirectResponse(url="/agents?error=save_failed", status_code=302)

            return RedirectResponse(
                url="/agents?error=email_exists",
                status_code=302
            )

    try:
        agent = Agent(
            name=name,
            email=email,
            dni=_clean(dni),
            phone=_clean(phone),
            zone=_clean(zone),
            company=companies_label(selected_companies)
        )
        agent.companies = list(selected_companies)

        db.add(agent)

        db.commit()

    except Exception:
        db.rollback()
        logger.exception("Error creando agente: email=%s", email)
        return RedirectResponse(
            url="/agents?error=save_failed",
            status_code=302
        )

    return RedirectResponse(
        url="/agents",
        status_code=302
    )


@router.post("/agents/update")
async def update_agent(
    request: Request,
    agent_id: str = Form(None),
    name: str = Form(None),
    email: str = Form(None),
    dni: str = Form(None),
    phone: str = Form(None),
    zone: str = Form(None),
    company: str = Form(None),
    db: Session = Depends(get_db)
):

    try:
        agent_id = int(agent_id)
    except (TypeError, ValueError):
        return RedirectResponse(
            url="/agents?error=missing_fields",
            status_code=302
        )

    name = (name or "").strip()
    email = _clean(email)

    if not name:
        return RedirectResponse(
            url="/agents?error=missing_fields",
            status_code=302
        )

    # Solo se pueden editar agentes de la empresa activa
    agent = get_agent_in_company(db, agent_id, get_active_company(request).id)

    if not agent:
        return RedirectResponse(
            url="/agents?error=agent_not_found",
            status_code=302
        )

    # El agente solo puede editar su propio perfil; el admin, cualquiera
    if not _can_edit_agent(request, agent, db):
        return deny_if_not_admin(request, "/agents")

    # El correo debe seguir siendo único entre agentes, cuando se indica
    if email:

        email_owner = db.query(Agent).filter(
            Agent.email == email,
            Agent.id != agent_id
        ).first()

        if email_owner:
            return RedirectResponse(
                url="/agents?error=email_exists",
                status_code=302
            )

    try:
        agent.name = name
        agent.email = email
        agent.dni = _clean(dni)
        agent.phone = _clean(phone)
        agent.zone = _clean(zone)

        # Solo el admin puede cambiar las empresas del agente; un agente que
        # edita su propio perfil no puede darse acceso a otra empresa.
        if is_admin(getattr(request.state, "user", None)):
            form = await request.form()
            agent.companies = list(resolve_companies(
                db,
                company_ids_from_form(form),
                fallback=list(agent.companies)
            ))
        agent.company = companies_label(agent.companies)

        db.commit()

    except Exception:
        db.rollback()
        logger.exception("Error actualizando agente: agent_id=%s", agent_id)
        return RedirectResponse(
            url="/agents?error=save_failed",
            status_code=302
        )

    return RedirectResponse(
        url="/agents",
        status_code=302
    )


@router.post("/agents/delete/{agent_id}")
async def delete_agent(
    agent_id: int,
    request: Request,
    db: Session = Depends(get_db)
):

    # Solo el admin puede eliminar agentes
    denied = deny_if_not_admin(request, "/agents")

    if denied:
        return denied

    active_company = get_active_company(request)

    agent = get_agent_in_company(db, agent_id, active_company.id)

    if not agent:
        return RedirectResponse(
            url="/agents?error=agent_not_found",
            status_code=302
        )

    # No se puede dar de baja si tiene propiedades en la empresa activa
    properties = scope_properties(
        db.query(Property).filter(Property.agent_id == agent_id),
        active_company.id
    ).count()

    if properties > 0:
        return RedirectResponse(
            url="/agents?error=in_use",
            status_code=302
        )

    # Si el agente también trabaja en la otra empresa, solo se le quita de
    # esta; la ficha se elimina únicamente cuando no queda en ninguna.
    if len(agent.companies) > 1:
        remove_from_company(db, agent, active_company.id)
        db.commit()

        response = RedirectResponse(url="/agents", status_code=302)
        set_flash(
            response,
            "success",
            f"{agent.name} se ha quitado de {active_company.name}. Sigue activo en sus otras empresas."
        )
        return response

    db.delete(agent)

    db.commit()

    return RedirectResponse(
        url="/agents",
        status_code=302
    )


@router.post("/agents/{agent_id}/upload-signature")
async def upload_agent_signature(
    agent_id: int,
    request: Request,
    signature_data: str = Form(...),
    db: Session = Depends(get_db)
):
    """
    Endpoint para subir la firma del agente.
    signature_data viene como base64 string desde el canvas del frontend
    """
    agent = get_agent_in_company(db, agent_id, get_active_company(request).id)

    if not agent:
        return RedirectResponse(
            url="/agents?error=agent_not_found",
            status_code=302
        )

    # El agente solo puede firmar su propio perfil; el admin, cualquiera
    if not _can_edit_agent(request, agent, db):
        return deny_if_not_admin(request, "/agents")

    # Crear directorio de firmas si no existe
    signatures_dir = "storage/signatures/agents"
    os.makedirs(signatures_dir, exist_ok=True)

    # Decodificar base64
    if signature_data.startswith("data:image/png;base64,"):
        signature_data = signature_data.replace("data:image/png;base64,", "")

    signature_bytes = base64.b64decode(signature_data)

    # Generar nombre de archivo único
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"agent_{agent_id}_{timestamp}.png"
    filepath = os.path.join(signatures_dir, filename)

    # Guardar archivo
    with open(filepath, "wb") as f:
        f.write(signature_bytes)

    # Actualizar agente
    agent.signature_filename = filename
    agent.signature_filepath = filepath
    agent.signature_uploaded_at = datetime.utcnow()

    db.commit()

    return RedirectResponse(
        url="/agents",
        status_code=302
    )