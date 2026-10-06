import datetime

from sqlalchemy import Column
from sqlalchemy import Integer
from sqlalchemy import SmallInteger
from sqlalchemy import String
from sqlalchemy import ForeignKey
from sqlalchemy import Text
from sqlalchemy import Numeric
from sqlalchemy import Date
from sqlalchemy import DateTime
from sqlalchemy import Boolean
from sqlalchemy import func
from sqlalchemy import or_

from sqlalchemy.orm import relationship

from app.core.constants import PropertyStatus
from app.db.base import Base


class Property(Base):

    __tablename__ = "properties"

    id = Column(Integer, primary_key=True, index=True)

    # Identificadores de la tabla externa de propiedades.
    # Por ahora `referencia` es informativa: no se usa como clave de
    # sincronización ni tiene restricción de unicidad.
    referencia = Column(String, index=True, nullable=True)

    codigo = Column(String, nullable=True)

    ref_catastral = Column(String, nullable=True)

    title = Column(String, nullable=False) # referencia

    address = Column(String) #direccion

    city = Column(String) #poblacion

    property_type = Column(String, default="Casa") #tipo_inmueble

    business_type = Column(String, default="Venta") #operacion

    price = Column(Numeric) #precio

    status = Column(String, default=PropertyStatus.ACTIVE)

    description = Column(Text) #observaciones

    fair_price = Column(Numeric, nullable=True)

    market_entry_date = Column(DateTime, default=datetime.datetime.utcnow) #fecha_alta

    # Estado de conservación del inmueble (Nuevo, A reformar...).
    # No confundir con `status`, que es el estado comercial.
    estado_inmueble = Column(String, nullable=True)

    situacion = Column(String, nullable=True)

    pais = Column(String, nullable=True)

    zona = Column(String, nullable=True)

    cod_postal = Column(String(5), nullable=True)

    moneda = Column(String(3), nullable=False, default="EUR", server_default="EUR")

    m2_utiles = Column(Numeric(10, 2), nullable=True)

    m2_construidos = Column(Numeric(10, 2), nullable=True)

    planta = Column(String, nullable=True)

    num_dormitorios = Column(SmallInteger, nullable=True)

    num_banos_aseos = Column(SmallInteger, nullable=True)

    num_salones = Column(SmallInteger, nullable=True)

    num_terrazas = Column(SmallInteger, nullable=True)

    num_armarios = Column(SmallInteger, nullable=True)

    num_garaje_aparcam = Column(SmallInteger, nullable=True)

    num_ascensores = Column(SmallInteger, nullable=True)

    num_despachos = Column(SmallInteger, nullable=True)

    num_locales = Column(SmallInteger, nullable=True)

    llaves = Column(Text, nullable=True)

    mandato_acuerdo = Column(Text, nullable=True)

    fecha_alta = Column(Date, nullable=True)

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

    visits = relationship(
        "PropertyVisit",
        back_populates="property"
    )

    # -----------------------------------------------------------------
    # Disponibilidad: una propiedad es "No disponible" cuando su
    # estado_inmueble (texto libre) dice "No disponible", sin importar
    # mayúsculas ni espacios. Por ahora las selecciones de trabajo
    # (visitas, alertas, informes, envíos automáticos) solo usan las
    # disponibles.
    # -----------------------------------------------------------------

    NOT_AVAILABLE_STATE = "no disponible"

    @classmethod
    def not_available_clause(cls):
        """Condición SQL: la propiedad está marcada como No disponible."""
        return func.lower(func.trim(cls.estado_inmueble)) == cls.NOT_AVAILABLE_STATE

    @classmethod
    def available_clause(cls):
        """Condición SQL: la propiedad NO está marcada como No disponible."""
        return or_(cls.estado_inmueble.is_(None), ~cls.not_available_clause())

    @property
    def is_available(self):
        return (self.estado_inmueble or "").strip().lower() != self.NOT_AVAILABLE_STATE
