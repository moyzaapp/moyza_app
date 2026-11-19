"""Propiedades adicionales de interés de una alerta (PLAN_ALERTA_VARIAS_PROPIEDADES.md).

La primera propiedad de interés sigue en `property_alerts.property_id` (así el
listado, los duplicados, los avisos y la trazabilidad no cambian); aquí van las
demás que el agente marca en la Propuesta. Lista completa:
`PropertyAlert.interest_properties`.
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, UniqueConstraint
from sqlalchemy.orm import relationship

from app.db.base import Base


class AlertProperty(Base):

    __tablename__ = "alert_properties"

    __table_args__ = (
        UniqueConstraint("alert_id", "property_id", name="uq_alert_properties_alert_property"),
        Index("ix_alert_properties_property_id", "property_id"),
    )

    id = Column(Integer, primary_key=True, index=True)

    alert_id = Column(
        Integer,
        ForeignKey("property_alerts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    property_id = Column(
        Integer,
        ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False,
    )

    added_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    added_by = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    alert = relationship("PropertyAlert", back_populates="extra_properties")
    property = relationship("Property")
