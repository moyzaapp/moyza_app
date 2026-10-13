from datetime import datetime

from sqlalchemy import Column
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey

from sqlalchemy.orm import relationship

from app.db.base import Base


class AlertFollowUp(Base):

    __tablename__ = "alert_follow_ups"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    alert_id = Column(
        Integer,
        ForeignKey("property_alerts.id"),
        nullable=False,
        index=True
    )

    # Tipo de acción
    action_type = Column(
        String,
        nullable=False
    )

    notes = Column(
        Text,
        nullable=True
    )

    # Metadata adicional
    next_action_date = Column(
        DateTime,
        nullable=True
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )

    created_by = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False
    )

    # Relaciones
    alert = relationship(
        "PropertyAlert",
        back_populates="follow_ups"
    )
