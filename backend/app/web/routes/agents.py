from fastapi import APIRouter
from fastapi import Request

from app.web.dependencies.auth import get_current_web_user
from app.models.user import User
from fastapi import Depends

from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()

templates = Jinja2Templates(
    directory="app/web/templates"
)


@router.get("/agents", response_class=HTMLResponse)
async def agents_page(request: Request, current_user: User = Depends(get_current_web_user)):

    return templates.TemplateResponse(
        request=request,
        name="agents/home.html",
        context={
            "request": request,
            "current_user": current_user
        }
    )