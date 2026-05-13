from fastapi import APIRouter
from fastapi import Request
from fastapi import Depends
from fastapi import Form
from fastapi import HTTPException

from sqlalchemy.orm import Session

from fastapi.responses import HTMLResponse
from fastapi.responses import RedirectResponse

from fastapi.templating import Jinja2Templates

from app.db.deps import get_db

from app.services.auth_service import authenticate_user
from app.core.security import create_access_token

router = APIRouter()

templates = Jinja2Templates(
    directory="app/web/templates"
)


@router.get("/", response_class=HTMLResponse)
async def login_page(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="auth/login.html",
        context={
            "request": request
        }
    )


@router.get("/auth", response_class=HTMLResponse)
async def auth(request: Request):

    current_user = request.state.user

    return templates.TemplateResponse(
        request=request,
        name="auth/home.html",
        context={
            "request": request,
            "current_user": current_user
        }
    )



@router.post("/login")
async def login(
    request: Request,
    username: str = Form(None),
    password: str = Form(None),
    db: Session = Depends(get_db)):

    # Validación amigable
    if not username or not password:

        return templates.TemplateResponse(
            request=request,
            name="auth/login.html",
            context={
                "request": request,
                "error": "Todos los campos son obligatorios"
            }
        )

    user = authenticate_user(
        db,
        username,
        password
    )

    if not user:

        return templates.TemplateResponse(
            request=request,
            name="auth/login.html",
            context={
                "request": request,
                "error": "Credenciales inválidas"
            }
        )

    token = create_access_token(
        {"sub": user.email}
    )

    response = RedirectResponse(
        url="/dashboard",
        status_code=302
    )

    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=False,
        samesite="lax"
    )

    return response


@router.get("/logout")
async def logout():

    response = RedirectResponse(
        url="/",
        status_code=302
    )

    response.delete_cookie("access_token")

    return response