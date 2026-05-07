from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.user import User

from app.core.security import (
    verify_password,
    create_access_token
)


def authenticate_user(db: Session, email: str, password: str):

    user = (
        db.query(User)
        .filter(User.email == email)
        .first()
    )

    if not user:

        raise HTTPException(
            status_code=401,
            detail="Invalid credentials"
        )

    if not verify_password(
        password,
        user.hashed_password
    ):

        raise HTTPException(
            status_code=401,
            detail="Invalid credentials"
        )

    token = create_access_token({
        "sub": user.email
    })

    return {
        "access_token": token,
        "token_type": "bearer"
    }