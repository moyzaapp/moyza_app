from sqlalchemy.orm import Session
from app.models.client import Client

def create_client(db: Session, name: str, phone: str):
    client = Client(name=name, phone=phone)
    db.add(client)
    db.commit()
    db.refresh(client)
    return client

def get_clients(db: Session):
    return db.query(Client).all()