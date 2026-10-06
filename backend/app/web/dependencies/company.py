"""Contexto de empresa activa (MOYZA / MOES PREMIUM).

El middleware de autenticación resuelve, por cada petición, qué empresas
puede ver el usuario y cuál está activa. El resto de la app lee ese
resultado desde `request.state`:

- request.state.company            -> Company activa
- request.state.allowed_companies  -> lista de Company que puede elegir

Regla de resolución:
1. Admin: todas las empresas activas.
2. Resto: las empresas del usuario (`user_companies`) más las de su ficha
   de agente (`agent_companies`, enlazada por email).
3. Si la cookie `active_company` apunta a una empresa permitida, esa es la
   activa. Si no, la primera permitida (MOYZA por defecto).
"""
from fastapi import Request
from fastapi import HTTPException
from fastapi import status
from sqlalchemy.orm import Session
from sqlalchemy.orm import joinedload

from app.core.constants import CompanyCode
from app.models.agent import Agent
from app.models.company import Company
from app.models.user import User

ACTIVE_COMPANY_COOKIE = "active_company"

# Un año: el cambio de empresa es una preferencia estable del usuario
ACTIVE_COMPANY_COOKIE_MAX_AGE = 60 * 60 * 24 * 365


def _is_admin(user: User) -> bool:
    return bool(user and user.role and user.role.name.lower() == "admin")


def get_allowed_companies(user: User, db: Session) -> list[Company]:
    """Empresas que el usuario puede ver, ordenadas por id (MOYZA primero)."""
    active = (
        db.query(Company)
        .filter(Company.is_active.is_(True))
        .order_by(Company.id)
        .all()
    )

    if _is_admin(user):
        return active

    allowed_ids = {c.id for c in user.companies}

    agent = (
        db.query(Agent)
        .options(joinedload(Agent.companies))
        .filter(Agent.email == user.email)
        .first()
    )
    if agent:
        allowed_ids.update(c.id for c in agent.companies)

    allowed = [c for c in active if c.id in allowed_ids]

    # Transición: un usuario sin ninguna empresa asignada trabaja en la
    # empresa por defecto (MOYZA) para no quedarse sin acceso. La gestión
    # explícita de pertenencias llega con el formulario de usuarios.
    if not allowed:
        allowed = [c for c in active if c.code == CompanyCode.DEFAULT]

    return allowed


def resolve_company_for_api(request: Request, user: User, db: Session) -> Company | None:
    """Empresa activa para endpoints `/api/...`, que no pasan por AuthMiddleware."""
    allowed = get_allowed_companies(user, db)
    return resolve_active_company(allowed, request.cookies.get(ACTIVE_COMPANY_COOKIE))


def get_api_user(request: Request, db: Session) -> User | None:
    """Usuario autenticado por cookie para endpoints `/api/...`."""
    from app.core.security import decode_token

    token = request.cookies.get("access_token")
    if not token:
        return None

    payload = decode_token(token)
    email = payload.get("sub") if payload else None
    if not email:
        return None

    return (
        db.query(User)
        .options(joinedload(User.role), joinedload(User.companies))
        .filter(User.email == email)
        .first()
    )


def resolve_active_company(
    allowed: list[Company],
    cookie_code: str | None
) -> Company | None:
    """Elige la empresa activa a partir de la cookie y las permitidas."""
    if not allowed:
        return None

    if cookie_code:
        for company in allowed:
            if company.code == cookie_code:
                return company

    for company in allowed:
        if company.code == CompanyCode.DEFAULT:
            return company

    return allowed[0]


def get_active_company(request: Request) -> Company:
    """Dependencia FastAPI: empresa activa de la petición.

    Lanza 403 si el usuario no tiene ninguna empresa asignada; sin empresa
    no hay nada que mostrar y es un error de configuración del usuario.
    """
    company = getattr(request.state, "company", None)

    if company is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El usuario no tiene ninguna empresa asignada."
        )

    return company


def get_allowed_companies_from_request(request: Request) -> list[Company]:
    return list(getattr(request.state, "allowed_companies", []) or [])


def can_switch_company(request: Request) -> bool:
    return len(get_allowed_companies_from_request(request)) > 1
