from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.user import User
from app.core.password import verify_password


# Credenciales correctas pero usuario dado de baja (PLAN_BAJA_USUARIOS.md §4.1).
# Es truthy: los llamadores deben compararlo con `is INACTIVE` antes de usar el usuario.
INACTIVE = object()


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

    # Solo tras comprobar la contraseña, para no revelar qué emails existen.
    # NULL cuenta como activo.
    if user.is_active is False:
        return INACTIVE

    return user