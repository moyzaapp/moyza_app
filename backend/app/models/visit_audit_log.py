from datetime import datetime

from sqlalchemy import Column
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import relationship

from app.db.base import Base


class VisitAuditLog(Base):
    """
    Registro de auditoría detallado para trazabilidad legal de visitas.

    Eventos típicos:
    - 'draft_created': Visita creada en estado borrador
    - 'preview_viewed': Cliente visualizó vista previa del documento
    - 'consent_accepted': Cliente aceptó términos RGPD
    - 'signature_captured': Firma digital capturada
    - 'pdf_generated': PDF final generado
    - 'pdf_sent': PDF enviado por WhatsApp
    - 'visit_completed': Proceso completado
    """

    __tablename__ = "visit_audit_logs"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    visit_id = Column(
        Integer,
        ForeignKey("property_visits.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    event_type = Column(
        String,
        nullable=False
    )

    event_data = Column(
        JSON,
        nullable=True
    )

    timestamp = Column(
        DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    ip_address = Column(
        String,
        nullable=True
    )

    user_agent = Column(
        String,
        nullable=True
    )

    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True
    )

    # Relaciones
    visit = relationship("PropertyVisit", back_populates="audit_logs")
