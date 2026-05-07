from pydantic import BaseModel, EmailStr


class UserCreate(BaseModel):

    email: EmailStr

    full_name: str

    password: str


class UserResponse(BaseModel):

    id: int

    email: EmailStr

    full_name: str

    is_active: bool

    role: str

    class Config:
        from_attributes = True