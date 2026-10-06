from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship
from app.db.base import Base


class Client(Base):

    __tablename__ = "clients"

    id = Column(Integer, primary_key=True, index=True)

    name = Column(String, nullable=False)

    email = Column(String, nullable=True, unique=True)

    phone = Column(String, nullable=False)

    status = Column(String, default="Activo")

    properties = relationship(
        "Property",
        back_populates="client"
    )

    # Empresas en las que el cliente tiene inmuebles (puede ser más de una)
    companies = relationship(
        "Company",
        secondary="client_companies",
        back_populates="clients"
    )