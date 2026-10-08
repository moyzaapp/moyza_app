import calendar
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.agent_performance_report import AgentPerformanceReport
from app.models.agent_performance_target import AgentPerformanceTarget
from app.models.alert_follow_up import AlertFollowUp
from app.models.property import Property
from app.models.property_alert import PropertyAlert
from app.models.property_price_history import PropertyPriceHistory
from app.models.property_visit import PropertyVisit
from app.core.constants import FollowUpActionType
from app.services.company_scope import visits_for_agent


class PerformanceReportService:

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # Helpers de período
    # ------------------------------------------------------------------

    @staticmethod
    def current_week_start() -> datetime:
        today = datetime.utcnow().date()
        monday = today - timedelta(days=today.weekday())
        return datetime(monday.year, monday.month, monday.day)

    @staticmethod
    def week_bounds(period_start: datetime):
        """Lun 00:00:00 → Dom 23:59:59"""
        end = period_start + timedelta(days=6)
        return period_start, datetime(end.year, end.month, end.day, 23, 59, 59)

    @staticmethod
    def current_month_start() -> datetime:
        today = datetime.utcnow()
        return datetime(today.year, today.month, 1)

    @staticmethod
    def month_bounds(period_start: datetime):
        """Día 1 00:00:00 → último día 23:59:59"""
        last_day = calendar.monthrange(period_start.year, period_start.month)[1]
        end = datetime(period_start.year, period_start.month, last_day, 23, 59, 59)
        return period_start, end

    @staticmethod
    def is_current_period(period_type: str, period_start: datetime) -> bool:
        now = datetime.utcnow()
        if period_type == "WEEKLY":
            today = now.date()
            monday = today - timedelta(days=today.weekday())
            return period_start.date() == monday
        else:
            return period_start.year == now.year and period_start.month == now.month

    # ------------------------------------------------------------------
    # Cálculo de métricas
    # ------------------------------------------------------------------

    def calculate_metrics(
        self,
        agent_id: int,
        period_start: datetime,
        period_end: datetime,
    ) -> dict:
        db = self.db

        contactos_venta = (
            db.query(PropertyAlert)
            .filter(
                PropertyAlert.agent_id == agent_id,
                PropertyAlert.business_type.ilike("venta"),
                PropertyAlert.created_at >= period_start,
                PropertyAlert.created_at <= period_end,
            )
            .count()
        )

        contactos_alquiler = (
            db.query(PropertyAlert)
            .filter(
                PropertyAlert.agent_id == agent_id,
                PropertyAlert.business_type.ilike("alquiler"),
                PropertyAlert.created_at >= period_start,
                PropertyAlert.created_at <= period_end,
            )
            .count()
        )

        bajadas = (
            db.query(PropertyPriceHistory)
            .join(Property, Property.id == PropertyPriceHistory.property_id)
            .filter(
                Property.agent_id == agent_id,
                PropertyPriceHistory.new_price < PropertyPriceHistory.old_price,
                PropertyPriceHistory.created_at >= period_start,
                PropertyPriceHistory.created_at <= period_end,
            )
            .count()
        )

        captaciones_crm = (
            db.query(Property)
            .filter(
                Property.agent_id == agent_id,
                Property.market_entry_date >= period_start,
                Property.market_entry_date <= period_end,
            )
            .count()
        )

        cierres = (
            db.query(AlertFollowUp)
            .join(PropertyAlert, PropertyAlert.id == AlertFollowUp.alert_id)
            .filter(
                PropertyAlert.agent_id == agent_id,
                AlertFollowUp.action_type == FollowUpActionType.CERRADO,
                AlertFollowUp.created_at >= period_start,
                AlertFollowUp.created_at <= period_end,
            )
            .count()
        )

        # Visitas en las que participó el agente (principal o acompañante);
        # el captador de la propiedad que no estuvo no suma.
        hojas_visita = (
            visits_for_agent(db.query(PropertyVisit), agent_id)
            .filter(
                PropertyVisit.created_at >= period_start,
                PropertyVisit.created_at <= period_end,
            )
            .count()
        )

        return {
            "contactos_venta": contactos_venta,
            "contactos_alquiler": contactos_alquiler,
            "bajadas": bajadas,
            "captaciones_crm": captaciones_crm,
            "cierres": cierres,
            "hojas_visita": hojas_visita,
            "calidad_cartera": None,
        }

    # ------------------------------------------------------------------
    # Persistencia
    # ------------------------------------------------------------------

    def get_report(
        self,
        agent_id: int,
        period_type: str,
        period_start: datetime,
    ) -> Optional[AgentPerformanceReport]:
        return (
            self.db.query(AgentPerformanceReport)
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
        agents = self.db.query(Agent).all()
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
                AgentPerformanceTarget.agent_id == agent_id,
                AgentPerformanceTarget.period_type == period_type,
                AgentPerformanceTarget.period_start == period_start,
            )
            .first()
        )

    def save_target(
        self,
        agent_id: int,
        period_type: str,
        period_start: datetime,
        created_by: int,
        **kwargs,
    ) -> AgentPerformanceTarget:
        target = self.get_target(agent_id, period_type, period_start)
        if not target:
            target = AgentPerformanceTarget(
                agent_id=agent_id,
                period_type=period_type,
                period_start=period_start,
                created_by=created_by,
            )
            self.db.add(target)

        for key, value in kwargs.items():
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
