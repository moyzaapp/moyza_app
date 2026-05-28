from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship
from app.db.base import Base


class Client(Base):

    __tablename__ = "clients"

    id = Column(Integer, primary_key=True, index=True)

    name = Column(String, nullable=False)

    email = Column(String, nullable=False, unique=True)

    phone = Column(String)

    status = Column(String, default="Activo")

    properties = relationship(
        "Property",
        back_populates="client"
    )