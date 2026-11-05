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
