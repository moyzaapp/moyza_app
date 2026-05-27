from sqlalchemy.orm import declarative_base
Base = declarative_base()

from app.models.user import User
from app.models.client import Client
from app.models.role import Role
from app.models.permission import Permission
from app.models.role_permission import RolePermission
from app.models.agent import Agent
from app.models.property import Property
from app.models.report import Report