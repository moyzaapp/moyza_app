from pydantic import BaseModel

class ClientCreate(BaseModel):
    name: str
    phone: str

class ClientResponse(ClientCreate):
    id: int

    class Config:
        orm_mode = True