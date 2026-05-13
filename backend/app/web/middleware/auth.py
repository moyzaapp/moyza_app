from starlette.middleware.base import BaseHTTPMiddleware

from fastapi.responses import RedirectResponse

from sqlalchemy.orm import Session

from app.core.security import decode_token
from app.db.session import SessionLocal
from app.models.user import User


PUBLIC_PATHS = [
    "/",
    "/login",
    "/logout",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/static"
]


class AuthMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request, call_next):

        path = request.url.path

        # Rutas públicas
        # if any(path.startswith(p) for p in PUBLIC_PATHS):
        if path in PUBLIC_PATHS:

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

            user = db.query(User).filter(
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

        finally:

            db.close()

        response = await call_next(request)

        return response