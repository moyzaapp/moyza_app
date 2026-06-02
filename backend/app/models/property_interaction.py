from datetime import datetime

from sqlalchemy import Column
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey

from app.db.base import Base


class PropertyInteraction(Base):

    __tablename__ = "property_interactions"

    id = Column(
        Integer,
        primary_key=True
    )

    property_id = Column(
        Integer,
        ForeignKey("properties.id"),
        nullable=False
    )

    interaction_type = Column(
        String,
        nullable=False
    )

    contact_name = Column(
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

    source = Column(
        String,
        nullable=True
    )

    notes = Column(
        Text,
        nullable=True
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )

    created_by = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=True
    )