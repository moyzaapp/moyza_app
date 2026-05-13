from app.web.dependencies.auth import get_current_web_user
from app.models.user import User
from app.models.client import Client
from fastapi import APIRouter
from fastapi import Request
from fastapi import Depends
from sqlalchemy.orm import Session
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from app.db.deps import get_db
from fastapi import Form
from fastapi.responses import RedirectResponse

router = APIRouter()

templates = Jinja2Templates(
    directory="app/web/templates"
)


@router.get("/clients", response_class=HTMLResponse)
async def clients_page(request: Request, db: Session = Depends(get_db)):

    clients = db.query(Client).all()

    current_user = request.state.user

    return templates.TemplateResponse(
        request=request,
        name="clients/home.html",
        context={
            "request": request,
            "clients": clients,
            "current_user": current_user
        }
    )

@router.post("/clients/create")
async def create_client(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(...),
    db: Session = Depends(get_db)
):

    client = Client(
        name=name,
        email=email,
        phone=phone,
        status="Activo"
    )

    db.add(client)

    db.commit()

    return RedirectResponse(
        url="/clients",
        status_code=302
    )

@router.post("/clients/update")
async def update_client(
    request: Request,
    client_id: int = Form(...),
    name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(...),
    db: Session = Depends(get_db)
):

    client = db.query(Client).filter(
        Client.id == client_id
    ).first()

    if client:

        client.name = name
        client.email = email
        client.phone = phone

        db.commit()

    return RedirectResponse(
        url="/clients",
        status_code=302
    )