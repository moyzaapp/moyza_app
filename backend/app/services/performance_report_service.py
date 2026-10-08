"""Rendimiento por agente: métricas, períodos, objetivos y snapshots.

PLAN_RESULTADOS_COMERCIALES.md. Reglas:

- Todas las métricas se calculan dentro de una empresa (`company_id`): las
  de sus propiedades, alertas, seguimientos y visitas. Un agente que está
  en las dos empresas tiene resultados, objetivos y snapshots separados.
- Captaciones, bajadas y cierres se desglosan en venta / alquiler. El tipo
  sale de la propiedad; en cierres, del tipo de la alerta y, si falta, del
  de la propiedad. Lo que no es venta ni alquiler cuenta en el total
  ("otros") pero en ningún tipo.
- Períodos semana, mes y año. El período en curso se calcula en vivo; uno
  pasado se lee de su snapshot congelado si existe.
- Las métricas con objetivo dependen del período (`PerformanceObjectives`).
"""
import calendar
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import case
from sqlalchemy import extract
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.constants import FollowUpActionType
from app.core.constants import PerformanceObjectives
from app.core.constants import PeriodType
from app.models.agent import Agent
from app.models.agent_performance_report import AgentPerformanceReport
from app.models.agent_performance_target import AgentPerformanceTarget
from app.models.alert_follow_up import AlertFollowUp
from app.models.company import Company
from app.models.property import Property
from app.models.property_alert import PropertyAlert
from app.models.property_price_history import PropertyPriceHistory
from app.models.property_visit import PropertyVisit
from app.services.company_scope import scope_agents
from app.services.company_scope import scope_visits
from app.services.company_scope import visits_for_agent


SALE = "venta"
RENT = "alquiler"
OTHER = "otros"
KINDS = (SALE, RENT, OTHER)

# Métricas con desglose venta / alquiler -> (clave venta, clave alquiler)
BREAKDOWN_KEYS = {
    "contactos": ("contactos_venta", "contactos_alquiler"),
    "captaciones_crm": ("captaciones_venta", "captaciones_alquiler"),
    "bajadas": ("bajadas_venta", "bajadas_alquiler"),
    "cierres": ("cierres_venta", "cierres_alquiler"),
}

# Métricas de la pestaña Rendimiento, en orden de presentación
RESULT_METRICS = ("captaciones_crm", "bajadas", "cierres", "contactos", "hojas_visita")

# Indicadores de la pestaña Evolución (orden del selector)
EVOLUTION_INDICATORS = ("captaciones_crm", "cierres", "bajadas")

# Columnas de métricas que se congelan en `agent_performance_reports`
SNAPSHOT_METRIC_KEYS = (
    "contactos_venta",
    "contactos_alquiler",
    "bajadas",
    "bajadas_venta",
    "bajadas_alquiler",
    "captaciones_crm",
    "captaciones_venta",
    "captaciones_alquiler",
    "cierres",
    "cierres_venta",
    "cierres_alquiler",
    "hojas_visita",
    "calidad_cartera",
)

MONTH_NAMES = (
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
)
MONTH_ABBR = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")


@dataclass(frozen=True)
class Period:
    """Período resuelto a partir de los query params, con su navegación."""

    period_type: str
    start: datetime
    end: datetime
    prev_start: datetime
    next_start: datetime
    current_start: datetime
    is_current: bool
    show_next: bool
    label: str

    @property
    def start_str(self) -> str:
        return self.start.strftime("%Y-%m-%d")

    @property
    def prev_str(self) -> str:
        return self.prev_start.strftime("%Y-%m-%d")

    @property
    def next_str(self) -> str:
        return self.next_start.strftime("%Y-%m-%d")


def _empty_counts() -> dict:
    return {kind: 0 for kind in KINDS}


def business_kind(column):
    """Expresión SQL: 'venta', 'alquiler' u 'otros' (NULL incluido) sin distinguir mayúsculas."""
    return case(
        (column.ilike(SALE), SALE),
        (column.ilike(RENT), RENT),
        else_=OTHER,
    )


