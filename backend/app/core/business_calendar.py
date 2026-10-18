"""Calendario hábil de Jaén (PLAN_ALERTAS_DIAS_HABILES.md §2.1).

- Días hábiles: lunes a viernes que no son festivo nacional, de Andalucía
  (librería `holidays`, país ES, comunidad AN, con los traslados al lunes) ni
  local de Jaén capital (`LocalHolidays` en `core/constants.py`). El sábado no
  es hábil (decisión 3).
- "Horas hábiles" = horas que caen dentro de un día hábil, en hora de Madrid.
  Cada día hábil aporta 24 h, así que 48 h hábiles son dos días hábiles
  completos a la misma hora (decisión 1): viernes 18:00 -> martes 18:00. Si el
  reloj arranca en un día no hábil, empieza a contar a las 00:00 del siguiente
  hábil (sábado 10:00 + 48 h -> miércoles 00:00).
- Las fechas de entrada y salida son UTC naive, como `created_at` en la base
  de datos; la cuenta se hace en `Europe/Madrid`. Los cambios de hora caen
  siempre en domingo (no hábil), así que contar en hora local de pared nunca
  parte un día hábil.

Sin base de datos: todo es puro y se prueba en tests/test_business_calendar.py.
"""
from datetime import date
from datetime import datetime
from datetime import time
from datetime import timedelta
from functools import lru_cache
from typing import Optional
from zoneinfo import ZoneInfo

import holidays

from app.core.constants import LocalHolidays

MADRID = ZoneInfo("Europe/Madrid")
UTC = ZoneInfo("UTC")

COUNTRY = "ES"
SUBDIVISION = "AN"

HOURS_PER_DAY = 24
# Límite de seguridad de los bucles (un año de días); nunca se alcanza con datos reales
_MAX_DAYS = 400

WEEKDAYS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


# ---------------------------------------------------------------------------
# Festivos y días hábiles
# ---------------------------------------------------------------------------

@lru_cache(maxsize=16)
def holidays_for_year(year: int) -> dict:
    """{fecha: nombre} de los festivos de Jaén capital en `year`."""
    result = dict(holidays.country_holidays(COUNTRY, subdiv=SUBDIVISION, years=year))
    for month, day, name in LocalHolidays.BY_YEAR.get(year, []):
        result.setdefault(date(year, month, day), name)
    return result


def holiday_name(day: date) -> Optional[str]:
    """Nombre del festivo de `day`, o None si no lo es."""
    return holidays_for_year(day.year).get(day)


def is_business_day(day) -> bool:
    """Lunes a viernes que no es festivo. Acepta `date` o `datetime` (se usa su fecha)."""
    if isinstance(day, datetime):
        day = day.date()
    return day.weekday() < 5 and day not in holidays_for_year(day.year)


def next_business_day(day: date) -> date:
    """El primer día hábil estrictamente posterior a `day`."""
    candidate = day + timedelta(days=1)
    for _ in range(_MAX_DAYS):
        if is_business_day(candidate):
            return candidate
        candidate += timedelta(days=1)
    raise ValueError(f"Sin días hábiles tras {day}")  # pragma: no cover


# ---------------------------------------------------------------------------
# Conversión UTC naive <-> hora de Madrid
# ---------------------------------------------------------------------------

def to_madrid(value: datetime) -> datetime:
    """UTC naive -> hora local de Madrid (naive)."""
    return value.replace(tzinfo=UTC).astimezone(MADRID).replace(tzinfo=None)


def to_utc(local: datetime) -> datetime:
    """Hora local de Madrid (naive) -> UTC naive."""
    return local.replace(tzinfo=MADRID).astimezone(UTC).replace(tzinfo=None)


def madrid_today(now: Optional[datetime] = None) -> date:
    """Fecha de hoy en Madrid; `now` en UTC naive (por defecto, la hora actual)."""
    return to_madrid(now or datetime.utcnow()).date()


# ---------------------------------------------------------------------------
# Horas hábiles
# ---------------------------------------------------------------------------

def add_business_hours(start: datetime, hours: float) -> datetime:
    """`start` + `hours` contando solo el tiempo dentro de días hábiles.

    `start` y el resultado en UTC naive. Viernes 18:00 + 48 -> martes 18:00;
    si el lunes es festivo, miércoles 18:00.
    """
    remaining = timedelta(hours=hours)
    if remaining <= timedelta(0):
        return start
    local = to_madrid(start)
    day = local.date()
    cursor = local
    for _ in range(_MAX_DAYS * 2):
        if is_business_day(day):
            day_end = datetime.combine(day + timedelta(days=1), time.min)
            available = day_end - cursor
            if remaining <= available:
                return to_utc(cursor + remaining)
            remaining -= available
        day += timedelta(days=1)
        cursor = datetime.combine(day, time.min)
    raise ValueError("Demasiadas horas hábiles")  # pragma: no cover


def business_hours_between(start: datetime, end: datetime) -> float:
    """Horas hábiles entre `start` y `end` (UTC naive). 0 si `end` <= `start`."""
    if end <= start:
        return 0.0
    local_start, local_end = to_madrid(start), to_madrid(end)
    total = timedelta(0)
    day = local_start.date()
    while day <= local_end.date():
        if is_business_day(day):
            day_start = datetime.combine(day, time.min)
            day_end = day_start + timedelta(days=1)
            lo, hi = max(local_start, day_start), min(local_end, day_end)
            if hi > lo:
                total += hi - lo
        day += timedelta(days=1)
    return total.total_seconds() / 3600


def next_business_day_at(hour: int, now: Optional[datetime] = None, minute: int = 0) -> datetime:
    """Próximo momento a las `hour`:`minute` de Madrid en un día hábil, en UTC naive.

    Si hoy es hábil y aún no ha llegado esa hora, es hoy.
    """
    now = now or datetime.utcnow()
    local_now = to_madrid(now)
    day = local_now.date()
    target = datetime.combine(day, time(hour, minute))
    if not (is_business_day(day) and target > local_now):
        day = next_business_day(day)
        target = datetime.combine(day, time(hour, minute))
    return to_utc(target)


# ---------------------------------------------------------------------------
# Textos
# ---------------------------------------------------------------------------

def format_business_duration(hours: float) -> str:
    """Horas hábiles como texto corto: '5 h', '2 d 5 h', '3 d' (1 d = 24 h hábiles)."""
    total = max(int(hours), 0)
    days, rest = divmod(total, HOURS_PER_DAY)
    if not days:
        return f"{rest} h"
    if not rest:
        return f"{days} d"
    return f"{days} d {rest} h"


def business_days_label(hours: float) -> str:
    """Días hábiles completos como texto: '1 día hábil', '3 días hábiles'."""
    days = max(int(hours) // HOURS_PER_DAY, 0)
    return f"{days} {'día hábil' if days == 1 else 'días hábiles'}"


def format_due(value: Optional[datetime], now: Optional[datetime] = None) -> str:
    """'martes 20/10 a las 12:00' (hora de Madrid); añade el año si no es el de `now`."""
    if value is None:
        return ""
    local = to_madrid(value)
    year = to_madrid(now or datetime.utcnow()).year
    day = local.strftime("%d/%m") if local.year == year else local.strftime("%d/%m/%Y")
    return f"{WEEKDAYS[local.weekday()]} {day} a las {local.strftime('%H:%M')}"
