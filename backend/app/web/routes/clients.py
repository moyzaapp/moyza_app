from app.web.dependencies.auth import get_current_web_user
from app.web.dependencies.auth import is_admin
from app.web.dependencies.auth import deny_if_not_admin
from app.web.dependencies.auth import get_agent_from_user
from app.models.user import User
from app.models.client import Client
from app.models.property import Property
from fastapi import APIRouter
from fastapi import Request
from fastapi import Depends
from sqlalchemy import or_
from sqlalchemy.orm import Session
from fastapi.responses import HTMLResponse
from app.web.template_env import templates
from app.db.deps import get_db
from fastapi import Form
from fastapi.responses import RedirectResponse

from app.web.dependencies.company import get_active_company
from app.web.utils.flash import set_flash
from app.services.company_scope import (
    scope_clients,
    scope_properties,
    get_client_in_company,
    add_to_company,
    remove_from_company,
)

router = APIRouter()



@router.get("/clients", response_class=HTMLResponse)
async def clients_page(request: Request, db: Session = Depends(get_db)):

    current_user = request.state.user
    company = get_active_company(request)

    # Solo clientes de la empresa activa
    base_query = scope_clients(db.query(Client), company.id)

    # Agentes ven solo clientes cuyas propiedades tienen asignadas
    if not is_admin(current_user):
        agent = get_agent_from_user(current_user, db)
        if agent:
            client_ids = (
                scope_properties(db.query(Property.client_id), company.id)
                .filter(
                    Property.agent_id == agent.id,
                    Property.client_id.isnot(None)
                )
                .distinct()
                .subquery()
            )
            base_query = base_query.filter(Client.id.in_(client_ids))
        else:
            base_query = base_query.filter(Client.id == -1)

    search = (request.query_params.get("search") or "").strip()

    if search:
        base_query = base_query.filter(
            or_(
                Client.name.ilike(f"%{search}%"),
                Client.email.ilike(f"%{search}%"),
                Client.phone.ilike(f"%{search}%")
            )
        )

    clients = base_query.order_by(Client.name).all()

    error = request.query_params.get("error")

    # Solo el admin puede crear, editar o eliminar clientes
    can_manage = is_admin(current_user)

    return templates.TemplateResponse(
        request=request,
        name="clients/home.html",
        context={
            "request": request,
            "clients": clients,
            "current_user": current_user,
            "error": error,
            "search": search,
            "can_manage": can_manage
        }
    )

@router.post("/clients/create")
async def create_client(
        request: Request,
        name: str = Form(...),
        phone: str = Form(...),
        email: str = Form(None),
        db: Session = Depends(get_db)
    ):

    # Solo el admin puede crear clientes
    denied = deny_if_not_admin(request, "/clients")

    if denied:
        return denied

    active_company = get_active_company(request)

    # El correo es opcional: una cadena vacía se guarda como NULL
    email = (email or "").strip() or None

    if email:

        existing_client = db.query(Client).filter(
            Client.email == email
        ).first()

        if existing_client:
            # Un cliente puede tener inmuebles en ambas empresas: si ya existe
            # en la otra, se le añade a la activa en vez de duplicar la ficha.
            if add_to_company(db, existing_client, active_company.id):
                db.commit()
                response = RedirectResponse(url="/clients", status_code=302)
                set_flash(
                    response,
                    "success",
                    f"{existing_client.name} ya existía como cliente y se ha añadido a {active_company.name}."
                )
                return response

            return RedirectResponse(
                url="/clients?error=email_exists",
                status_code=302
            )

    client = Client(
        name=name,
        email=email,
        phone=phone,
        status="Activo"
    )

    db.add(client)
    add_to_company(db, client, active_company.id)

    db.commit()

    return RedirectResponse(
        url="/clients",
        status_code=302
    )

@router.post("/clients/update")
async def update_client(
        request: Request,
        client_id: int = Form(...),
        name: str = Form(...),
        phone: str = Form(...),
        email: str = Form(None),
        db: Session = Depends(get_db)
    ):

    # Solo el admin puede editar clientes
    denied = deny_if_not_admin(request, "/clients")

    if denied:
        return denied

    # El correo es opcional: una cadena vacía se guarda como NULL
    email = (email or "").strip() or None

    # Solo se pueden editar clientes de la empresa activa
    client = get_client_in_company(db, client_id, get_active_company(request).id)

    if client:

        if email:

            existing_client = db.query(Client).filter(
                Client.email == email,
                Client.id != client_id
            ).first()

            if existing_client:
                return RedirectResponse(
                    url="/clients?error=email_exists",
                    status_code=302
                )

        client.name = name
        client.email = email
        client.phone = phone

        db.commit()

    return RedirectResponse(
        url="/clients",
        status_code=302
    )

@router.post("/clients/delete/{client_id}")
async def delete_client(
        client_id: int,
        request: Request,
        db: Session = Depends(get_db)
    ):

    # Solo el admin puede eliminar clientes
    denied = deny_if_not_admin(request, "/clients")

    if denied:
        return denied

    active_company = get_active_company(request)

    client = get_client_in_company(db, client_id, active_company.id)

    if not client:
        return RedirectResponse(
            url="/clients",
            status_code=302
        )

    # No se puede dar de baja si tiene propiedades en la empresa activa
    properties = scope_properties(
        db.query(Property).filter(Property.client_id == client_id),
        active_company.id
    ).count()

    if properties > 0:
        return RedirectResponse(
            url="/clients?error=in_use",
            status_code=302
        )

    # Si el cliente también está en la otra empresa, solo se le quita de
    # esta; la ficha se elimina únicamente cuando no queda en ninguna.
    if len(client.companies) > 1:
        remove_from_company(db, client, active_company.id)
        db.commit()

        response = RedirectResponse(url="/clients", status_code=302)
        set_flash(
            response,
            "success",
            f"{client.name} se ha quitado de {active_company.name}. Sigue activo en sus otras empresas."
        )
        return response

    db.delete(client)

    db.commit()

    return RedirectResponse(
        url="/clients",
        status_code=302
    )