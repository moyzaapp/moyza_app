from fastapi import APIRouter
from fastapi import Request
from fastapi import Depends
from fastapi import Form

from fastapi.responses import HTMLResponse
from fastapi.responses import RedirectResponse

from fastapi.templating import Jinja2Templates

from sqlalchemy.orm import Session

from app.db.deps import get_db

from app.models.property import Property
from app.models.client import Client
from app.models.agent import Agent


router = APIRouter()

templates = Jinja2Templates(
    directory="app/web/templates"
)

@router.get("/properties", response_class=HTMLResponse)
async def properties_page(
    request: Request,
    db: Session = Depends(get_db)
):

    properties = db.query(Property).all()

    clients = db.query(Client).all()

    agents = db.query(Agent).all()

    current_user = request.state.user

    active_count = db.query(Property).filter(Property.status == "Activa").count()
    paused_count = db.query(Property).filter(Property.status == "Pausada").count()
    sold_count = db.query(Property).filter(Property.status == "Vendida").count()

    search = request.query_params.get("search")

    if search:
        properties = db.query(Property).filter(Property.title.contains(search)).all()

    return templates.TemplateResponse(
        request=request,
        name="properties/home.html",
        context={
            "request": request,
            "properties": properties,
            "clients": clients,
            "agents": agents,
            "current_user": current_user,
            "active_count": active_count,
            "paused_count": paused_count,
            "sold_count": sold_count
        }
    )

@router.post("/properties/create")
async def create_property(
    request: Request,
    title: str = Form(...),
    address: str = Form(...),
    city: str = Form(...),
    price: float = Form(...),
    description: str = Form(...),
    client_id: int = Form(...),
    agent_id: int = Form(...),
    db: Session = Depends(get_db)
):

    property_item = Property(
        title=title,
        address=address,
        city=city,
        price=price,
        description=description,
        client_id=client_id,
        agent_id=agent_id,
        status="Activa"
    )

    db.add(property_item)

    db.commit()

    return RedirectResponse(
        url="/properties",
        status_code=302
    )

@router.post("/properties/update")
async def update_property(
    request: Request,
    property_id: int = Form(...),
    title: str = Form(...),
    price: float = Form(...),
    client_id: int = Form(...),
    agent_id: int = Form(...),
    address: str = Form(...),
    status: str = Form(...),
    db: Session = Depends(get_db)
):

    property = db.query(Property).filter(
        Property.id == property_id
    ).first()

    if property:

        property.title = title
        property.price = price
        property.client_id = client_id
        property.agent_id = agent_id
        property.address = address
        property.status = status

        db.commit()

    return RedirectResponse(
        url="/properties",
        status_code=302
    )

@router.post("/properties/delete/{property_id}")
async def delete_property(
    property_id: int,
    db: Session = Depends(get_db)
):

    property = db.query(Property).filter(
        Property.id == property_id
    ).first()

    if property:

        db.delete(property)
        db.commit()

    return RedirectResponse(
        url="/properties",
        status_code=302
    )