"""Inicio (/dashboard) por rol. PLAN_DASHBOARD_INICIO.md.

Entradas puras (sin `request`) para que se puedan probar sin la app:

- `period()`: período de los query params (semana / mes / año) con su
  navegación. Es el mismo `period()` de `PerformanceReportService`: una sola
  implementación para el Inicio y Resultados Comerciales.
- `agent_home(agent, period)`: Inicio del agente.

Reglas:
- Todas las consultas se limitan a la empresa del servicio.
- Las métricas salen de `PerformanceReportService` (misma fórmula que
  Resultados Comerciales); aquí solo se agrupan por lotes para no lanzar
  una consulta por agente.
- Objetivos según el tipo de período (`PerformanceObjectives`); el % global
  es la media de los % de esas métricas (`completion_pct`).
"""
from dataclasses import dataclass
from dataclasses import field
from datetime import date
from datetime import datetime
from datetime import time
from datetime import timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import and_
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.constants import AlertStatus
from app.core.constants import DashboardThresholds
from app.core.constants import FollowUpActionType
from app.core.constants import PerformanceObjectives
from app.core.constants import PeriodType
from app.core.constants import PropertyStatus
from app.models.agent import Agent
from app.models.agent_performance_report import AgentPerformanceReport
from app.models.agent_performance_target import AgentPerformanceTarget
from app.models.alert_follow_up import AlertFollowUp
from app.models.property import Property
from app.models.property_alert import PropertyAlert
from app.models.property_visit import PropertyVisit
from app.services.buyer_reminder_service import get_pending_buyers_by_agent
from app.services.company_scope import scope_agents
from app.services.performance_report_service import BREAKDOWN_KEYS
from app.services.performance_report_service import MONTH_ABBR
from app.services.performance_report_service import Period
from app.services.performance_report_service import PerformanceReportService
from app.services.performance_report_service import business_kind


MADRID = ZoneInfo("Europe/Madrid")

# Bloques de KPIs del agente: con objetivo posible (desglose venta / alquiler)
# y de actividad (solo resultado).
OBJECTIVE_GROUP = ("captaciones_crm", "bajadas", "cierres")
ACTIVITY_GROUP = ("hojas_visita", "contactos")

KPI_LABELS = {
    "captaciones_crm": "Captaciones",
    "bajadas": "Bajadas de precio",
    "cierres": "Cierres",
    "hojas_visita": "Hojas de visita",
    "contactos": "Contactos",
}

# Estado de propiedad -> tono (tokens.md: activa verde, pausada ámbar,
# vendida rojo, archivada gris; reservada "en curso" azul, retirada gris)
PORTFOLIO_TONES = {
    PropertyStatus.ACTIVE: "green",
    PropertyStatus.RESERVED: "blue",
    PropertyStatus.PAUSED: "amber",
    PropertyStatus.SOLD: "red",
    PropertyStatus.WITHDRAWN: "gray",
    PropertyStatus.ARCHIVED: "gray",
}
PORTFOLIO_ORDER = (
    PropertyStatus.ACTIVE,
    PropertyStatus.RESERVED,
    PropertyStatus.PAUSED,
    PropertyStatus.SOLD,
    PropertyStatus.WITHDRAWN,
    PropertyStatus.ARCHIVED,
)

WEEKDAYS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
MONTHS_LONG = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)


def madrid_now(now: Optional[datetime] = None) -> datetime:
    """Hora local de Madrid (naive). `now` se interpreta en UTC (naive)."""
    utc = (now or datetime.utcnow()).replace(tzinfo=ZoneInfo("UTC"))
    return utc.astimezone(MADRID).replace(tzinfo=None)


def long_date_es(value: date) -> str:
    """'miércoles 8 de octubre'."""
    return f"{WEEKDAYS[value.weekday()]} {value.day} de {MONTHS_LONG[value.month - 1]}"


def semaphore(pct: Optional[int]) -> str:
    """Tono del semáforo de cumplimiento (tokens.md): sin objetivo = gris."""
    if pct is None:
        return "gray"
    if pct >= 100:
        return "green"
    if pct >= 60:
        return "amber"
    return "red"


