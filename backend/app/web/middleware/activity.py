import time
import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.background import BackgroundTask

from app.core.security import decode_token
from app.db.session import SessionLocal
from app.models.user_activity_log import UserActivityLog

logger = logging.getLogger(__name__)

SKIP_PREFIXES = ("/static", "/storage", "/docs", "/redoc", "/openapi")


class ActivityMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if any(path.startswith(p) for p in SKIP_PREFIXES):
            return await call_next(request)

        start = time.monotonic()
        response = await call_next(request)
        duration_ms = int((time.monotonic() - start) * 1000)

        user_id = self._get_user_id(request)
        ip = self._get_ip(request)

        # Una ruta puede dejar en `request.state.activity_path` un texto más
        # descriptivo que la URL (p. ej. la consulta de teléfono de Propiedades,
        # con el número y el resultado). El state viaja en el scope, así que lo
        # que pone la ruta se ve aquí, igual que `request.state.user`.
        path = getattr(request.state, "activity_path", None) or path

        response.background = BackgroundTask(
            _write_log,
            user_id=user_id,
            ip_address=ip,
            user_agent=request.headers.get("user-agent"),
            method=request.method,
            path=path,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )

        return response

    def _get_user_id(self, request: Request):
        try:
            # Primero intentar del state (ya lo setea AuthMiddleware)
            if hasattr(request.state, "user") and request.state.user:
                return request.state.user.id
            # Fallback: leer el JWT directamente
            token = request.cookies.get("access_token")
            if token:
                payload = decode_token(token)
                if payload:
                    from app.db.session import SessionLocal
                    from app.models.user import User
                    db = SessionLocal()
                    try:
                        user = db.query(User).filter(User.email == payload.get("sub")).first()
                        return user.id if user else None
                    finally:
                        db.close()
        except Exception:
            pass
        return None

    def _get_ip(self, request: Request):
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        if request.client:
            return request.client.host
        return None


def _write_log(**kwargs):
    db = SessionLocal()
    try:
        db.add(UserActivityLog(**kwargs))
        db.commit()
    except Exception as e:
        logger.warning("Error writing activity log: %s", e)
        db.rollback()
    finally:
        db.close()
