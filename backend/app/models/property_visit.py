from datetime import datetime

from sqlalchemy import Column
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy import DateTime
from sqlalchemy import Boolean
from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import relationship

from app.db.base import Base


class PropertyVisit(Base):

    __tablename__ = "property_visits"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    property_id = Column(
        Integer,
        ForeignKey("properties.id"),
        nullable=False
    )

    visitor_name = Column(
        String,
        nullable=False
    )

    dni = Column(
        String,
        nullable=True
    )

    phone = Column(
        String,
        nullable=True
    )

    email = Column(
        String,
        nullable=True
    )

    interest_level = Column(
        Integer,
        nullable=True
    )

    price_feedback = Column(
        String,
        nullable=True
    )

    location_feedback = Column(
        String,
        nullable=True
    )

    condition_feedback = Column(
        String,
        nullable=True
    )

    lighting_feedback = Column(
        String,
        nullable=True
    )

    elevator_feedback = Column(
        String,
        nullable=True
    )

    garage_feedback = Column(
        String,
        nullable=True
    )

    notes = Column(
        Text,
        nullable=True
    )

    visit_sheet_filename = Column(
        String,
        nullable=True
    )

    visit_sheet_filepath = Column(
        String,
        nullable=True
    )

    visit_sheet_generated_at = Column(
        DateTime,
        nullable=True
    )

    visit_sheet_sent_to = Column(
        String,
        nullable=True
    )

    # Campos de consentimiento de datos (RGPD)
    data_consent_accepted = Column(
        Boolean,
        default=False,
        nullable=False
    )

    data_consent_accepted_at = Column(
        DateTime,
        nullable=True
    )

    data_consent_ip = Column(
        String,
        nullable=True
    )

    data_consent_user_agent = Column(
        String,
        nullable=True
    )

    # Campos de firma digital
    signature_filename = Column(
        String,
        nullable=True
    )

    signature_filepath = Column(
        String,
        nullable=True
    )

    signature_captured_at = Column(
        DateTime,
        nullable=True
    )

    signature_ip = Column(
        String,
        nullable=True
    )

    # Estado del proceso de visita
    # Estados: 'draft', 'preview', 'signed', 'completed'
    visit_status = Column(
        String,
        default='completed',
        nullable=False
    )

    # Audit trail completo en formato JSON
    audit_trail = Column(
        JSON,
        nullable=True
    )

    created_by = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=True
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )

    # Relaciones
    property = relationship("Property", back_populates="visits")
    audit_logs = relationship("VisitAuditLog", back_populates="visit", cascade="all, delete-orphan")
    otp_verifications = relationship("VisitOTPVerification", back_populates="visit", cascade="all, delete-orphan")
