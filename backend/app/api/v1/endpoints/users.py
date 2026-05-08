from fastapi import APIRouter, Depends
from app.core.deps import get_current_user, require_role, require_permission
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


@router.post("/", response_model=UserResponse)
def create_new_user(user: UserCreate, db: Session = Depends(get_db)):
    return create_user(db, user)


@router.get("/", response_model=list[UserResponse])
def list_users(db: Session = Depends(get_db), current_user=Depends(require_permission("users.read"))):
    return get_users(db)

@router.get("/me")
def get_me(current_user=Depends(get_current_user)):
    return current_user

@router.get("/admin")
def admin_panel(current_user=Depends(require_role(1))):
    return {"message": "Welcome admin"}