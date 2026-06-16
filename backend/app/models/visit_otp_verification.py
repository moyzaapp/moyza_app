from datetime import datetime

from sqlalchemy import Column
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy.orm import relationship

from app.db.base import Base


class VisitOTPVerification(Base):
    """
    Tabla para verificación OTP de visitas (preparación futura).

    No se usará inmediatamente, pero está lista para cuando
    se integre Twilio u otro proveedor de SMS/WhatsApp.
    """

    __tablename__ = "visit_otp_verifications"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    visit_id = Column(
        Integer,
        ForeignKey("property_visits.id", ondelete="CASCADE"),
        nullable=False
    )

    phone_number = Column(
        String,
        nullable=False
    )

    otp_code = Column(
        String,
        nullable=False
    )

    otp_sent_at = Column(
        DateTime,
        nullable=False
    )

    otp_verified_at = Column(
        DateTime,
        nullable=True
    )

    otp_expires_at = Column(
        DateTime,
        nullable=False
    )

    verification_method = Column(
        String,
        nullable=False
    )

    status = Column(
        String,
        default='pending',
        nullable=False
    )

    attempts = Column(
        Integer,
        default=0,
        nullable=False
    )

    max_attempts = Column(
        Integer,
        default=3,
        nullable=False
    )

    # Relaciones
    visit = relationship("PropertyVisit", back_populates="otp_verifications")
