from datetime import datetime

from sqlalchemy import Column
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
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
