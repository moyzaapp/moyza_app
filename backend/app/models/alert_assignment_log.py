"""Historial de asignaciones de una alerta de comprador.

PLAN_ASIGNACION_ALERTAS.md §2.3. Una fila por cada vez que la alerta se
asigna: en el alta (`from_agent_id` vacío) y en cada reasignación. Las
alertas anteriores a esta tabla no tienen filas (nunca se reasignaron).
"""
from datetime import datetime

from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy.orm import relationship

from app.db.base import Base


class AlertAssignmentLog(Base):

    __tablename__ = "alert_assignment_logs"

    id = Column(Integer, primary_key=True, index=True)

    alert_id = Column(
        Integer,
        ForeignKey("property_alerts.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    from_agent_id = Column(Integer, ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)

    to_agent_id = Column(Integer, ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)

    assigned_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    reason = Column(String, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    alert = relationship("PropertyAlert", back_populates="assignment_logs")

    from_agent = relationship("Agent", foreign_keys=[from_agent_id])

    to_agent = relationship("Agent", foreign_keys=[to_agent_id])

    assigned_by_user = relationship("User", foreign_keys=[assigned_by])
