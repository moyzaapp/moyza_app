from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from app.core.security import decode_token
from app.db.deps import get_db
from app.models.user import User
from sqlalchemy.orm import Session

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def get_current_user(
        token: str = Depends(oauth2_scheme),
        db: Session = Depends(get_db)
        ):

    payload = decode_token(token)

    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )

    email = payload.get("sub")

    user = db.query(User).filter(User.email == email).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )

    return user


def require_role(role: int):
    def wrapper(current_user=Depends(get_current_user)):
        if current_user.role_id != role:
            raise HTTPException(status_code=403, detail=current_user.role_id)
        return current_user
    return wrapper


def require_permission(permission_code: str):

    def permission_checker(current_user: User = Depends(get_current_user)):

        permissions = [
            permission.code
            for permission in current_user.role.permissions
        ]

        if permission_code not in permissions:

            raise HTTPException(
                status_code=403,
                detail="Permission denied"
            )

        return current_user

    return permission_checker