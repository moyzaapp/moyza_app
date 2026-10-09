"""Notificaciones in-app (PLAN_DASHBOARD_INICIO.md §4).

Solo viven dentro de la app (campana del navbar, página /notifications y
bloque "Novedades" del Inicio): nunca se envían por email ni WhatsApp.
Cada notificación es de un usuario y de una empresa; solo se ve con esa
empresa activa.
"""
from datetime import datetime

from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy.orm import relationship

from app.db.base import Base


class Notification(Base):

    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)

    # Catálogo en notification_service.NotificationKind
    kind = Column(String, nullable=False)

    title = Column(String, nullable=False)

    body = Column(String, nullable=True)

    # Ruta interna a la que lleva ("/properties/42")
    url = Column(String, nullable=True)

    actor_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Objeto que la origina ("visit", "alert", "performance_report"...)
    entity_type = Column(String, nullable=True)
    entity_id = Column(Integer, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    read_at = Column(DateTime, nullable=True)

    user = relationship("User", foreign_keys=[user_id])
    actor = relationship("User", foreign_keys=[actor_user_id])

    __table_args__ = (
        # Badge (no leídas) y listado del usuario
        Index("ix_notifications_user_read_created", "user_id", "read_at", "created_at"),
    )
