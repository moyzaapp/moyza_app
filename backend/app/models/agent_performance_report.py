from datetime import datetime

from sqlalchemy import Column
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Float
from sqlalchemy import Text
from sqlalchemy import Boolean
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy.orm import relationship

from app.db.base import Base


class AgentPerformanceReport(Base):

    __tablename__ = "agent_performance_reports"

    id = Column(Integer, primary_key=True, index=True)

    agent_id = Column(
        Integer,
        ForeignKey("agents.id"),
        nullable=False
    )

    # Métricas de la empresa en la que se calcularon (las de sus propiedades)
    company_id = Column(
        Integer,
        ForeignKey("companies.id"),
        nullable=False,
        index=True
    )

    period_type = Column(String, nullable=False)   # WEEKLY / MONTHLY / YEARLY
    period_start = Column(DateTime, nullable=False)
    period_end = Column(DateTime, nullable=False)

    # Métricas calculadas
    contactos_venta = Column(Integer, default=0)
    contactos_alquiler = Column(Integer, default=0)
    bajadas = Column(Integer, default=0)
    captaciones_crm = Column(Integer, default=0)
    cierres = Column(Integer, default=0)
    hojas_visita = Column(Integer, default=0)
    calidad_cartera = Column(Float, nullable=True)

    # Desglose venta / alquiler. NULL en los snapshots anteriores al desglose:
    # su total sigue en la columna agregada y se muestra como "otros".
    captaciones_venta = Column(Integer, nullable=True)
    captaciones_alquiler = Column(Integer, nullable=True)
    bajadas_venta = Column(Integer, nullable=True)
    bajadas_alquiler = Column(Integer, nullable=True)
    cierres_venta = Column(Integer, nullable=True)
    cierres_alquiler = Column(Integer, nullable=True)

    # Congelamiento: True cuando el período cerró y las métricas son finales
    is_locked = Column(Boolean, default=False)
    locked_at = Column(DateTime, nullable=True)

    # Observaciones del admin (siempre editables, incluso después del cierre)
    admin_notes = Column(Text, nullable=True)
    audio_file = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    agent = relationship("Agent", backref="performance_reports")
