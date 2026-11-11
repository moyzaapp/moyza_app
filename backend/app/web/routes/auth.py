from fastapi import APIRouter
from fastapi import BackgroundTasks
from fastapi import Request
from fastapi import Depends
from fastapi import Form
from fastapi import HTTPException

from pydantic import ValidationError

from sqlalchemy.orm import Session

from fastapi.responses import HTMLResponse
from fastapi.responses import JSONResponse
from fastapi.responses import RedirectResponse

from app.web.template_env import templates

from app.db.deps import get_db
from app.models.user import User
from app.models.role import Role
from app.models.permission import Permission

from app.services.auth_service import INACTIVE
from app.services.auth_service import authenticate_user
from app.core.security import create_access_token
from app.services.user_service import (
    create_user,
    delete_user,
    update_user,
    change_user_password
)
from app.services.user_email_service import send_password_changed_email
from app.services import offboarding_service
from app.services.offboarding_service import OffboardingError
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

    # Los dados de baja no se ven por defecto: solo con ?baja=1 (opción 1 acordada
    # el 2026-11-10 sobre PLAN_BAJA_USUARIOS.md). Se cuentan para el enlace.
    show_inactive = request.query_params.get("baja") == "1"

    all_users = db.query(User).order_by(User.full_name).all()
    inactive_users = [u for u in all_users if u.is_active is False]
    users = inactive_users if show_inactive else [u for u in all_users if u.is_active is not False]

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
            "show_inactive": show_inactive,
            "inactive_count": len(inactive_users),
            # Eliminar solo sin historial (PLAN_BAJA_USUARIOS.md §7.1)
            "history_by_user_id": offboarding_service.history_by_user_id(db, users),
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

    if user is INACTIVE:

        return templates.TemplateResponse(
            request=request,
            name="auth/login.html",
            context={
                "request": request,
                "error": "Tu usuario está dado de baja. Contacta con un administrador."
            }
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

    # Marca de "acabo de iniciar sesión": el Inicio la lee desde JS para abrir
    # el aviso de compradores sin atender una vez por sesión, y la borra.
    # No es httponly a propósito (la consume el navegador), caduca en 2 minutos.
    response.set_cookie(
        key="moyza_welcome",
        value="1",
        max_age=120,
        httponly=False,
        secure=False,
        samesite="lax",
        path="/",
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


# ---------------------------------------------------------------------------
# Baja lógica (PLAN_BAJA_USUARIOS.md §6)
# ---------------------------------------------------------------------------

def reassign_to_from_form(form) -> dict:
    """{company_id: agent_id} de los campos `reassign_to_<company_id>` del modal de baja."""
    prefix = "reassign_to_"
    result = {}
    for key, value in form.items():
        if not key.startswith(prefix):
            continue
        try:
            company_id = int(key[len(prefix):])
        except ValueError:
            continue
        result[company_id] = value
    return result


def json_admin_denied(request: Request):
    """403 JSON si quien pide no es admin; None si puede seguir."""
    from app.web.dependencies.auth import is_admin

    if not is_admin(getattr(request.state, "user", None)):
        return JSONResponse(status_code=403, content={"detail": "Solo un administrador puede dar de baja"})
    return None


@router.get("/auth/users/{user_id}/offboarding")
async def user_offboarding_summary(
    request: Request,
    user_id: int,
    db: Session = Depends(get_db)
):
    """JSON del modal de baja (§6.1)."""
    denied = json_admin_denied(request)
    if denied:
        return denied

    user = db.get(User, user_id)
    if user is None:
        return JSONResponse(status_code=404, content={"detail": "Usuario no encontrado"})

    summary = offboarding_service.summary_for_user(db, user)
    return JSONResponse(content=offboarding_service.summary_to_dict(summary))


@router.post("/auth/users/{user_id}/deactivate")
async def deactivate_user_endpoint(
    request: Request,
    user_id: int,
    db: Session = Depends(get_db)
):
    """Da de baja al usuario y a su ficha, reasignando sus alertas abiertas (§5)."""
    from app.web.dependencies.auth import require_admin_role

    admin_user = require_admin_role(request, db)
    if isinstance(admin_user, RedirectResponse):
        return admin_user

    response = RedirectResponse(url="/auth", status_code=303)

    user = db.get(User, user_id)
    if user is None:
        set_flash(response, "error", "Usuario no encontrado")
        return response

    form = await request.form()

    try:
        summary = offboarding_service.deactivate(
            db,
            user=user,
            by_user=admin_user,
            reassign_to=reassign_to_from_form(form),
            reason=form.get("reason"),
        )
        set_flash(response, "success", offboarding_service.deactivation_message(summary))

    except OffboardingError as e:
        set_flash(response, "error", str(e))

    return response


@router.post("/auth/users/{user_id}/reactivate")
async def reactivate_user_endpoint(
    request: Request,
    user_id: int,
    db: Session = Depends(get_db)
):
    """Reactiva al usuario y su ficha (§2-5)."""
    from app.web.dependencies.auth import require_admin_role

    admin_user = require_admin_role(request, db)
    if isinstance(admin_user, RedirectResponse):
        return admin_user

    response = RedirectResponse(url="/auth", status_code=303)

    user = db.get(User, user_id)
    if user is None:
        set_flash(response, "error", "Usuario no encontrado")
        return response

    try:
        offboarding_service.reactivate(db, user=user)
        set_flash(
            response,
            "success",
            f"{user.full_name} reactivado. Lo que se reasignó en la baja no vuelve solo."
        )

    except OffboardingError as e:
        set_flash(response, "error", str(e))

    return response
