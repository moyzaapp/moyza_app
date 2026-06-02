from datetime import datetime

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
from app.models.property_price_history import PropertyPriceHistory
from app.models.property_interaction import PropertyInteraction


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

        old_price = property.price

        property.title = title
        property.price = price
        property.client_id = client_id
        property.agent_id = agent_id
        property.address = address
        property.status = status

        if old_price != price:

            history = PropertyPriceHistory(
                property_id=property_id,
                old_price=old_price,
                new_price=price,
                reason="Actualización manual"
            )

            db.add(history)

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

@router.get("/properties/{property_id}")
async def property_detail(
        property_id: int,
        request: Request,
        db: Session = Depends(get_db)
    ):

    property_item = (
        db.query(Property)
        .filter(Property.id == property_id)
        .first()
    )

    if not property_item:
        return RedirectResponse(
            url="/properties",
            status_code=302
        )

    history = (
        db.query(PropertyPriceHistory)
        .filter(
            PropertyPriceHistory.property_id == property_id
        )
        .order_by(
            PropertyPriceHistory.created_at.desc()
        )
        .all()
    )

    reductions_count = len(history)

    days_on_market = 0
    if property_item.market_entry_date:
        days_on_market = (
                datetime.utcnow()
                - property_item.market_entry_date
            ).days

    interactions = (
        db.query(PropertyInteraction)
        .filter(
            PropertyInteraction.property_id == property_id
        )
        .order_by(
            PropertyInteraction.created_at.desc()
        )
        .all()
    )

    consultas = (
        db.query(PropertyInteraction)
        .filter(
            PropertyInteraction.property_id == property_id,
            PropertyInteraction.interaction_type == "CONSULTA"
        )
        .count()
    )

    visitas = (
        db.query(PropertyInteraction)
        .filter(
            PropertyInteraction.property_id == property_id,
            PropertyInteraction.interaction_type == "VISITA"
        )
        .count()
    )

    interesados = (
        db.query(PropertyInteraction)
        .filter(
            PropertyInteraction.property_id == property_id,
            PropertyInteraction.interaction_type == "INTERESADO"
        )
        .count()
    )

    ofertas = (
        db.query(PropertyInteraction)
        .filter(
            PropertyInteraction.property_id == property_id,
            PropertyInteraction.interaction_type == "OFERTA"
        )
        .count()
    )

    price_gap = None

    if property_item.fair_price:

        price_gap = (
            float(property_item.price)
            - float(property_item.fair_price)
        )

    return templates.TemplateResponse(
        request=request,
        name="properties/detail.html",
        context={
            "request": request,
            "property": property_item,
            "history": history,
            "reductions": reductions_count,
            "days_on_market": days_on_market,
            "interactions": interactions,
            "current_user": request.state.user,
            "price_gap": price_gap,
            "consultas": consultas,
            "visitas": visitas,
            "interesados": interesados,
            "ofertas": ofertas
        }
    )


@router.post("/properties/{property_id}/interactions/create")
async def create_interaction(
        property_id: int,
        request: Request,
        interaction_type: str = Form(...),
        contact_name: str = Form(""),
        phone: str = Form(""),
        source: str = Form(""),
        notes: str = Form(""),
        db: Session = Depends(get_db)
    ):

    current_user = request.state.user

    interaction = PropertyInteraction(
        property_id=property_id,
        interaction_type=interaction_type,
        contact_name=contact_name,
        phone=phone,
        source=source,
        notes=notes,
        created_by=current_user.id
    )

    db.add(interaction)
    db.commit()

    return RedirectResponse(
        url=f"/properties/{property_id}",
        status_code=302
    )