@dataclass
class Kpi:
    key: str
    label: str
    value: int
    previous: Optional[int]
    is_objective: bool = False
    target: Optional[int] = None
    pct: Optional[int] = None
    breakdown: Optional[dict] = None

    @property
    def delta(self) -> Optional[int]:
        if self.previous is None:
            return None
        return self.value - self.previous

    @property
    def tone(self) -> str:
        """Color del valor: semáforo si tiene objetivo definido; neutro si no."""
        return semaphore(self.pct) if self.is_objective else "gray"

    @property
    def bar_pct(self) -> Optional[int]:
        return min(self.pct, 100) if self.pct is not None else None


@dataclass
class TrendSeries:
    key: str
    label: str
    data: list
    color: str


@dataclass
class Trend:
    labels: list
    series: list = field(default_factory=list)
    stacked: bool = False

    @property
    def is_empty(self) -> bool:
        return all(sum(s.data) == 0 for s in self.series)

    def as_json(self) -> dict:
        return {
            "labels": self.labels,
            "stacked": self.stacked,
            "series": [
                {"key": s.key, "label": s.label, "data": s.data, "color": s.color}
                for s in self.series
            ],
        }


# Series categóricas sin significado fijo (charts.md), en orden
CATEGORICAL = ("#2563EB", "#F59E0B", "#10B981", "#8B5CF6", "#EF4444", "#6B7280")
TOTAL_COLOR = "#111827"
OTHERS_COLOR = "#9CA3AF"


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

    # ------------------------------------------------------------------
    # Métricas por lotes (todos los agentes de una vez)
    # ------------------------------------------------------------------

    def company_agents(self) -> list:
        return scope_agents(self.db.query(Agent), self.company_id).order_by(Agent.name.asc()).all()

    def _visit_counts(self, agent_ids, start: datetime, end: datetime) -> dict:
        """Hojas de visita por agente participante (principal + acompañante)."""
        counts = {}
        if not agent_ids:
            return counts
        for column in (PropertyVisit.agent_id, PropertyVisit.companion_agent_id):
            rows = (
                self.db.query(column, func.count(PropertyVisit.id))
                .join(Property, Property.id == PropertyVisit.property_id)
                .filter(
                    Property.company_id == self.company_id,
                    column.in_(agent_ids),
                    PropertyVisit.created_at >= start,
                    PropertyVisit.created_at <= end,
                )
                .group_by(column)
            )
            # Principal y acompañante nunca coinciden: la suma no duplica
            for agent_id, total in rows:
                counts[agent_id] = counts.get(agent_id, 0) + total
        return counts

    def team_metrics(self, agent_ids, period: Period) -> dict:
        """{agent_id: métricas} del período; snapshot congelado si el período está cerrado.

        Mismo criterio que `PerformanceReportService.metrics_for_period`, con
        una consulta agrupada por indicador en lugar de una por agente.
        """
        agent_ids = list(agent_ids)
        result = {}
        if not agent_ids:
            return result

        if not period.is_current:
            for report in self.perf._reports_query(agent_ids).filter(
                AgentPerformanceReport.period_type == period.period_type,
                AgentPerformanceReport.period_start == period.start,
                AgentPerformanceReport.is_locked.is_(True),
            ):
                result[report.agent_id] = self.perf.report_metrics(report)

        live_ids = [agent_id for agent_id in agent_ids if agent_id not in result]
        if live_ids:
            counts = {
                indicator: self.perf.grouped_counts(indicator, period.start, period.end, live_ids)
                for indicator in BREAKDOWN_KEYS
            }
            visits = self._visit_counts(live_ids, period.start, period.end)
            for agent_id in live_ids:
                result[agent_id] = self.perf.metrics_from_counts(
                    {indicator: counts[indicator].get((agent_id, None)) for indicator in BREAKDOWN_KEYS},
                    visits.get(agent_id, 0),
                )
        return result

    def team_targets(self, agent_ids, period: Period) -> dict:
        agent_ids = list(agent_ids)
        if not agent_ids:
            return {}
        return {
            target.agent_id: target
            for target in self.db.query(AgentPerformanceTarget).filter(
                AgentPerformanceTarget.company_id == self.company_id,
                AgentPerformanceTarget.agent_id.in_(agent_ids),
                AgentPerformanceTarget.period_type == period.period_type,
                AgentPerformanceTarget.period_start == period.start,
            )
        }

    # ------------------------------------------------------------------
    # KPIs
    # ------------------------------------------------------------------

    def build_kpis(self, keys, metrics: dict, previous: Optional[dict], target, period_type: str) -> list:
        objective_keys = set(self.perf.objective_keys(period_type))
        kpis = []
        for key in keys:
            value = self.perf.metric_value(metrics, key)
            is_objective = key in objective_keys
            target_value = self.perf.target_value(target, key) if is_objective else None
            kpis.append(Kpi(
                key=key,
                label=KPI_LABELS[key],
                value=value,
                previous=self.perf.metric_value(previous, key) if previous is not None else None,
                is_objective=is_objective,
                target=target_value,
                pct=self.perf.metric_pct(value, target_value),
                breakdown=self.perf.breakdown(metrics, key),
            ))
        return kpis

    @staticmethod
    def ranking(agent_id: int, completions: dict) -> Optional[dict]:
        """Puesto del agente por % global entre los agentes con objetivos (sin nombres).

        None si el agente no tiene % global o es el único con objetivos.
        Empates comparten puesto.
        """
        mine = completions.get(agent_id)
        ranked = [pct for pct in completions.values() if pct is not None]
        if mine is None or len(ranked) < 2:
            return None
        return {"position": 1 + sum(1 for pct in ranked if pct > mine), "total": len(ranked)}

    # ------------------------------------------------------------------
    # Inicio del agente
    # ------------------------------------------------------------------

    def agent_home(self, agent: Agent, period: Period, now: Optional[datetime] = None) -> dict:
        previous_period = self.previous_period(period, now=now)
        agents = self.company_agents()
        agent_ids = [a.id for a in agents]
        if agent.id not in agent_ids:
            agent_ids.append(agent.id)

        metrics_now = self.team_metrics(agent_ids, period)
        metrics_prev = self.team_metrics([agent.id], previous_period)
        targets = self.team_targets(agent_ids, period)

        metrics = metrics_now[agent.id]
        target = targets.get(agent.id)
        completions = {
            agent_id: self.perf.completion_pct(metrics_now[agent_id], targets.get(agent_id), period.period_type)
            for agent_id in agent_ids
        }

        report = self.perf.get_report(agent.id, period.period_type, period.start)

        return {
            "objective_kpis": self.build_kpis(
                OBJECTIVE_GROUP, metrics, metrics_prev[agent.id], target, period.period_type
            ),
            "activity_kpis": self.build_kpis(
                ACTIVITY_GROUP, metrics, metrics_prev[agent.id], target, period.period_type
            ),
            "objective_keys": self.perf.objective_keys(period.period_type),
            "has_target": target is not None,
            "completion": completions[agent.id],
            "ranking": self.ranking(agent.id, completions),
            "agenda": self.agenda(agent, now=now),
            "portfolio": self.portfolio(agent, now=now),
            "trend": self.agent_trend(agent, period, now=now),
            "admin_notes": (report.admin_notes or "").strip() if report else "",
            "pending_buyers": self.pending_buyers_for_agent(agent.id),
        }

    # ------------------------------------------------------------------
    # Agenda del agente
    # ------------------------------------------------------------------

    def _latest_follow_up_subquery(self):
        """Último seguimiento (por id) de cada alerta."""
        return (
            self.db.query(
                AlertFollowUp.alert_id.label("alert_id"),
                func.max(AlertFollowUp.id).label("follow_up_id"),
            )
            .group_by(AlertFollowUp.alert_id)
            .subquery()
        )

    def _agent_open_alerts(self, agent_id: int):
        return (
            self.db.query(PropertyAlert)
            .join(Property, Property.id == PropertyAlert.property_id)
            .filter(
                Property.company_id == self.company_id,
                PropertyAlert.agent_id == agent_id,
                PropertyAlert.status.in_([AlertStatus.PENDING, AlertStatus.IN_PROGRESS]),
            )
        )

    def agenda(self, agent: Agent, now: Optional[datetime] = None) -> dict:
        """Hoy y pendiente: próximas acciones vencidas o de hoy, sin leer y sin respuesta.

        `next_action_date` se guarda como la hora local que el agente escribe
        (input datetime-local), así que se compara con el final del día de
        hoy en Madrid.
        """
        local_now = madrid_now(now)
        end_of_today = datetime.combine(local_now.date(), time(23, 59, 59))
        start_of_today = datetime.combine(local_now.date(), time.min)
        latest = self._latest_follow_up_subquery()
        labels = FollowUpActionType.labels()

        due_query = (
            self._agent_open_alerts(agent.id)
            .join(latest, latest.c.alert_id == PropertyAlert.id)
            .join(AlertFollowUp, AlertFollowUp.id == latest.c.follow_up_id)
            .filter(
                AlertFollowUp.next_action_date.isnot(None),
                AlertFollowUp.next_action_date <= end_of_today,
            )
        )
        due_total = due_query.count()
        due_rows = (
            due_query.with_entities(PropertyAlert, AlertFollowUp)
            .order_by(AlertFollowUp.next_action_date.asc())
            .limit(DashboardThresholds.AGENDA_LIMIT)
            .all()
        )
        due = [
            {
                "alert_id": alert.id,
                "buyer_name": alert.lead_name or "Comprador sin nombre",
                "action_label": labels.get(follow_up.action_type, follow_up.action_type),
                "when": follow_up.next_action_date,
                "overdue": follow_up.next_action_date < start_of_today,
            }
            for alert, follow_up in due_rows
        ]

        unread = (
            self._agent_open_alerts(agent.id)
            .filter(PropertyAlert.status == AlertStatus.PENDING, PropertyAlert.read_at.is_(None))
            .count()
        )

        no_response_cutoff = (now or datetime.utcnow()) - timedelta(days=DashboardThresholds.NO_RESPONSE_DAYS)
        no_response = (
            self._agent_open_alerts(agent.id)
            .join(latest, latest.c.alert_id == PropertyAlert.id)
            .join(AlertFollowUp, AlertFollowUp.id == latest.c.follow_up_id)
            .filter(
                AlertFollowUp.action_type == FollowUpActionType.SIN_RESPUESTA,
                AlertFollowUp.created_at < no_response_cutoff,
            )
            .count()
        )

        return {
            "due": due,
            "due_total": due_total,
            "unread": unread,
            "no_response": no_response,
            "no_response_days": DashboardThresholds.NO_RESPONSE_DAYS,
            "is_empty": not due_total and not unread and not no_response,
        }

    def pending_buyers_for_agent(self, agent_id: int) -> list:
        """Compradores con más de BUYER_REMINDER_HOURS sin gestión (regla del email de las 06:00)."""
        pending = get_pending_buyers_by_agent(self.db, settings.BUYER_REMINDER_HOURS)
        buyers = pending.get((agent_id, self.company_id), [])
        return sorted(buyers, key=lambda b: b["hours_elapsed"], reverse=True)

    # ------------------------------------------------------------------
    # Cartera del agente
    # ------------------------------------------------------------------

    def portfolio(self, agent: Agent, now: Optional[datetime] = None) -> dict:
        rows = (
            self.db.query(Property.status, func.count(Property.id))
            .filter(Property.company_id == self.company_id, Property.agent_id == agent.id)
            .group_by(Property.status)
            .all()
        )
        by_status = {status or PropertyStatus.ACTIVE: total for status, total in rows}
        statuses = [
            {"status": status, "count": by_status[status], "tone": PORTFOLIO_TONES.get(status, "gray")}
            for status in PORTFOLIO_ORDER
            if by_status.get(status)
        ]
        # Estados fuera del catálogo (datos antiguos), al final en gris
        statuses += [
            {"status": status, "count": total, "tone": "gray"}
            for status, total in by_status.items()
            if status not in PORTFOLIO_ORDER and total
        ]

        cutoff = (now or datetime.utcnow()) - timedelta(days=DashboardThresholds.STALE_PROPERTY_DAYS)
        recent_visit = (
            self.db.query(PropertyVisit.id)
            .filter(PropertyVisit.property_id == Property.id, PropertyVisit.created_at >= cutoff)
            .exists()
        )
        stale_query = (
            self.db.query(Property)
            .filter(
                Property.company_id == self.company_id,
                Property.agent_id == agent.id,
                Property.status == PropertyStatus.ACTIVE,
                Property.available_clause(),
                # Las recién captadas aún no han tenido tiempo de recibir visitas
                (Property.market_entry_date.is_(None)) | (Property.market_entry_date < cutoff),
                ~recent_visit,
            )
        )
        return {
            "statuses": statuses,
            "total": sum(by_status.values()),
            "stale_total": stale_query.count(),
            "stale": stale_query.order_by(Property.market_entry_date.asc().nullsfirst()).limit(5).all(),
            "stale_days": DashboardThresholds.STALE_PROPERTY_DAYS,
        }

    # ------------------------------------------------------------------
    # Tendencias (una consulta agrupada por semana y tabla)
    # ------------------------------------------------------------------

    @staticmethod
    def trend_weeks(period: Period, weeks: int, now: Optional[datetime] = None) -> list:
        """Lunes de las `weeks` semanas que terminan en la del final del período (o la actual)."""
        anchor = min(period.end, now or datetime.utcnow())
        last_monday = PerformanceReportService.normalize_start(PeriodType.WEEKLY, anchor)
        return [last_monday - timedelta(weeks=weeks - 1 - i) for i in range(weeks)]

    @staticmethod
    def week_label(monday: datetime) -> str:
        return f"{monday.day} {MONTH_ABBR[monday.month - 1]}"

    def _weekly_contacts(self, agent_ids, start: datetime, end: datetime) -> dict:
        """{(agent_id, lunes): contactos venta + alquiler}."""
        week = func.date_trunc("week", PropertyAlert.created_at)
        kind = business_kind(PropertyAlert.business_type)
        rows = (
            self.db.query(PropertyAlert.agent_id, week.label("week"), func.count(PropertyAlert.id))
            .join(Property, Property.id == PropertyAlert.property_id)
            .filter(
                Property.company_id == self.company_id,
                PropertyAlert.agent_id.in_(list(agent_ids)),
                PropertyAlert.created_at >= start,
                PropertyAlert.created_at <= end,
                kind != "otros",
            )
            .group_by(PropertyAlert.agent_id, week)
        )
        return {(agent_id, monday): total for agent_id, monday, total in rows}

    def _weekly_visits(self, agent_ids, start: datetime, end: datetime) -> dict:
        """{(agent_id, lunes): hojas de visita} por agente participante."""
        week = func.date_trunc("week", PropertyVisit.created_at)
        result = {}
        for column in (PropertyVisit.agent_id, PropertyVisit.companion_agent_id):
            rows = (
                self.db.query(column, week.label("week"), func.count(PropertyVisit.id))
                .join(Property, Property.id == PropertyVisit.property_id)
                .filter(
                    Property.company_id == self.company_id,
                    column.in_(list(agent_ids)),
                    PropertyVisit.created_at >= start,
                    PropertyVisit.created_at <= end,
                )
                .group_by(column, week)
            )
            for agent_id, monday, total in rows:
                result[(agent_id, monday)] = result.get((agent_id, monday), 0) + total
        return result

    def agent_trend(self, agent: Agent, period: Period, now: Optional[datetime] = None) -> Trend:
        mondays = self.trend_weeks(period, DashboardThresholds.AGENT_TREND_WEEKS, now=now)
        start = mondays[0]
        end = mondays[-1] + timedelta(days=7) - timedelta(seconds=1)
        visits = self._weekly_visits([agent.id], start, end)
        contacts = self._weekly_contacts([agent.id], start, end)
        return Trend(
            labels=[self.week_label(m) for m in mondays],
            series=[
                TrendSeries("hojas_visita", KPI_LABELS["hojas_visita"],
                            [visits.get((agent.id, m), 0) for m in mondays], CATEGORICAL[0]),
                TrendSeries("contactos", KPI_LABELS["contactos"],
                            [contacts.get((agent.id, m), 0) for m in mondays], CATEGORICAL[1]),
            ],
        )
