import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.templating import Jinja2Templates

from app.core.config import settings
from app.core.constants import AlertOrigin, BusinessType, PhoneCountryCodes
from app.core.phone import phone_display, split_phone, tel_href, whatsapp_url

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


def eur(value, empty: str = "–") -> str:
    """Importe en euros con formato de España: 120000 -> '120.000 €'."""
    if value is None or value == "":
        return empty
    try:
        return f"{int(round(float(value))):,}".replace(",", ".") + " €"
    except (TypeError, ValueError):
        return empty


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
# Enlace wa.me del teléfono (None si no es utilizable): {{ phone | whatsapp_url }}
templates.env.filters["whatsapp_url"] = whatsapp_url
# Teléfono para mostrar ('+34 600 112 233'), enlace tel: y (código, local) del
# selector de país (PLAN_TELEFONO_COMPRADOR.md)
templates.env.filters["phone_display"] = phone_display
templates.env.filters["tel_href"] = tel_href
templates.env.filters["split_phone"] = split_phone
# Precios: {{ prop.price | eur }} -> '120.000 €'
templates.env.filters["eur"] = eur
# Opciones del selector de país; globales para que las vea el macro phone_field
templates.env.globals["phone_country_choices"] = PhoneCountryCodes.choices()
templates.env.globals["phone_default_country"] = PhoneCountryCodes.DEFAULT
templates.env.globals["current_year"] = lambda: datetime.now().year
# Envío de la ficha de visita por WhatsApp (ver config.VISIT_SHEET_WHATSAPP_ENABLED)
templates.env.globals["visit_sheet_whatsapp_enabled"] = settings.VISIT_SHEET_WHATSAPP_ENABLED
# Operaciones fijas (Venta / Alquiler) para los selects: BusinessType.values()
templates.env.globals["BusinessType"] = BusinessType
# Origen de una alerta: con referencia ('property') o búsqueda general ('search')
templates.env.globals["AlertOrigin"] = AlertOrigin
# Tailwind: <link> al CSS compilado si existe; si es None, base.html carga tailwind.js
templates.env.globals["tailwind_css_version"] = tailwind_css_version
