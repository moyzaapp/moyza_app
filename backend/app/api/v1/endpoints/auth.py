from fastapi import APIRouter
from fastapi import Depends
from fastapi.security import OAuth2PasswordRequestForm

from sqlalchemy.orm import Session

from app.db.deps import get_db

from app.services.auth_service import authenticate_user


router = APIRouter()


@router.post("/login")

def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    return authenticate_user(
        db,
        form_data.username,
        form_data.password
    )