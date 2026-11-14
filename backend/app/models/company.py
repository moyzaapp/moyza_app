from datetime import datetime

from sqlalchemy import Column
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy import Boolean
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import Table

from sqlalchemy.orm import relationship

from app.db.base import Base


# =========================================================
# Tablas de pertenencia (N:M)
#
# Usuarios, agentes y clientes pueden trabajar con ambas
# empresas, por eso no llevan un company_id directo sino
# una fila por cada empresa a la que pertenecen.
# =========================================================

user_companies = Table(
    "user_companies",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("company_id", Integer, ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True),
)

agent_companies = Table(
    "agent_companies",
    Base.metadata,
    Column("agent_id", Integer, ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True),
    Column("company_id", Integer, ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True),
)

client_companies = Table(
    "client_companies",
    Base.metadata,
    Column("client_id", Integer, ForeignKey("clients.id", ondelete="CASCADE"), primary_key=True),
    Column("company_id", Integer, ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True),
)


class Company(Base):
    """Empresa (marca) interna: MOYZA o MOES PREMIUM.

    Concentra la identidad legal y de marca que antes estaba hardcodeada
    en la ficha de visita, los informes y los correos. Así cada documento
    se genera con los datos de la empresa activa sin condicionales en el
    código.
    """

    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True)

    # Clave estable para usar en código y cookies: "MOYZA", "MOES"
    code = Column(String(20), unique=True, nullable=False, index=True)

    # Nombre comercial que se muestra en la interfaz
    name = Column(String, nullable=False)

    # Identidad legal (ficha de visita, pie de informes, RGPD)
    legal_name = Column(String, nullable=True)        # "Moyza 2012 S.L."
    tax_id = Column(String(20), nullable=True)        # C.I.F.
    fiscal_address = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    rgpd_text = Column(Text, nullable=True)

    # Marca
    logo_path = Column(String, nullable=True)         # "/static/logo_moyza.png"
    primary_color = Column(String(7), nullable=True)  # "#000000"

    # Prefijo del ID de documento en fichas de visita: "MOYZA-VISIT"
    document_prefix = Column(String(20), nullable=True)

    # Comunicaciones
    email_sender_name = Column(String, nullable=True)  # "Sistema Moyza"
    whatsapp_phone = Column(String, nullable=True)

    is_active = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relaciones
    properties = relationship("Property", back_populates="company")
    buyers = relationship("Buyer", back_populates="company")

    users = relationship("User", secondary=user_companies, back_populates="companies")
    agents = relationship("Agent", secondary=agent_companies, back_populates="companies")
    clients = relationship("Client", secondary=client_companies, back_populates="companies")

    def __repr__(self):
        return f"<Company {self.code}>"
