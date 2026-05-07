from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.schemas.client import ClientCreate, ClientResponse
from app.services.client_service import create_client, get_clients

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/", response_model=ClientResponse)
def create(client: ClientCreate, db: Session = Depends(get_db)):
    return create_client(db, client.name, client.phone)

@router.get("/", response_model=list[ClientResponse])
def read(db: Session = Depends(get_db)):
    return get_clients(db)