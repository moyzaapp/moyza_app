# app/models/property_price_history.py

from sqlalchemy import Column
from sqlalchemy import Integer
from sqlalchemy import Float
from sqlalchemy import String
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey

from datetime import datetime

from app.db.base import Base


class PropertyPriceHistory(Base):

    __tablename__ = "property_price_history"

    id = Column(Integer, primary_key=True)

    property_id = Column(
        Integer,
        ForeignKey("properties.id"),
        nullable=False
    )

    old_price = Column(Float)

    new_price = Column(Float)

    reason = Column(String)

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )

    created_by = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=True
    )