from fastapi import Request
from fastapi import Depends
from fastapi import HTTPException
from fastapi import status
from fastapi.responses import RedirectResponse

from sqlalchemy.orm import Session

from app.db.deps import get_db

from app.core.security import decode_token

from app.models.user import User
from app.models.agent import Agent


def get_current_web_user(
    request: Request,
    db: Session = Depends(get_db)
):

    token = request.cookies.get("access_token")

    if not token:

        return RedirectResponse(url="/", status_code=302)

    payload = decode_token(token)

    if not payload:

        return RedirectResponse(url="/", status_code=302)

    email = payload.get("sub")

    if not email:

        return RedirectResponse(url="/", status_code=302)

    user = db.query(User).filter(
        User.email == email
    ).first()

    # Dado de baja (NULL cuenta como activo), PLAN_BAJA_USUARIOS.md §4.1
    if not user or user.is_active is False:

        return RedirectResponse(url="/", status_code=302)

    return user


def require_admin_role(
    request: Request,
    db: Session = Depends(get_db)
):
    """Valida que el usuario tenga rol de admin (asumiendo role.name = 'Admin')"""
    from app.web.utils.flash import set_flash

    user = get_current_web_user(request, db)

    # Si get_current_web_user retorna RedirectResponse, propagarlo
    if isinstance(user, RedirectResponse):
        return user

    # Validar que el usuario tenga rol admin
    if not user.role or user.role.name.lower() != 'admin':
        response = RedirectResponse(url="/clients", status_code=303)
        set_flash(response, "error", "Acceso denegado. Solo administradores pueden acceder a esta sección.")
        return response

    return user


def get_agent_from_user(user: User, db: Session):
    """Obtiene el Agent asociado al usuario por email. Retorna None si no existe."""
    if not user:
        return None

    agent = db.query(Agent).filter(Agent.email == user.email).first()
    return agent


def is_admin(user: User) -> bool:
    """Verifica si el usuario tiene rol de admin"""
    return user and user.role and user.role.name.lower() == 'admin'


def deny_if_not_admin(request: Request, redirect_url: str):
    """Bloquea acciones reservadas al admin.

    Devuelve una redirección con flash de error cuando el usuario no es admin,
    o None cuando sí lo es (la acción puede continuar). Se usa en los endpoints
    POST para que ocultar el botón en la plantilla no sea la única protección.
    """
    from app.web.utils.flash import set_flash

    user = getattr(request.state, "user", None)

    if is_admin(user):
        return None

    response = RedirectResponse(url=redirect_url, status_code=302)

    set_flash(
        response,
        "error",
        "No tienes permisos para realizar esta acción."
    )

    return response