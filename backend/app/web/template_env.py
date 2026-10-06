from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi.templating import Jinja2Templates

_UTC = ZoneInfo("UTC")
_MADRID = ZoneInfo("Europe/Madrid")


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
    return {
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
