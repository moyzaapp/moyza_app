from fastapi import APIRouter
from fastapi import Request
from fastapi import Depends

from fastapi.responses import HTMLResponse

from fastapi.templating import Jinja2Templates

from app.web.dependencies.auth import get_current_web_user

from app.models.user import User

router = APIRouter()

templates = Jinja2Templates(
    directory="app/web/templates"
)


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):

    current_user = request.state.user

    return templates.TemplateResponse(
        request=request,
        name="dashboard/home.html",
        context={
            "request": request,
            "current_user": current_user
        }
    )