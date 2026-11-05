"""Cierres registrados a mano por el administrador.

PLAN_CIERRES_MANUALES_Y_DIRECCIONES.md §2.1. Un cierre es la firma o venta
de una propiedad; hasta que exista una sección de operaciones, el admin lo
apunta aquí. Un registro por cierre y por agente: si cierran dos agentes, se
meten dos registros. Es el resultado que cuenta la métrica "Cierres"
(`PerformanceReportService._indicator_spec("cierres")`).
"""
from datetime import datetime

from sqlalchemy import Column
from sqlalchemy import Date
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy.orm import relationship

from app.db.base import Base


class Closing(Base):

    __tablename__ = "closings"
    __table_args__ = (
        Index("ix_closings_company_agent_closed_on", "company_id", "agent_id", "closed_on"),
    )

    id = Column(Integer, primary_key=True, index=True)

    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False)

    # "Venta" / "Alquiler" (BusinessType), como `properties.business_type`
    business_type = Column(String, nullable=False)

    # Fecha de la firma (sin hora): decide el período en que cuenta
    closed_on = Column(Date, nullable=False)

    # Opcional: la propiedad puede no estar en el CRM o borrarse después
    property_id = Column(
        Integer,
        ForeignKey("properties.id", ondelete="SET NULL"),
        nullable=True,
    )

    notes = Column(Text, nullable=True)

    created_by = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    agent = relationship("Agent")
    property = relationship("Property")
    creator = relationship("User")