def closing_business_type():
    """Tipo de un cierre: el de la alerta y, si falta (NULL o vacío), el de la propiedad."""
    return func.coalesce(
        func.nullif(func.trim(PropertyAlert.business_type), ""),
        Property.business_type,
    )


class PerformanceReportService:

    def __init__(self, db: Session, company_id: Optional[int] = None):
        self.db = db
        self.company_id = company_id

    def _require_company(self) -> int:
        if self.company_id is None:
            raise ValueError("PerformanceReportService necesita company_id para esta operación")
        return self.company_id

    # ------------------------------------------------------------------
    # Helpers de período
    # ------------------------------------------------------------------

    @staticmethod
    def _now(now: Optional[datetime] = None) -> datetime:
        return now or datetime.utcnow()

    @classmethod
    def current_week_start(cls, now: Optional[datetime] = None) -> datetime:
        today = cls._now(now).date()
        monday = today - timedelta(days=today.weekday())
        return datetime(monday.year, monday.month, monday.day)

    @staticmethod
    def week_bounds(period_start: datetime):
        """Lun 00:00:00 → Dom 23:59:59"""
        end = period_start + timedelta(days=6)
        return period_start, datetime(end.year, end.month, end.day, 23, 59, 59)

    @classmethod
    def current_month_start(cls, now: Optional[datetime] = None) -> datetime:
        today = cls._now(now)
        return datetime(today.year, today.month, 1)

    @staticmethod
    def month_bounds(period_start: datetime):
        """Día 1 00:00:00 → último día 23:59:59"""
        last_day = calendar.monthrange(period_start.year, period_start.month)[1]
        end = datetime(period_start.year, period_start.month, last_day, 23, 59, 59)
        return period_start, end

    @classmethod
    def current_year_start(cls, now: Optional[datetime] = None) -> datetime:
        return datetime(cls._now(now).year, 1, 1)

    @staticmethod
    def year_bounds(period_start: datetime):
        """1 de enero 00:00:00 → 31 de diciembre 23:59:59"""
        return datetime(period_start.year, 1, 1), datetime(period_start.year, 12, 31, 23, 59, 59)

    @classmethod
    def normalize_start(cls, period_type: str, value: datetime) -> datetime:
        """Inicio del período que contiene `value` (lunes, día 1 o 1 de enero)."""
        if period_type == PeriodType.YEARLY:
            return datetime(value.year, 1, 1)
        if period_type == PeriodType.MONTHLY:
            return datetime(value.year, value.month, 1)
        monday = value - timedelta(days=value.weekday())
        return datetime(monday.year, monday.month, monday.day)

    @classmethod
    def current_period_start(cls, period_type: str, now: Optional[datetime] = None) -> datetime:
        if period_type == PeriodType.YEARLY:
            return cls.current_year_start(now)
        if period_type == PeriodType.MONTHLY:
            return cls.current_month_start(now)
        return cls.current_week_start(now)

    @classmethod
    def period_bounds(cls, period_type: str, period_start: datetime):
        if period_type == PeriodType.YEARLY:
            return cls.year_bounds(period_start)
        if period_type == PeriodType.MONTHLY:
            return cls.month_bounds(period_start)
        return cls.week_bounds(period_start)

    @staticmethod
    def shift_period(period_type: str, period_start: datetime, steps: int) -> datetime:
        """Inicio del período `steps` posiciones antes (<0) o después (>0)."""
        if period_type == PeriodType.YEARLY:
            return datetime(period_start.year + steps, 1, 1)
        if period_type == PeriodType.MONTHLY:
            index = period_start.year * 12 + (period_start.month - 1) + steps
            return datetime(index // 12, index % 12 + 1, 1)
        return period_start + timedelta(days=7 * steps)

    @classmethod
    def previous_period_start(cls, period_type: str, now: Optional[datetime] = None) -> datetime:
        """Inicio del período cerrado justo antes del que está en curso (para congelar)."""
        return cls.shift_period(period_type, cls.current_period_start(period_type, now), -1)

    @classmethod
    def is_current_period(cls, period_type: str, period_start: datetime, now: Optional[datetime] = None) -> bool:
        return cls.normalize_start(period_type, period_start) == cls.current_period_start(period_type, now)

    @classmethod
    def period_label(cls, period_type: str, period_start: datetime) -> str:
        if period_type == PeriodType.YEARLY:
            return str(period_start.year)
        if period_type == PeriodType.MONTHLY:
            return f"{MONTH_NAMES[period_start.month - 1]} {period_start.year}"
        _, end = cls.week_bounds(period_start)
        return (
            f"{period_start.day} {MONTH_ABBR[period_start.month - 1]} – "
            f"{end.day} {MONTH_ABBR[end.month - 1]} {end.year}"
        )

    @classmethod
    def period(cls, period_type: str, period_start_str: str = "", now: Optional[datetime] = None) -> Period:
        """Resuelve tipo y fecha de los query params en un `Period` completo.

        Tipo desconocido -> semana. Fecha vacía o inválida -> período en curso.
        Cualquier fecha se normaliza al inicio de su período.
        """
        if not PeriodType.is_valid(period_type):
            period_type = PeriodType.DEFAULT

        current_start = cls.current_period_start(period_type, now)

        start = current_start
        if period_start_str:
            try:
                start = cls.normalize_start(period_type, datetime.strptime(period_start_str, "%Y-%m-%d"))
            except ValueError:
                start = current_start

        _, end = cls.period_bounds(period_type, start)
        next_start = cls.shift_period(period_type, start, 1)

        return Period(
            period_type=period_type,
            start=start,
            end=end,
            prev_start=cls.shift_period(period_type, start, -1),
            next_start=next_start,
            current_start=current_start,
            is_current=start == current_start,
            # No se navega a períodos futuros
            show_next=next_start <= current_start,
            label=cls.period_label(period_type, start),
        )

    # ------------------------------------------------------------------
    # Objetivos por período y % de cumplimiento
    # ------------------------------------------------------------------

    @staticmethod
    def objective_keys(period_type: str) -> tuple:
        return PerformanceObjectives.for_period(period_type)

    @staticmethod
    def metric_value(metrics: dict, key: str) -> int:
        """Valor total de una métrica. Contactos = venta + alquiler."""
        if key == "contactos":
            return (metrics.get("contactos_venta") or 0) + (metrics.get("contactos_alquiler") or 0)
        return metrics.get(key) or 0

    @staticmethod
    def breakdown(metrics: dict, key: str) -> Optional[dict]:
        """{'venta', 'alquiler', 'otros'} de una métrica, o None si no tiene desglose.

        Un snapshot anterior al desglose (columnas NULL) devuelve None: solo
        se conoce el total.
        """
        keys = BREAKDOWN_KEYS.get(key)
        if keys is None:
            return None
        sale, rent = metrics.get(keys[0]), metrics.get(keys[1])
        if sale is None and rent is None:
            return None
        sale, rent = sale or 0, rent or 0
        total = PerformanceReportService.metric_value(metrics, key)
        return {SALE: sale, RENT: rent, OTHER: max(total - sale - rent, 0)}

    @staticmethod
    def target_value(target, key: str) -> Optional[int]:
        if target is None:
            return None
        return getattr(target, PerformanceObjectives.target_field(key), None)

    @staticmethod
    def metric_pct(value: int, target_value: Optional[int]) -> Optional[int]:
        """% entero (sin tope) de un valor sobre su objetivo; None sin objetivo."""
        if not target_value:
            return None
        return max((value or 0) * 100 // target_value, 0)

    @classmethod
    def objective_rows(cls, metrics: dict, target, period_type: str) -> list:
        """Filas de las métricas con objetivo en el período, en el orden de la constante."""
        rows = []
        for key in cls.objective_keys(period_type):
            value = cls.metric_value(metrics, key)
            target_value = cls.target_value(target, key)
            pct = cls.metric_pct(value, target_value)
            rows.append({
                "key": key,
                "label": PerformanceObjectives.LABELS[key],
                "value": value,
                "target": target_value,
                "pct": pct,
                "bar_pct": min(pct, 100) if pct is not None else None,
            })
        return rows

    @classmethod
    def completion_pct(cls, metrics: dict, target, period_type: str) -> Optional[int]:
        """% global: media simple de los % de las métricas con objetivo del período.

        Solo cuentan las métricas con objetivo definido (> 0); cada % se
        limita a 100 para que un indicador sobrado no tape a otro. None si
        el período no tiene ningún objetivo.
        """
        pcts = [
            min(row["pct"], 100)
            for row in cls.objective_rows(metrics, target, period_type)
            if row["pct"] is not None
        ]
        if not pcts:
            return None
        return round(sum(pcts) / len(pcts))

    # ------------------------------------------------------------------
    # Cálculo de métricas
    # ------------------------------------------------------------------

    def _indicator_spec(self, indicator: str):
        """(columna agente, columna fecha, columna tipo, función que monta FROM/JOIN/WHERE)."""
        if indicator == "contactos":
            def build(query):
                return (
                    query.select_from(PropertyAlert)
                    .join(Property, Property.id == PropertyAlert.property_id)
                )
            return PropertyAlert.agent_id, PropertyAlert.created_at, PropertyAlert.business_type, build

        if indicator == "captaciones_crm":
            def build(query):
                return query.select_from(Property)
            return Property.agent_id, Property.market_entry_date, Property.business_type, build

        if indicator == "bajadas":
            def build(query):
                return (
                    query.select_from(PropertyPriceHistory)
                    .join(Property, Property.id == PropertyPriceHistory.property_id)
                    .filter(PropertyPriceHistory.new_price < PropertyPriceHistory.old_price)
                )
            return Property.agent_id, PropertyPriceHistory.created_at, Property.business_type, build

        if indicator == "cierres":
            def build(query):
                return (
                    query.select_from(AlertFollowUp)
                    .join(PropertyAlert, PropertyAlert.id == AlertFollowUp.alert_id)
                    .join(Property, Property.id == PropertyAlert.property_id)
                    .filter(AlertFollowUp.action_type == FollowUpActionType.CERRADO)
                )
            return PropertyAlert.agent_id, AlertFollowUp.created_at, closing_business_type(), build

        raise ValueError(f"Indicador desconocido: {indicator}")

    def grouped_counts(
        self,
        indicator: str,
        period_start: datetime,
        period_end: datetime,
        agent_ids,
        by_month: bool = False,
    ) -> dict:
        """Conteo por agente (y mes) y tipo: {(agent_id, mes|None): {'venta', 'alquiler', 'otros'}}.

        Una sola consulta agrupada, filtrada por la empresa del servicio
        (la de la propiedad); `mes` es 1..12 si `by_month`.
        """
        company_id = self._require_company()
        agent_ids = list(agent_ids)
        if not agent_ids:
            return {}

        agent_col, date_col, type_col, build = self._indicator_spec(indicator)

        group_cols = [agent_col.label("agent_id")]
        if by_month:
            group_cols.append(extract("month", date_col).label("month"))
        group_cols.append(business_kind(type_col).label("kind"))

        query = (
            build(self.db.query(*group_cols, func.count().label("total")))
            .filter(
                Property.company_id == company_id,
                agent_col.in_(agent_ids),
                date_col >= period_start,
                date_col <= period_end,
            )
            .group_by(*group_cols)
        )

        result = {}
        for row in query.all():
            key = (row.agent_id, int(row.month) if by_month else None)
            result.setdefault(key, _empty_counts())[row.kind] += row.total
        return result

    def calculate_metrics(
        self,
        agent_id: int,
        period_start: datetime,
        period_end: datetime,
    ) -> dict:
        """Métricas del agente en la empresa del servicio y el rango dado."""
        company_id = self._require_company()

        counts = {
            indicator: self.grouped_counts(indicator, period_start, period_end, [agent_id])
            .get((agent_id, None), _empty_counts())
            for indicator in BREAKDOWN_KEYS
        }

        # Visitas en las que participó el agente (principal o acompañante)
        # sobre propiedades de la empresa; el captador que no estuvo no suma.
        hojas_visita = (
            scope_visits(visits_for_agent(self.db.query(PropertyVisit), agent_id), company_id)
            .filter(
                PropertyVisit.created_at >= period_start,
                PropertyVisit.created_at <= period_end,
            )
            .count()
        )

        metrics = {
            # Contactos: solo venta y alquiler, como hasta ahora
            "contactos_venta": counts["contactos"][SALE],
            "contactos_alquiler": counts["contactos"][RENT],
            "hojas_visita": hojas_visita,
            "calidad_cartera": None,
        }
        for indicator in ("captaciones_crm", "bajadas", "cierres"):
            sale_key, rent_key = BREAKDOWN_KEYS[indicator]
            c = counts[indicator]
            metrics[indicator] = c[SALE] + c[RENT] + c[OTHER]
            metrics[sale_key] = c[SALE]
            metrics[rent_key] = c[RENT]
        return metrics

    @staticmethod
    def report_metrics(report: AgentPerformanceReport) -> dict:
        """Métricas congeladas de un snapshot (desglose None si es anterior a él)."""
        return {key: getattr(report, key) for key in SNAPSHOT_METRIC_KEYS}

    def metrics_for_period(self, agent_id: int, period: Period):
        """(métricas, snapshot): en vivo si el período está en curso o no está congelado."""
        report = self.get_report(agent_id, period.period_type, period.start)
        if period.is_current or report is None or not report.is_locked:
            metrics = self.calculate_metrics(agent_id, period.start, period.end)
        else:
            metrics = self.report_metrics(report)
        return metrics, report

    def agents_period_data(self, agents, period: Period) -> list:
        """Datos de la pestaña Rendimiento: una entrada por agente."""
        data = []
        for agent in agents:
            metrics, report = self.metrics_for_period(agent.id, period)
            target = self.get_target(agent.id, period.period_type, period.start)
            data.append({
                "agent": agent,
                "metrics": metrics,
                "target": target,
                "report": report,
                "values": {key: self.metric_value(metrics, key) for key in RESULT_METRICS},
                "details": {key: self.breakdown(metrics, key) for key in BREAKDOWN_KEYS},
                "objectives": {
                    row["key"]: row
                    for row in self.objective_rows(metrics, target, period.period_type)
                },
                "completion": self.completion_pct(metrics, target, period.period_type),
                "admin_notes": report.admin_notes if report else "",
                "is_locked": report.is_locked if report else False,
            })
        return data

    # ------------------------------------------------------------------
    # Evolución anual (pestaña Evolución)
    # ------------------------------------------------------------------

    def yearly_evolution(self, year: int, agents, now: Optional[datetime] = None) -> dict:
        """Series del año para las gráficas: por agente y mes, con desglose y objetivo anual.

        - Meses con snapshot mensual congelado: valores del snapshot.
        - Resto de meses (en curso o sin congelar): en vivo, una consulta
          agrupada por agente, mes y tipo por indicador.
        - Total anual: snapshot anual congelado si existe; si no, la suma
          de los meses.
        """
        self._require_company()
        agents = list(agents)
        agent_ids = [a.id for a in agents]
        year_start, year_end = self.year_bounds(datetime(year, 1, 1))

        live = {
            indicator: self.grouped_counts(indicator, year_start, year_end, agent_ids, by_month=True)
            for indicator in EVOLUTION_INDICATORS
        }

        monthly_snapshots = {}
        yearly_snapshots = {}
        targets = {}
        if agent_ids:
            for report in self._reports_query(agent_ids).filter(
                AgentPerformanceReport.period_type == PeriodType.MONTHLY,
                AgentPerformanceReport.period_start >= year_start,
                AgentPerformanceReport.period_start <= year_end,
                AgentPerformanceReport.is_locked.is_(True),
            ):
                monthly_snapshots[(report.agent_id, report.period_start.month)] = report

            for report in self._reports_query(agent_ids).filter(
                AgentPerformanceReport.period_type == PeriodType.YEARLY,
                AgentPerformanceReport.period_start == year_start,
                AgentPerformanceReport.is_locked.is_(True),
            ):
                yearly_snapshots[report.agent_id] = report

            for target in (
                self.db.query(AgentPerformanceTarget)
                .filter(
                    AgentPerformanceTarget.company_id == self.company_id,
                    AgentPerformanceTarget.agent_id.in_(agent_ids),
                    AgentPerformanceTarget.period_type == PeriodType.YEARLY,
                    AgentPerformanceTarget.period_start == year_start,
                )
            ):
                targets[target.agent_id] = target

        current_year = self.current_year_start(now).year
        current_month = self._now(now).month if year == current_year else None

        agents_data = []
        for agent in agents:
            monthly = {}
            totals = {}
            year_report = yearly_snapshots.get(agent.id)
            year_metrics = self.report_metrics(year_report) if year_report else None

            for indicator in EVOLUTION_INDICATORS:
                series = {kind: [0] * 12 for kind in KINDS}
                for month in range(1, 13):
                    snapshot = monthly_snapshots.get((agent.id, month))
                    if snapshot is not None and month != current_month:
                        counts = self._snapshot_counts(self.report_metrics(snapshot), indicator)
                    else:
                        counts = live[indicator].get((agent.id, month), _empty_counts())
                    for kind in KINDS:
                        series[kind][month - 1] = counts[kind]
                monthly[indicator] = series

                if year_metrics is not None:
                    total_counts = self._snapshot_counts(year_metrics, indicator)
                else:
                    total_counts = {kind: sum(series[kind]) for kind in KINDS}
                totals[indicator] = dict(
                    total_counts,
                    total=sum(total_counts.values()),
                    target=self.target_value(targets.get(agent.id), indicator),
                )

            completion = self.completion_pct(
                {indicator: totals[indicator]["total"] for indicator in EVOLUTION_INDICATORS},
                targets.get(agent.id),
                PeriodType.YEARLY,
            )
            agents_data.append({
                "id": agent.id,
                "name": agent.name,
                "totals": totals,
                "monthly": monthly,
                "completion": completion,
                "has_target": agent.id in targets,
            })

        return {
            "year": year,
            "months": [m[:3] for m in MONTH_NAMES],
            "indicators": {key: PerformanceObjectives.LABELS[key] for key in EVOLUTION_INDICATORS},
            "agents": agents_data,
        }

    @classmethod
    def _snapshot_counts(cls, metrics: dict, indicator: str) -> dict:
        """Conteos por tipo de un snapshot; sin desglose, el total va a 'otros'."""
        detail = cls.breakdown(metrics, indicator)
        if detail is None:
            return {SALE: 0, RENT: 0, OTHER: cls.metric_value(metrics, indicator)}
        return detail

    # ------------------------------------------------------------------
    # Persistencia
    # ------------------------------------------------------------------

    def _reports_query(self, agent_ids=None):
        query = self.db.query(AgentPerformanceReport).filter(
            AgentPerformanceReport.company_id == self._require_company()
        )
        if agent_ids is not None:
            query = query.filter(AgentPerformanceReport.agent_id.in_(list(agent_ids)))
        return query

    def get_report(
        self,
        agent_id: int,
        period_type: str,
        period_start: datetime,
    ) -> Optional[AgentPerformanceReport]:
        return (
            self._reports_query()
            .filter(
                AgentPerformanceReport.agent_id == agent_id,
                AgentPerformanceReport.period_type == period_type,
                AgentPerformanceReport.period_start == period_start,
            )
            .first()
        )

    def get_or_create_report(
        self,
        agent_id: int,
        period_type: str,
        period_start: datetime,
        period_end: datetime,
    ) -> AgentPerformanceReport:
        report = self.get_report(agent_id, period_type, period_start)
        if not report:
            report = AgentPerformanceReport(
                agent_id=agent_id,
                company_id=self._require_company(),
                period_type=period_type,
                period_start=period_start,
                period_end=period_end,
            )
            self.db.add(report)
        return report

    def freeze_report(
        self,
        agent_id: int,
        period_type: str,
        period_start: datetime,
        period_end: datetime,
    ) -> AgentPerformanceReport:
        """Calcula métricas y congela el reporte. Las notas se preservan."""
        metrics = self.calculate_metrics(agent_id, period_start, period_end)
        report = self.get_or_create_report(agent_id, period_type, period_start, period_end)

        for key, value in metrics.items():
            setattr(report, key, value)

        report.is_locked = True
        report.locked_at = datetime.utcnow()
        report.updated_at = datetime.utcnow()

        self.db.commit()
        return report

    def freeze_all_for_period(
        self,
        period_type: str,
        period_start: datetime,
        period_end: datetime,
    ):
        """Congela el período para los agentes de la empresa del servicio.

        Sin empresa (scheduler), recorre todas las empresas y, en cada una,
        sus agentes: un agente en las dos empresas obtiene dos snapshots.
        """
        if self.company_id is None:
            for company in self.db.query(Company).order_by(Company.id).all():
                PerformanceReportService(self.db, company.id).freeze_all_for_period(
                    period_type, period_start, period_end
                )
            return

        agents = scope_agents(self.db.query(Agent), self.company_id).order_by(Agent.id).all()
        for agent in agents:
            self.freeze_report(agent.id, period_type, period_start, period_end)

    # ------------------------------------------------------------------
    # Objetivos
    # ------------------------------------------------------------------

    def get_target(
        self,
        agent_id: int,
        period_type: str,
        period_start: datetime,
    ) -> Optional[AgentPerformanceTarget]:
        return (
            self.db.query(AgentPerformanceTarget)
            .filter(
                AgentPerformanceTarget.company_id == self._require_company(),
                AgentPerformanceTarget.agent_id == agent_id,
                AgentPerformanceTarget.period_type == period_type,
                AgentPerformanceTarget.period_start == period_start,
            )
            .first()
        )

    @staticmethod
    def allowed_target_fields(period_type: str) -> set:
        return {
            PerformanceObjectives.target_field(key)
            for key in PerformanceObjectives.for_period(period_type)
        }

    def save_target(
        self,
        agent_id: int,
        period_type: str,
        period_start: datetime,
        created_by: int,
        **kwargs,
    ) -> AgentPerformanceTarget:
        """Guarda los objetivos del período.

        Solo se escriben los campos con objetivo en ese tipo de período; el
        resto se ignora y lo que ya hubiera guardado se conserva.
        """
        allowed = self.allowed_target_fields(period_type)

        target = self.get_target(agent_id, period_type, period_start)
        if not target:
            target = AgentPerformanceTarget(
                agent_id=agent_id,
                company_id=self._require_company(),
                period_type=period_type,
                period_start=period_start,
                created_by=created_by,
            )
            self.db.add(target)

        for key, value in kwargs.items():
            if key in allowed:
                setattr(target, key, value)

        target.updated_at = datetime.utcnow()
        self.db.commit()
        return target

    def save_notes(
        self,
        agent_id: int,
        period_type: str,
        period_start: datetime,
        period_end: datetime,
        admin_notes: str,
    ) -> AgentPerformanceReport:
        report = self.get_or_create_report(agent_id, period_type, period_start, period_end)
        report.admin_notes = admin_notes
        report.updated_at = datetime.utcnow()
        self.db.commit()
        return report

