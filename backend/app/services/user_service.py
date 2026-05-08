from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.user import User
from app.schemas.user import UserCreate
from app.core.password import hash_password


def create_user(db: Session, user: UserCreate):

    existing_user = (
    db.query(User)
    .filter(User.email == user.email)
    .first()
    )

    if existing_user:

        raise HTTPException(
            status_code=400,
            detail="Email already registered"
        )

    db_user = User(
        email=user.email,
        full_name=user.full_name,
        hashed_password=hash_password(user.password),
        role_id = 1 if not user.role_id else user.role_id
    )

    db.add(db_user)

    db.commit()

    db.refresh(db_user)

    return db_user


def get_users(db: Session):

    return db.query(User).all()