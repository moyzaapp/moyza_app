"""Comprador compatible con una propiedad nueva.

PLAN_COMPRADORES_COMPATIBLES_PROPIEDAD_NUEVA.md §4.2. Cuando el captador (o el
admin) da el OK a una propiedad nueva (PLAN_REVISION_PROPIEDADES_NUEVAS.md),
`property_match_service.match_property` cruza la propiedad con los perfiles de
las alertas abiertas de todos los agentes y de las dos empresas y guarda aquí
una fila por alerta que encaja. Es el historial de cruces por comprador (base
de la futura «Reserva de compradores», §6).

Una fila por propiedad y alerta (`(property_id, alert_id)` único: un segundo
cruce no duplica ni vuelve a avisar). El estado del envío al comprador NO se
guarda aquí: «Enviada el …» sale de los seguimientos `PROPIEDAD_ENVIADA` con
`property_id` (`routes/alerts.py::sent_dates`), como en las sugerencias.
"""
from datetime import datetime

from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import relationship

from app.db.base import Base


class PropertyBuyerMatch(Base):

    __tablename__ = "property_buyer_matches"
    __table_args__ = (
        UniqueConstraint("property_id", "alert_id", name="uq_property_buyer_matches_property_alert"),
        # Página de compatibles y bloque del detalle (por propiedad); avisos por agente
        Index("ix_property_buyer_matches_property_id", "property_id"),
        Index("ix_property_buyer_matches_agent_id", "agent_id"),
    )

    id = Column(Integer, primary_key=True, index=True)

    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False)

    alert_id = Column(Integer, ForeignKey("property_alerts.id", ondelete="CASCADE"), nullable=False)

    # Agente de la alerta al cruzar (a quién se avisó)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)

    # Empresa de la alerta: donde el agente ve el aviso (vista unificada: con su distintivo)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    # Cuándo se cruzó
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Aviso al agente; nulo si el agente no tiene usuario activo en la app
    notified_at = Column(DateTime, nullable=True)

    property = relationship("Property")
    alert = relationship("PropertyAlert")
    agent = relationship("Agent")
    company = relationship("Company")
