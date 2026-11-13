"""Contexto de empresa (MOYZA / MOES PREMIUM).

El middleware de autenticación resuelve, por cada petición, qué empresas
puede ver el usuario, cuál está activa y con cuáles trabaja. El resto de la
app lee ese resultado desde `request.state`:

- request.state.company            -> Company activa (en la vista unificada,
                                      la empresa principal del usuario)
- request.state.allowed_companies  -> lista de Company que puede ver
- request.state.company_ids        -> ids con los que trabaja la petición
                                      (`get_company_ids`)
- request.state.unified_view       -> True si trabaja con todas sus empresas
                                      a la vez, sin selector (`is_unified_view`)

Regla de resolución (PLAN_VISTA_UNIFICADA_AGENTES.md §2.1):
1. Empresas permitidas. Admin: todas las activas. Resto: las marcadas en su
   usuario (`user_companies`) más las de su ficha de agente
   (`agent_companies`, enlazada por email). Así una alerta asignada desde la
   otra empresa (que añade esa empresa a la ficha,
   `alert_assignment_service.assign`) se ve sin que el admin toque el usuario.
   Un usuario sin ninguna cae a MOYZA.
2. Admin, o usuario con `company_switch_enabled`: vista por empresa, como
   siempre. Si la cookie `active_company` apunta a una empresa permitida, esa
   es la activa; si no, la primera permitida (MOYZA por defecto).
   `company_ids` = [activa].
3. Resto (por defecto): vista unificada. Sin selector (la cookie se ignora),
   `company_ids` = todas sus permitidas y la empresa "activa" es su empresa
   principal (`primary_company_id`) si está entre las permitidas; si no, la
   primera permitida (MOYZA por defecto). La principal da la marca del
   sidebar y es la empresa por defecto de lo que se crea sin empresa
   derivable.

Lectura: las rutas pasan `get_company_ids(request)` a `scope_*` /
`get_*_in_company` (aceptan una lista). Creación: necesita una empresa
concreta (la del objeto del que deriva, o la elegida y validada contra
`company_ids`, o `get_active_company`).
"""
from dataclasses import dataclass

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

    # Las del usuario más las de su ficha de agente (ver cabecera)
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


@dataclass
class CompanyScope:
    """Resultado de la resolución de empresa de una petición (ver cabecera)."""

    allowed: list
    company: Company | None
    company_ids: list[int]
    unified_view: bool


def uses_unified_view(user: User) -> bool:
    """True si el usuario trabaja con todas sus empresas a la vez (sin selector).

    El admin nunca; el resto, salvo que su usuario tenga `company_switch_enabled`.
    """
    if user is None or _is_admin(user):
        return False
    return not bool(getattr(user, "company_switch_enabled", False))


def resolve_primary_company(user: User, allowed: list) -> Company | None:
    """Empresa principal del usuario entre las permitidas.

    La de `primary_company_id` si está entre las permitidas; si no, la primera
    permitida (MOYZA por defecto, mismo criterio que sin cookie).
    """
    primary_id = getattr(user, "primary_company_id", None)
    if primary_id is not None:
        for company in allowed:
            if company.id == primary_id:
                return company
    return resolve_active_company(allowed, None)


def resolve_company_scope(user: User, allowed: list, cookie_code: str | None) -> CompanyScope:
    """Empresa activa, ids de trabajo y modo de vista (función pura, sin BD)."""
    if uses_unified_view(user):
        company = resolve_primary_company(user, allowed)
        return CompanyScope(
            allowed=list(allowed),
            company=company,
            company_ids=[c.id for c in allowed],
            unified_view=True,
        )

    company = resolve_active_company(allowed, cookie_code)
    return CompanyScope(
        allowed=list(allowed),
        company=company,
        company_ids=[company.id] if company is not None else [],
        unified_view=False,
    )


def resolve_user_company_scope(request: Request, user: User, db: Session) -> CompanyScope:
    """`resolve_company_scope` con las empresas permitidas de la BD y la cookie."""
    return resolve_company_scope(
        user,
        get_allowed_companies(user, db),
        request.cookies.get(ACTIVE_COMPANY_COOKIE),
    )


def resolve_company_for_api(request: Request, user: User, db: Session) -> Company | None:
    """Empresa activa para endpoints `/api/...`, que no pasan por AuthMiddleware.

    Mismo criterio que el middleware: en la vista unificada, la principal.
    """
    return resolve_user_company_scope(request, user, db).company


def resolve_company_ids_for_api(request: Request, user: User, db: Session) -> list[int]:
    """`company_ids` para endpoints `/api/...` (mismo criterio que `get_company_ids`)."""
    return resolve_user_company_scope(request, user, db).company_ids


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

    # Dado de baja = no autenticado (NULL cuenta como activo), PLAN_BAJA_USUARIOS.md §4.1
    return (
        db.query(User)
        .options(joinedload(User.role), joinedload(User.companies))
        .filter(User.email == email, User.is_active.isnot(False))
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


def get_company_ids(request: Request) -> list[int]:
    """Ids de las empresas con las que trabaja la petición (para leer).

    Admin o vista por empresa: [empresa activa]. Vista unificada: todas las
    permitidas. Lanza 403, como `get_active_company`, si no hay ninguna.
    """
    ids = getattr(request.state, "company_ids", None)
    if ids is None:
        # Petición sin pasar por el middleware nuevo (tests antiguos): la activa
        return [get_active_company(request).id]
    if not ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El usuario no tiene ninguna empresa asignada."
        )
    return list(ids)


def is_unified_view(request: Request) -> bool:
    """True si el usuario trabaja con todas sus empresas a la vez (sin selector)."""
    return bool(getattr(request.state, "unified_view", False))


def get_allowed_companies_from_request(request: Request) -> list[Company]:
    return list(getattr(request.state, "allowed_companies", []) or [])


def can_switch_company(request: Request) -> bool:
    return not is_unified_view(request) and len(get_allowed_companies_from_request(request)) > 1
