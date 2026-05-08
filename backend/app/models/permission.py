from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship

from app.db.base import Base


class Permission(Base):

    __tablename__ = "permissions"

    id = Column(Integer, primary_key=True, index=True)

    code = Column(String, unique=True, nullable=False)

    roles = relationship(
        "Role",
        secondary="role_permissions",
        back_populates="permissions"
    )