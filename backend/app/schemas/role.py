from pydantic import BaseModel


class RoleResponse(BaseModel):

    id: int

    name: str

    class Config:
        from_attributes = True