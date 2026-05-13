from app.web.dependencies.auth import get_current_web_user
from app.models.user import User
from fastapi import APIRouter
from fastapi import Request
from fastapi import Depends

from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()

templates = Jinja2Templates(
    directory="app/web/templates"
)


@router.get("/clients", response_class=HTMLResponse)
async def clients_page(request: Request, current_user: User = Depends(get_current_web_user)):

    clients = [
        {
            "name": "Juan Perez",
            "email": "juan@test.com",
            "phone": "300123456",
            "status": "Activo"
        },
        {
            "name": "Maria Lopez",
            "email": "maria@test.com",
            "phone": "300555555",
            "status": "Activo"
        }
    ]

    return templates.TemplateResponse(
        request=request,
        name="clients/home.html",
        context={
            "request": request,
            "clients": current_user,
            "current_user": current_user
        }
    )