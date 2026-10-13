from datetime import datetime

from sqlalchemy import Column
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey

from sqlalchemy.orm import relationship

from app.db.base import Base


class PropertyAlert(Base):

    __tablename__ = "property_alerts"

    id = Column(Integer, primary_key=True, index=True)

    property_id = Column(
        Integer,
        ForeignKey("properties.id"),
        nullable=False
    )

    agent_id = Column(
        Integer,
        ForeignKey("agents.id"),
        nullable=False
    )

    # Información del interesado
    lead_name = Column(
        String,
        nullable=False
    )

    lead_phone = Column(
        String,
        nullable=True
    )

    lead_email = Column(
        String,
        nullable=True
    )

    source = Column(
        String,
        nullable=True
    )

    # Descripción de la alerta
    alert_type = Column(
        String,
        default="LEAD_INTERES"
    )

    message = Column(
        Text,
        nullable=True
    )

    priority = Column(
        String,
        default="NORMAL"
    )

    # Estado y seguimiento
    status = Column(
        String,
        default="PENDING"
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )

    read_at = Column(
        DateTime,
        nullable=True
    )

    completed_at = Column(
        DateTime,
        nullable=True
    )

    # Auditoría
    created_by = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False
    )

    buyer_id = Column(
        Integer,
        ForeignKey("buyers.id"),
        nullable=True
    )

    business_type = Column(
        String,
        nullable=True
    )

    # Asignación (PLAN_ASIGNACION_ALERTAS.md §2.3). `agent_id` es el agente que
    # trabaja la alerta; puede no ser el captador de la propiedad. Las alertas
    # anteriores a la asignación manual tienen assigned_at = created_at y
    # assigned_by = created_by.
    assigned_by = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True
    )

    assigned_at = Column(
        DateTime,
        nullable=True
    )

    previous_agent_id = Column(
        Integer,
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True
    )

    assignment_reason = Column(
        String,
        nullable=True
    )

    # Relaciones
    property = relationship(
        "Property",
        backref="alerts"
    )

    # `foreign_keys` explícito: property_alerts tiene dos FK a agents
    agent = relationship(
        "Agent",
        foreign_keys=[agent_id],
        backref="alerts"
    )

    previous_agent = relationship(
        "Agent",
        foreign_keys=[previous_agent_id]
    )

    assigned_by_user = relationship(
        "User",
        foreign_keys=[assigned_by]
    )

    assignment_logs = relationship(
        "AlertAssignmentLog",
        back_populates="alert",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AlertAssignmentLog.created_at.desc(), AlertAssignmentLog.id.desc()"
    )

    buyer = relationship(
        "Buyer",
        back_populates="alerts"
    )

    follow_ups = relationship(
        "AlertFollowUp",
        back_populates="alert",
        cascade="all, delete-orphan"
    )
