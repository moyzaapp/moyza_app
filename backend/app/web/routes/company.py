"""Cambio de empresa activa (selector del sidebar)."""
from urllib.parse import urlparse

from fastapi import APIRouter
from fastapi import Request
from fastapi import Form

from fastapi.responses import RedirectResponse

from app.web.dependencies.company import ACTIVE_COMPANY_COOKIE
from app.web.dependencies.company import ACTIVE_COMPANY_COOKIE_MAX_AGE
from app.web.dependencies.company import get_allowed_companies_from_request
from app.web.utils.flash import set_flash

router = APIRouter()


def _safe_next(next_url: str | None, fallback: str = "/properties") -> str:
    """Solo acepta rutas locales para evitar redirecciones abiertas."""
    if not next_url:
        return fallback

    parsed = urlparse(next_url)

    if parsed.scheme or parsed.netloc or not next_url.startswith("/"):
        return fallback

    # Evitar volver al propio endpoint de cambio
    if parsed.path == "/switch-company":
        return fallback

    return next_url


@router.post("/switch-company")
async def switch_company(
    request: Request,
    code: str = Form(...),
    next_url: str = Form(None, alias="next"),
):
    allowed = get_allowed_companies_from_request(request)

    target = next((c for c in allowed if c.code == code), None)

    response = RedirectResponse(url=_safe_next(next_url), status_code=303)

    if target is None:
        set_flash(response, "error", "No tienes acceso a esa empresa.")
        return response

    response.set_cookie(
        key=ACTIVE_COMPANY_COOKIE,
        value=target.code,
        max_age=ACTIVE_COMPANY_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        path="/",
    )

    set_flash(response, "success", f"Ahora estás trabajando en {target.name}.")

    return response
