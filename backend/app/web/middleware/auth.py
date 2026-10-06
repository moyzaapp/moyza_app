from starlette.middleware.base import BaseHTTPMiddleware

from fastapi.responses import RedirectResponse

from sqlalchemy.orm import Session
from sqlalchemy.orm import joinedload

from app.core.security import decode_token
from app.db.session import SessionLocal
from app.models.user import User
from app.web.dependencies.company import ACTIVE_COMPANY_COOKIE
from app.web.dependencies.company import get_allowed_companies
from app.web.dependencies.company import resolve_active_company


PUBLIC_PATHS = [
    "/",
    "/login",
    "/logout",
    "/docs",
    "/openapi.json",
    "/redoc"
]

# Prefijos públicos: archivos estáticos servidos por StaticFiles
PUBLIC_PREFIXES = [
    "/static",
    "/storage"
]


class AuthMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request, call_next):

        path = request.url.path

        if path.startswith("/api"):
            return await call_next(request)

        # Rutas públicas
        if path in PUBLIC_PATHS:

            return await call_next(request)

        # Archivos estáticos (coinciden por prefijo, no por ruta exacta)
        if any(path.startswith(p) for p in PUBLIC_PREFIXES):

            return await call_next(request)

        token = request.cookies.get("access_token")

        # No token
        if not token:

            return RedirectResponse(
                url="/",
                status_code=302
            )

        payload = decode_token(token)

        # Token inválido o expirado
        if not payload:

            response = RedirectResponse(
                url="/",
                status_code=302
            )

            response.delete_cookie("access_token")

            return response

        email = payload.get("sub")

        if not email:

            return RedirectResponse(
                url="/",
                status_code=302
            )

        db: Session = SessionLocal()

        try:

            user = db.query(User).options(
                joinedload(User.role),
                joinedload(User.companies)
            ).filter(
                User.email == email
            ).first()

            if not user:

                response = RedirectResponse(
                    url="/",
                    status_code=302
                )

                response.delete_cookie("access_token")

                return response

            # Usuario disponible globalmente
            request.state.user = user

            # Contexto de empresa (MOYZA / MOES): qué empresas puede ver
            # el usuario y cuál está activa según la cookie.
            allowed = get_allowed_companies(user, db)

            request.state.allowed_companies = allowed

            request.state.company = resolve_active_company(
                allowed,
                request.cookies.get(ACTIVE_COMPANY_COOKIE)
            )

        finally:

            db.close()

        response = await call_next(request)

        return response