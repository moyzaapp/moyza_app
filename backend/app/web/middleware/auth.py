from starlette.middleware.base import BaseHTTPMiddleware

from fastapi.responses import RedirectResponse

from sqlalchemy.orm import Session
from sqlalchemy.orm import joinedload

from app.core.security import decode_token
from app.db.session import SessionLocal
from app.models.user import User
from app.web.dependencies.company import resolve_user_company_scope


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

            # Sin usuario o dado de baja (NULL cuenta como activo): fuera,
            # también las sesiones vivas (PLAN_BAJA_USUARIOS.md §4.1)
            if not user or user.is_active is False:

                response = RedirectResponse(
                    url="/",
                    status_code=302
                )

                response.delete_cookie("access_token")

                return response

            # Usuario disponible globalmente
            request.state.user = user

            # Contexto de empresa (MOYZA / MOES): qué empresas puede ver el
            # usuario, cuál está activa (cookie, o su principal en la vista
            # unificada) y con cuáles trabaja (PLAN_VISTA_UNIFICADA_AGENTES.md)
            scope = resolve_user_company_scope(request, user, db)

            request.state.allowed_companies = scope.allowed

            request.state.company = scope.company

            request.state.company_ids = scope.company_ids

            request.state.unified_view = scope.unified_view

        finally:

            db.close()

        response = await call_next(request)

        return response