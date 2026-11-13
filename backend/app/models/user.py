from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy import ForeignKey

from app.db.base import Base


class User(Base):

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)

    email = Column(String, unique=True, index=True, nullable=False)

    full_name = Column(String, nullable=False)

    hashed_password = Column(String, nullable=False)

    phone = Column(String, nullable=True)

    company = Column(String, nullable=True)

    # NULL cuenta como activo (PLAN_BAJA_USUARIOS.md §3)
    is_active = Column(Boolean, default=True)

    # Fecha de la baja lógica; NULL si está activo
    deactivated_at = Column(DateTime, nullable=True)

    role_id = Column(Integer, ForeignKey("roles.id"))
    
    role = relationship("Role")

    # Empresas a las que tiene acceso el usuario. Un admin ve todas
    # independientemente de esta lista.
    companies = relationship(
        "Company",
        secondary="user_companies",
        back_populates="users"
    )

    # Vista por empresa (PLAN_VISTA_UNIFICADA_AGENTES.md §2.1): con False (por
    # defecto) un usuario no admin trabaja con todas sus empresas a la vez, sin
    # selector; con True conserva el selector y la empresa activa por cookie.
    # El admin siempre tiene selector, valga lo que valga.
    company_switch_enabled = Column(Boolean, nullable=False, default=False, server_default="false")

    # Empresa principal: marca del sidebar en la vista unificada y empresa por
    # defecto de lo que crea. NULL o fuera de sus empresas = la primera de ellas.
    primary_company_id = Column(Integer, ForeignKey("companies.id", ondelete="SET NULL"), nullable=True)

    primary_company = relationship("Company", foreign_keys=[primary_company_id])
