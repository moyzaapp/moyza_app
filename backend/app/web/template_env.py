import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.templating import Jinja2Templates

from app.core.constants import BusinessType

logger = logging.getLogger(__name__)

_UTC = ZoneInfo("UTC")
_MADRID = ZoneInfo("Europe/Madrid")

# CSS de Tailwind compilado (build de Docker o scripts/build_css.sh; ver TAILWIND_BUILD.md).
# Si no existe, base.html usa el compilador en navegador (/static/js/tailwind.js).
_TAILWIND_CSS = Path(__file__).resolve().parent.parent / "static" / "css" / "tailwind.css"


def _tailwind_css_version() -> int | None:
    """Versión del CSS compilado para el `?v=` (mtime), o None si no existe.

    Se calcula una vez al importar: tras regenerar el CSS hay que reiniciar la app.
    """
    try:
        return int(_TAILWIND_CSS.stat().st_mtime)
    except OSError:
        return None


tailwind_css_version = _tailwind_css_version()
if tailwind_css_version is None:
    logger.warning(
        "tailwind.css no encontrado (%s): se usa el compilador en navegador (lento). "
        "Ejecuta scripts/build_css.sh",
        _TAILWIND_CSS,
    )


def madrid_dt(value, fmt: str = "%d/%m/%Y %H:%M"):
    """Convert a naive UTC datetime to Europe/Madrid and format it."""
    if value is None:
        return ""
    if not isinstance(value, datetime):
        return value
    aware = value.replace(tzinfo=_UTC)
    return aware.astimezone(_MADRID).strftime(fmt)


def company_context(request) -> dict:
    """Expone la empresa activa a todas las plantillas.

    `active_company` puede ser None en páginas públicas (login) o si el
    usuario no tiene empresa asignada; las plantillas deben tolerarlo.
    """
    allowed = list(getattr(request.state, "allowed_companies", []) or [])
    company = getattr(request.state, "company", None)
    user = getattr(request.state, "user", None)
    role_name = (user.role.name if user is not None and user.role else "") or ""
    return {
        # Rol del usuario para sidebar y navbar (las plantillas no leen request.state.user.role)
        "user_is_admin": role_name.lower() == "admin",
        "user_role_label": {"admin": "Administrador", "agent": "Agente"}.get(role_name.lower(), role_name.capitalize()),
        "active_company": company,
        "allowed_companies": allowed,
        "can_switch_company": len(allowed) > 1,
        # Atajos con fallback para páginas sin empresa (login)
        "brand_name": company.name if company else "MOYZA",
        "brand_color": (company.primary_color if company and company.primary_color else "#000000"),
    }


templates = Jinja2Templates(
    directory="app/web/templates",
    context_processors=[company_context],
)
templates.env.filters["madrid_dt"] = madrid_dt
templates.env.globals["current_year"] = lambda: datetime.now().year
# Operaciones fijas (Venta / Alquiler) para los selects: BusinessType.values()
templates.env.globals["BusinessType"] = BusinessType
# Tailwind: <link> al CSS compilado si existe; si es None, base.html carga tailwind.js
templates.env.globals["tailwind_css_version"] = tailwind_css_version
