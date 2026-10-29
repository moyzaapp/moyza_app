from datetime import datetime

from sqlalchemy import Boolean, Column, Integer, String, Text, DateTime, ForeignKey, Numeric, SmallInteger, JSON
from sqlalchemy.orm import relationship

from app.db.base import Base


class BuyerSearchCriteria(Base):

    __tablename__ = "buyer_search_criteria"

    id = Column(Integer, primary_key=True, index=True)

    buyer_id = Column(
        Integer,
        ForeignKey("buyers.id"),
        nullable=False,
        unique=True  # un perfil de búsqueda por comprador
    )

    agent_id = Column(
        Integer,
        ForeignKey("agents.id"),
        nullable=True
    )

    # Ubicación en cascada País → Provincia → Población → Zona
    # (PLAN_PERFIL_UBICACION.md). País y provincia son un solo valor; la
    # provincia de una propiedad se deduce de su código postal (app/core/geo.py).
    # Poblaciones y zonas son listas JSON de valores de las propiedades
    # existentes; lista vacía (o nula) = "Todas".
    country = Column(String, nullable=True)    # "España"
    province = Column(String, nullable=True)   # "Jaén"
    zones = Column(JSON, nullable=True)   # ["Eixample", "Gràcia", ...]
    cities = Column(JSON, nullable=True)  # ["Barcelona", "Hospitalet", ...]

    # Tipo de inmueble y operación
    property_type = Column(String, nullable=True)   # Casa, Piso, Local…
    business_type = Column(String, nullable=True)   # Venta, Alquiler

    # Rango de precio
    min_price = Column(Numeric, nullable=True)
    max_price = Column(Numeric, nullable=True)

    # Habitaciones y baños
    min_bedrooms = Column(SmallInteger, nullable=True)
    max_bedrooms = Column(SmallInteger, nullable=True)
    min_bathrooms = Column(SmallInteger, nullable=True)

    # Ascensor (PLAN_PERFIL_ZONAS.md, fase C): NULL = indiferente, True = con
    # ascensor, False = sin ascensor. Se cruza con `Property.num_ascensores`.
    elevator = Column(Boolean, nullable=True)

    # Superficie
    min_m2 = Column(Numeric, nullable=True)
    max_m2 = Column(Numeric, nullable=True)

    # Requisitos adicionales en texto libre
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relaciones
    buyer = relationship("Buyer", back_populates="search_criteria")
    agent = relationship("Agent")
