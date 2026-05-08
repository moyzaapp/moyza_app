from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.user import User
from app.core.password import verify_password


def authenticate_user(db: Session, email: str, password: str):

    user = (
        db.query(User)
        .filter(User.email == email)
        .first()
    )

    if not user:
        return False

    if not verify_password(password, user.hashed_password):
        return False

    return user