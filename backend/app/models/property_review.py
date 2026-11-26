"""Revisión de una propiedad nueva por su captador.

PLAN_REVISION_PROPIEDADES_NUEVAS.md §4.1. La ETL del CRM escribe en
`properties` desde fuera de la app y la tabla no tiene `created_at`, así que
«propiedad nueva» = propiedad sin fila aquí (P1). La migración crea una fila
`skipped` para todas las que ya existían al desplegar; a partir de ahí el job
`register_property_reviews` (y el alta del admin, al momento) crea una fila
`pending` para cada propiedad activa con captador (P3).

Una fila por propiedad (`property_id` único). Estados y transiciones en
`PropertyReviewStatus` (core/constants.py) y en
`app/services/property_review_service.py`.
"""
from datetime import datetime

from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import SmallInteger
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy.orm import relationship

from app.db.base import Base


class PropertyReview(Base):

    __tablename__ = "property_reviews"
    __table_args__ = (
        # Listas de pendientes por captador y contadores del admin
        Index("ix_property_reviews_status_agent", "status", "agent_id"),
    )

    id = Column(Integer, primary_key=True, index=True)

    property_id = Column(
        Integer,
        ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    # Captador al que se pidió la revisión (el de la propiedad al registrarla)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)

    # PropertyReviewStatus: pending · issues · fixed · ok · skipped
    status = Column(String, nullable=False)

    # Lo que el captador pidió revisar (obligatorio al marcar «Revisar»)
    agent_comment = Column(Text, nullable=True)

    # Qué corrigió el admin (opcional)
    admin_comment = Column(Text, nullable=True)

    # Veces que el captador marcó «Revisar»
    rounds = Column(SmallInteger, nullable=False, default=0, server_default="0")

    # Cuándo la app vio la propiedad
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Primer aviso al captador y recordatorio (solo uno, P5)
    notified_at = Column(DateTime, nullable=True)
    reminded_at = Column(DateTime, nullable=True)

    # Último «Revisar» del captador
    flagged_at = Column(DateTime, nullable=True)

    # Última corrección del admin
    fixed_at = Column(DateTime, nullable=True)
    fixed_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # OK definitivo (captador o admin, P4)
    ok_at = Column(DateTime, nullable=True)
    ok_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    property = relationship("Property", back_populates="review")
    agent = relationship("Agent")
    fixed_by_user = relationship("User", foreign_keys=[fixed_by])
    ok_by_user = relationship("User", foreign_keys=[ok_by])
