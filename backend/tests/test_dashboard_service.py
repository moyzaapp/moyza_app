"""
Tests del servicio del Inicio (PLAN_DASHBOARD_INICIO.md).

- Unitarios (sin base de datos): período semana / mes / año, normalización
  al inicio del período, navegación y `show_next`.

Ejecución dentro del contenedor:
    docker exec moyza_backend python -m pytest tests/test_dashboard_service.py -q
"""
from datetime import datetime

import pytest

from app.services.dashboard_service import DashboardService


NOW = datetime(2026, 10, 8, 10, 30)   # jueves


# ---------------------------------------------------------------------------
# Período (fase 1)
# ---------------------------------------------------------------------------

class TestPeriod:

    def test_por_defecto_es_la_semana_en_curso(self):
        p = DashboardService.period(now=NOW)
        assert p.period_type == "WEEKLY"
        assert p.start == datetime(2026, 10, 5)
        assert p.end == datetime(2026, 10, 11, 23, 59, 59)
        assert p.is_current and not p.show_next

    def test_semana_se_normaliza_al_lunes(self):
        p = DashboardService.period("WEEKLY", "2026-10-01", now=NOW)
        assert p.start == datetime(2026, 9, 28)
        assert not p.is_current
        assert p.show_next
        assert p.next_start == datetime(2026, 10, 5)

    def test_mes_se_normaliza_al_dia_1(self):
        p = DashboardService.period("MONTHLY", "2026-02-17", now=NOW)
        assert p.start == datetime(2026, 2, 1)
        assert p.end == datetime(2026, 2, 28, 23, 59, 59)
        assert p.label == "Febrero 2026"
        assert p.show_next

    def test_mes_en_curso_no_navega_al_futuro(self):
        p = DashboardService.period("MONTHLY", "", now=NOW)
        assert p.start == datetime(2026, 10, 1)
        assert p.is_current and not p.show_next

    def test_anio(self):
        p = DashboardService.period("YEARLY", "2025-07-01", now=NOW)
        assert p.start == datetime(2025, 1, 1)
        assert p.show_next and not p.is_current

    @pytest.mark.parametrize("period_type, start", [("DAILY", ""), ("", "x"), ("WEEKLY", "2026-99-01")])
    def test_valores_invalidos_vuelven_a_la_semana_en_curso(self, period_type, start):
        p = DashboardService.period(period_type, start, now=NOW)
        if period_type in ("DAILY", ""):
            assert p.period_type == "WEEKLY"
        assert p.start == datetime(2026, 10, 5)

    def test_fecha_futura_se_normaliza_y_no_ofrece_siguiente(self):
        p = DashboardService.period("WEEKLY", "2026-10-30", now=NOW)
        # Una semana futura se muestra, pero no ofrece seguir avanzando
        assert p.start == datetime(2026, 10, 26)
        assert not p.show_next

    def test_periodo_anterior(self):
        p = DashboardService.period("MONTHLY", "2026-01-10", now=NOW)
        prev = DashboardService.previous_period(p, now=NOW)
        assert prev.start == datetime(2025, 12, 1)
        assert prev.end == datetime(2025, 12, 31, 23, 59, 59)
        assert not prev.is_current
