from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi.templating import Jinja2Templates

from app.core.constants import COMPANIES

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


templates = Jinja2Templates(directory="app/web/templates")
templates.env.filters["madrid_dt"] = madrid_dt
templates.env.globals["current_year"] = lambda: datetime.now().year
templates.env.globals["companies"] = COMPANIES
