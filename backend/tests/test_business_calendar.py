"""
Calendario hábil de Jaén (PLAN_ALERTAS_DIAS_HABILES.md §2.1, fase 1).

Sin base de datos: fines de semana, festivos nacionales y de Andalucía
(28 de febrero, Jueves y Viernes Santo, traslados al lunes), festivos locales
de Jaén capital, cambio de hora y textos.

    docker exec moyza_backend python -m pytest tests/test_business_calendar.py -q
"""
from datetime import date
from datetime import datetime

import pytest

from app.core import business_calendar as bc


def L(*args) -> datetime:
    """Hora local de Madrid -> UTC naive (como se guarda en la base de datos)."""
    return bc.to_utc(datetime(*args))


def local(value: datetime) -> datetime:
    return bc.to_madrid(value)


# ---------------------------------------------------------------------------
# Días hábiles
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("day, expected", [
    (date(2026, 10, 16), True),    # viernes
    (date(2026, 10, 17), False),   # sábado (decisión 3)
    (date(2026, 10, 18), False),   # domingo (y San Lucas)
    (date(2026, 5, 1), False),     # Fiesta del Trabajo (viernes)
    (date(2028, 2, 28), False),    # Día de Andalucía en lunes
    (date(2027, 3, 1), False),     # 28-F de 2027 (domingo) trasladado al lunes
    (date(2026, 4, 2), False),     # Jueves Santo (Andalucía)
    (date(2026, 4, 3), False),     # Viernes Santo
    (date(2026, 4, 6), True),      # Lunes de Pascua: no es festivo en Andalucía
    (date(2027, 3, 25), False),    # Jueves Santo 2027
    (date(2027, 3, 26), False),    # Viernes Santo 2027
    (date(2026, 11, 2), False),    # Todos los Santos (domingo) trasladado al lunes
    (date(2026, 12, 7), False),    # Constitución (domingo) trasladada al lunes
    (date(2026, 6, 11), False),    # Virgen de la Capilla (local de Jaén, jueves)
    (date(2027, 6, 11), False),    # Virgen de la Capilla 2027 (viernes)
    (date(2027, 10, 18), False),   # San Lucas 2027 (lunes)
    (date(2028, 10, 18), False),   # San Lucas 2028 (miércoles)
    (date(2029, 6, 11), True),     # año sin festivos locales cargados
])
def test_is_business_day(day, expected):
    assert bc.is_business_day(day) is expected


def test_acepta_datetime_y_da_nombre_del_festivo():
    assert bc.is_business_day(datetime(2026, 10, 16, 23, 0))
    assert bc.holiday_name(date(2026, 6, 11)) == "Virgen de la Capilla"
    assert bc.holiday_name(date(2026, 2, 28)) == "Día de Andalucía"
    assert bc.holiday_name(date(2026, 10, 14)) is None


def test_next_business_day():
    assert bc.next_business_day(date(2026, 10, 16)) == date(2026, 10, 19)
    assert bc.next_business_day(date(2026, 10, 30)) == date(2026, 11, 3)   # lunes 2 festivo
    assert bc.next_business_day(date(2026, 4, 1)) == date(2026, 4, 6)


# ---------------------------------------------------------------------------
# add_business_hours
# ---------------------------------------------------------------------------

def test_viernes_tarde_vence_el_martes_a_la_misma_hora():
    assert local(bc.add_business_hours(L(2026, 10, 16, 18, 0), 48)) == datetime(2026, 10, 20, 18, 0)


def test_criterio_aceptacion_viernes_mediodia():
    # Viernes 12:00 -> martes 12:00
    assert local(bc.add_business_hours(L(2026, 10, 16, 12, 0), 48)) == datetime(2026, 10, 20, 12, 0)
    # ...y si el lunes es festivo (2 de noviembre de 2026), miércoles 12:00
    assert local(bc.add_business_hours(L(2026, 10, 30, 12, 0), 48)) == datetime(2026, 11, 4, 12, 0)


def test_jueves_con_viernes_festivo():
    # Jueves 30/04/2026 10:00, viernes 1 de mayo festivo -> martes 10:00
    assert local(bc.add_business_hours(L(2026, 4, 30, 10, 0), 48)) == datetime(2026, 5, 5, 10, 0)
    # Sin festivo, jueves 10:00 -> lunes 10:00
    assert local(bc.add_business_hours(L(2026, 10, 15, 10, 0), 48)) == datetime(2026, 10, 19, 10, 0)


def test_semana_santa():
    # Miércoles Santo 12:00: jueves y viernes festivos -> martes 12:00
    assert local(bc.add_business_hours(L(2026, 4, 1, 12, 0), 48)) == datetime(2026, 4, 7, 12, 0)
    assert local(bc.add_business_hours(L(2027, 3, 24, 12, 0), 48)) == datetime(2027, 3, 30, 12, 0)


