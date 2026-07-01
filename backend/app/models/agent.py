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

    email = Column(String, nullable=False, unique=True)

    dni = Column(String, nullable=True)

    phone = Column(String)

    zone = Column(String)

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