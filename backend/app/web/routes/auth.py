from fastapi import APIRouter
from fastapi import BackgroundTasks
from fastapi import Request
from fastapi import Depends
from fastapi import Form
from fastapi import HTTPException

from pydantic import ValidationError

from sqlalchemy.orm import Session

from fastapi.responses import HTMLResponse
from fastapi.responses import RedirectResponse

from app.web.template_env import templates

from app.db.deps import get_db
from app.models.user import User
from app.models.role import Role
from app.models.permission import Permission

from app.services.auth_service import authenticate_user
from app.core.security import create_access_token
from app.services.user_service import (
    create_user,
    delete_user,
    update_user,
    change_user_password
)
from app.services.user_email_service import send_password_changed_email
from app.schemas.user import UserCreate, UserUpdate
from app.web.utils.flash import set_flash

router = APIRouter()



@router.get("/", response_class=HTMLResponse)
async def login_page(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="auth/login.html",
        context={
            "request": request
        }
    )


@router.get("/auth", response_class=HTMLResponse)
async def auth_page(
    request: Request,
    db: Session = Depends(get_db)
):
    from app.web.dependencies.auth import require_admin_role

    # Validar que solo admin pueda acceder
    admin_user = require_admin_role(request, db)
    if isinstance(admin_user, RedirectResponse):
        return admin_user

    from app.services.company_service import list_active_companies

    users = db.query(User).order_by(User.full_name).all()

    roles = db.query(Role).all()

    permissions = db.query(Permission).all()

    current_user = request.state.user

    return templates.TemplateResponse(
        request=request,
        name="auth/home.html",
        context={
            "request": request,
            "users": users,
            "roles": roles,
            "permissions": permissions,
            "current_user": current_user,
            # Empresas asignables en los formularios de usuario
            "all_companies": list_active_companies(db),
        }
    )


from app.services.company_service import company_ids_from_form as _company_ids_from_form



@router.post("/login")
async def login(
    request: Request,
    username: str = Form(None),
    password: str = Form(None),
    db: Session = Depends(get_db)):

    # Limpiar espacios del email antes de validar o autenticar
    if username:
        username = username.strip()

    # Validación amigable
    if not username or not password:

        return templates.TemplateResponse(
            request=request,
            name="auth/login.html",
            context={
                "request": request,
                "error": "Todos los campos son obligatorios"
            }
        )

    user = authenticate_user(
        db,
        username,
        password
    )

    if not user:

        return templates.TemplateResponse(
            request=request,
            name="auth/login.html",
            context={
                "request": request,
                "error": "Credenciales inválidas"
            }
        )

    token = create_access_token(
        {"sub": user.email}
    )

    response = RedirectResponse(
        url="/dashboard",
        status_code=302
    )

    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=False,
        samesite="lax"
    )

    return response


@router.get("/logout")
async def logout():

    response = RedirectResponse(
        url="/",
        status_code=302
    )

    response.delete_cookie("access_token")

    return response


@router.post("/auth/users/create")
async def create_user_endpoint(
    request: Request,
    background_tasks: BackgroundTasks,
    email: str = Form(...),
    full_name: str = Form(...),
    password: str = Form(...),
    role_id: int = Form(...),
    phone: str = Form(None),
    company: str = Form(None),
    db: Session = Depends(get_db)
):
    from app.web.dependencies.auth import require_admin_role

    # Validar que solo admin pueda crear usuarios
    admin_user = require_admin_role(request, db)
    if isinstance(admin_user, RedirectResponse):
        return admin_user

    response = RedirectResponse(url="/auth", status_code=303)

    form = await request.form()

    try:
        user_data = UserCreate(
            email=email,
            full_name=full_name,
            password=password,
            role_id=role_id,
            phone=phone,
            company=company,
            company_ids=_company_ids_from_form(form),
        )

        # El correo de bienvenida lleva la marca de la empresa activa del admin
        active_company = getattr(request.state, "company", None)
        create_user(
            db,
            user_data,
            background_tasks,
            company_name=active_company.name if active_company else None,
        )
        set_flash(response, "success", "Usuario creado correctamente. Se envió el correo de bienvenida.")

    except ValidationError as e:
        # Primer mensaje de validación (ej. teléfono con formato no válido)
        set_flash(response, "error", e.errors()[0]["msg"].replace("Value error, ", ""))

    except HTTPException as e:
        set_flash(response, "error", e.detail)

    return response


@router.post("/auth/users/update")
async def update_user_endpoint(
    request: Request,
    user_id: int = Form(...),
    full_name: str = Form(...),
    role_id: int = Form(...),
    phone: str = Form(None),
    company: str = Form(None),
    db: Session = Depends(get_db)
):
    from app.web.dependencies.auth import require_admin_role

    # Validar que solo admin pueda editar usuarios
    admin_user = require_admin_role(request, db)
    if isinstance(admin_user, RedirectResponse):
        return admin_user

    response = RedirectResponse(url="/auth", status_code=303)

    form = await request.form()

    try:
        user_data = UserUpdate(
            full_name=full_name,
            role_id=role_id,
            phone=phone,
            company=company,
            company_ids=_company_ids_from_form(form),
        )

        update_user(db, user_id, user_data)
        set_flash(response, "success", "Usuario actualizado correctamente")

    except ValidationError as e:
        set_flash(response, "error", e.errors()[0]["msg"].replace("Value error, ", ""))

    except HTTPException as e:
        set_flash(response, "error", e.detail)

    return response


@router.post("/auth/users/password")
async def change_password_endpoint(
    request: Request,
    background_tasks: BackgroundTasks,
    user_id: int = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    db: Session = Depends(get_db)
):
    from app.web.dependencies.auth import require_admin_role

    # Validar que solo admin pueda cambiar contraseñas
    admin_user = require_admin_role(request, db)
    if isinstance(admin_user, RedirectResponse):
        return admin_user

    response = RedirectResponse(url="/auth", status_code=303)

    if password != password_confirm:
        set_flash(response, "error", "Las contraseñas no coinciden")
        return response

    try:
        user = change_user_password(db, user_id, password)

        active_company = getattr(request.state, "company", None)

        background_tasks.add_task(
            send_password_changed_email,
            email=user.email,
            full_name=user.full_name,
            password=password,
            company_name=active_company.name if active_company else None,
        )

        set_flash(
            response,
            "success",
            f"Contraseña de {user.full_name} actualizada. Se envió el correo de aviso."
        )

    except HTTPException as e:
        set_flash(response, "error", e.detail)

    return response


@router.post("/auth/users/delete/{user_id}")
async def delete_user_endpoint(
    request: Request,
    user_id: int,
    db: Session = Depends(get_db)
):
    from app.web.dependencies.auth import require_admin_role

    # Validar que solo admin pueda eliminar usuarios
    admin_user = require_admin_role(request, db)
    if isinstance(admin_user, RedirectResponse):
        return admin_user

    response = RedirectResponse(url="/auth", status_code=303)

    try:
        # No permitir que el admin se elimine a sí mismo
        if admin_user.id == user_id:
            set_flash(response, "error", "No puedes eliminar tu propio usuario")
            return response

        delete_user(db, user_id)
        set_flash(response, "success", "Usuario eliminado correctamente")

    except HTTPException as e:
        set_flash(response, "error", e.detail)

    return response