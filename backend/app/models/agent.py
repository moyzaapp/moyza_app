from sqlalchemy import Column
from sqlalchemy import Integer
from sqlalchemy import String

from sqlalchemy.orm import relationship

from app.db.base import Base


class Agent(Base):

    __tablename__ = "agents"

    id = Column(Integer, primary_key=True, index=True)

    name = Column(String, nullable=False)

    email = Column(String)

    phone = Column(String)

    zone = Column(String)

    properties = relationship(
        "Property",
        back_populates="agent"
    )