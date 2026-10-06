from datetime import datetime

from sqlalchemy import Column
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import DateTime

from sqlalchemy.orm import relationship

from app.db.base import Base


class Agent(Base):

    __tablename__ = "agents"

    id = Column(Integer, primary_key=True, index=True)

    name = Column(String, nullable=False)

    email = Column(String, nullable=True, unique=True)

    dni = Column(String, nullable=True)

    phone = Column(String, nullable=True)

    zone = Column(String, nullable=True)

    company = Column(String, nullable=True)

    # Campos de firma digital del agente
    signature_filename = Column(
        String,
        nullable=True
    )

    signature_filepath = Column(
        String,
        nullable=True
    )

    signature_uploaded_at = Column(
        DateTime,
        nullable=True
    )

    properties = relationship(
        "Property",
        back_populates="agent"
    )

    # Empresas para las que trabaja el agente (puede ser más de una).
    # Sustituye progresivamente al texto libre de `company`.
    companies = relationship(
        "Company",
        secondary="agent_companies",
        back_populates="agents"
    )