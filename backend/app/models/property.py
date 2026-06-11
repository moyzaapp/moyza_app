import datetime

from sqlalchemy import Column
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import ForeignKey
from sqlalchemy import Text
from sqlalchemy import Numeric
from sqlalchemy import DateTime
from sqlalchemy import Boolean

from sqlalchemy.orm import relationship

from app.core.constants import PropertyStatus
from app.db.base import Base


class Property(Base):

    __tablename__ = "properties"

    id = Column(Integer, primary_key=True, index=True)

    title = Column(String, nullable=False)

    address = Column(String)

    city = Column(String)

    property_type = Column(String, default="Casa")

    business_type = Column(String, default="Venta")

    price = Column(Numeric)

    status = Column(String, default=PropertyStatus.ACTIVE)

    description = Column(Text)

    fair_price = Column(Numeric, nullable=True)

    market_entry_date = Column(DateTime, default=datetime.datetime.utcnow)

    client_id = Column(
        Integer,
        ForeignKey("clients.id")
    )

    agent_id = Column(
        Integer,
        ForeignKey("agents.id")
    )

    auto_send_report = Column(
        Boolean,
        default=False
    )

    report_frequency = Column(
        String,
        nullable=True
    )

    report_day = Column(
        Integer,
        nullable=True
    )

    report_hour = Column(
        Integer,
        nullable=True
    )

    client = relationship(
        "Client",
        back_populates="properties"
    )

    agent = relationship(
        "Agent",
        back_populates="properties"
    )

    interactions = relationship(
        "PropertyInteraction",
        backref="property"
    )