def test_festivo_local_de_jaen():
    # Miércoles 10/06/2026 12:00, jueves 11 festivo local -> lunes 15 12:00
    assert local(bc.add_business_hours(L(2026, 6, 10, 12, 0), 48)) == datetime(2026, 6, 15, 12, 0)


def test_empieza_en_dia_no_habil():
    # Sábado 10:00: cuenta desde el lunes 00:00 -> miércoles 00:00
    assert local(bc.add_business_hours(L(2026, 10, 17, 10, 0), 48)) == datetime(2026, 10, 21, 0, 0)
    # Desde un festivo (lunes 2/11) -> jueves 5 00:00
    assert local(bc.add_business_hours(L(2026, 11, 2, 9, 0), 48)) == datetime(2026, 11, 5, 0, 0)


def test_cambio_de_hora_octubre_y_marzo():
    # 25/10/2026: fin del horario de verano (domingo). Misma hora local, distinta en UTC
    start = L(2026, 10, 23, 18, 0)
    assert start == datetime(2026, 10, 23, 16, 0)
    due = bc.add_business_hours(start, 48)
    assert local(due) == datetime(2026, 10, 27, 18, 0)
    assert due == datetime(2026, 10, 27, 17, 0)
    # 29/03/2026: inicio del horario de verano
    start = L(2026, 3, 27, 18, 0)
    assert start == datetime(2026, 3, 27, 17, 0)
    due = bc.add_business_hours(start, 48)
    assert local(due) == datetime(2026, 3, 31, 18, 0)
    assert due == datetime(2026, 3, 31, 16, 0)


def test_cero_horas_devuelve_el_inicio():
    start = L(2026, 10, 17, 10, 0)
    assert bc.add_business_hours(start, 0) == start


# ---------------------------------------------------------------------------
# business_hours_between
# ---------------------------------------------------------------------------

def test_horas_habiles_entre_fechas():
    fri = L(2026, 10, 16, 18, 0)
    assert bc.business_hours_between(fri, L(2026, 10, 19, 6, 0)) == 12
    assert bc.business_hours_between(fri, L(2026, 10, 20, 18, 0)) == 48
    # Todo en fin de semana: 0
    assert bc.business_hours_between(L(2026, 10, 17, 9, 0), L(2026, 10, 18, 20, 0)) == 0
    # Al revés: 0
    assert bc.business_hours_between(L(2026, 10, 20, 9, 0), fri) == 0
    # Con cambio de hora por medio: el domingo no cuenta y el lunes son 24 h
    assert bc.business_hours_between(L(2026, 10, 23, 18, 0), L(2026, 10, 27, 18, 0)) == 48


def test_coherencia_suma_y_diferencia():
    for start in (L(2026, 10, 16, 18, 0), L(2026, 4, 1, 12, 0), L(2026, 10, 17, 10, 0), L(2026, 3, 27, 9, 30)):
        due = bc.add_business_hours(start, 48)
        assert bc.business_hours_between(start, due) == pytest.approx(48)


# ---------------------------------------------------------------------------
# next_business_day_at
# ---------------------------------------------------------------------------

def test_proximo_dia_habil_a_las_8():
    # Viernes 07:00 -> hoy 08:00
    assert local(bc.next_business_day_at(8, now=L(2026, 10, 16, 7, 0))) == datetime(2026, 10, 16, 8, 0)
    # Viernes 09:00 -> lunes 08:00
    assert local(bc.next_business_day_at(8, now=L(2026, 10, 16, 9, 0))) == datetime(2026, 10, 19, 8, 0)
    # Sábado -> lunes; viernes antes de un lunes festivo -> martes
    assert local(bc.next_business_day_at(8, now=L(2026, 10, 17, 7, 0))) == datetime(2026, 10, 19, 8, 0)
    assert local(bc.next_business_day_at(8, now=L(2026, 10, 30, 9, 0))) == datetime(2026, 11, 3, 8, 0)


def test_madrid_today():
    # 23:30 UTC del viernes ya es sábado en Madrid (verano)
    assert bc.madrid_today(datetime(2026, 10, 16, 23, 30)) == date(2026, 10, 17)


# ---------------------------------------------------------------------------
# Textos
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("hours, text", [(0, "0 h"), (5.9, "5 h"), (24, "1 d"), (53, "2 d 5 h"), (72, "3 d")])
def test_format_business_duration(hours, text):
    assert bc.format_business_duration(hours) == text


def test_business_days_label():
    assert bc.business_days_label(30) == "1 día hábil"
    assert bc.business_days_label(72) == "3 días hábiles"


def test_format_due():
    now = L(2026, 10, 16, 9, 0)
    assert bc.format_due(L(2026, 10, 20, 12, 0), now=now) == "martes 20/10 a las 12:00"
    assert bc.format_due(L(2027, 1, 5, 9, 30), now=now) == "martes 05/01/2027 a las 09:30"
    assert bc.format_due(None) == ""
