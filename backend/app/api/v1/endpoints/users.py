from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.deps import get_db

from app.schemas.user import (
    UserCreate,
    UserResponse
)

from app.services.user_service import (
    create_user,
    get_users
)

router = APIRouter()


@router.post(
    "/",
    response_model=UserResponse
)
def create_new_user(
    user: UserCreate,
    db: Session = Depends(get_db)
):

    return create_user(db, user)


@router.get(
    "/",
    response_model=list[UserResponse]
)
def list_users(
    db: Session = Depends(get_db)
):

    return get_users(db)