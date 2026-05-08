from pydantic import BaseModel, EmailStr

from app.schemas.role import RoleResponse


class UserCreate(BaseModel):

    email: EmailStr

    full_name: str

    password: str

    role_id: int


class UserResponse(BaseModel):

    id: int

    email: EmailStr

    full_name: str

    is_active: bool

    role_id: int

    class Config:
        from_attributes = True