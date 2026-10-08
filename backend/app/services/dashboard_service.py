"""Inicio (/dashboard) por rol. PLAN_DASHBOARD_INICIO.md.

Entradas puras (sin `request`) para que se puedan probar sin la app:

- `period()`: período de los query params (semana / mes / año) con su
  navegación. Es el mismo `period()` de `PerformanceReportService`: una sola
  implementación para el Inicio y Resultados Comerciales.

Todas las consultas se limitan a la empresa del servicio.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.core.constants import PeriodType
from app.services.performance_report_service import Period
from app.services.performance_report_service import PerformanceReportService


class DashboardService:

    def __init__(self, db: Session, company_id: int):
        self.db = db
        self.company_id = company_id
        self.perf = PerformanceReportService(db, company_id)

    # ------------------------------------------------------------------
    # Período
    # ------------------------------------------------------------------

    @staticmethod
    def period(
        period_type: str = PeriodType.DEFAULT,
        period_start_str: str = "",
        now: Optional[datetime] = None,
    ) -> Period:
        """Período del Inicio. Tipo desconocido -> semana; fecha vacía o inválida -> en curso."""
        return PerformanceReportService.period(period_type, period_start_str, now=now)

    @staticmethod
    def previous_period(period: Period, now: Optional[datetime] = None) -> Period:
        """Período inmediatamente anterior (para los deltas)."""
        return PerformanceReportService.period(period.period_type, period.prev_str, now=now)
