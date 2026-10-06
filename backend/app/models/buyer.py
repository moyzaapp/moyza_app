from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from app.db.base import Base


class Buyer(Base):

    __tablename__ = "buyers"

    id = Column(Integer, primary_key=True, index=True)

    name = Column(String, nullable=False)

    phone = Column(String, nullable=True)

    email = Column(String, nullable=True)

    notes = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Empresa en la que se captó al comprador (MOYZA o MOES)
    company_id = Column(
        Integer,
        ForeignKey("companies.id"),
        nullable=False,
        index=True
    )

    company = relationship("Company", back_populates="buyers")

    alerts = relationship(
        "PropertyAlert",
        back_populates="buyer",
        cascade="all, delete-orphan"
    )

    search_criteria = relationship(
        "BuyerSearchCriteria",
        back_populates="buyer",
        uselist=False,  # one-to-one
        cascade="all, delete-orphan"
    )
