from sqlalchemy import Column
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import ForeignKey
from sqlalchemy import Text
from sqlalchemy import DateTime

from sqlalchemy.orm import relationship

from datetime import datetime

from app.db.base import Base


class Report(Base):

    __tablename__ = "reports"

    id = Column(Integer, primary_key=True, index=True)

    property_id = Column(
        Integer,
        ForeignKey("properties.id")
    )

    uploaded_by = Column(
        Integer,
        ForeignKey("users.id")
    )

    report_type = Column(String)

    filename = Column(String)

    filepath = Column(String)

    notes = Column(Text)

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )

    property = relationship("Property")

    user = relationship("User")