from fastapi import APIRouter
from fastapi import Request
from fastapi import Depends
from fastapi import Form

from fastapi.responses import HTMLResponse
from fastapi.responses import RedirectResponse

from fastapi.templating import Jinja2Templates

from sqlalchemy.orm import Session

from app.db.deps import get_db

from app.models.agent import Agent
from app.models.property import Property


router = APIRouter()

templates = Jinja2Templates(
    directory="app/web/templates"
)


@router.get("/agents", response_class=HTMLResponse)
async def agents_page(
    request: Request,
    db: Session = Depends(get_db)
):
    error = request.query_params.get("error")

    agents = db.query(Agent).all()

    current_user = request.state.user

    return templates.TemplateResponse(
        request=request,
        name="agents/home.html",
        context={
            "request": request,
            "agents": agents,
            "current_user": current_user,
            "error": error
        }
    )


@router.post("/agents/create")
async def create_agent(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(...),
    zone: str = Form(...),
    db: Session = Depends(get_db)
):

    agent = Agent(
        name=name,
        email=email,
        phone=phone,
        zone=zone
    )

    db.add(agent)

    db.commit()

    return RedirectResponse(
        url="/agents",
        status_code=302
    )


@router.post("/agents/update")
async def update_agent(
    request: Request,
    agent_id: int = Form(...),
    name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(...),
    zone: str = Form(...),
    db: Session = Depends(get_db)
):

    agent = db.query(Agent).filter(
        Agent.id == agent_id
    ).first()

    if agent:

        agent.name = name
        agent.email = email
        agent.phone = phone
        agent.zone = zone

        db.commit()

    return RedirectResponse(
        url="/agents",
        status_code=302
    )


@router.post("/agents/delete/{agent_id}")
async def delete_agent(
    agent_id: int,
    db: Session = Depends(get_db)
):
    
    properties = db.query(Property).filter(
        Property.agent_id == agent_id
    ).count()

    if properties > 0:
        return RedirectResponse(
            url="/agents?error=in_use",
            status_code=302
        )

    agent = db.query(Agent).filter(
        Agent.id == agent_id
    ).first()

    if agent:

        db.delete(agent)

        db.commit()

    return RedirectResponse(
        url="/agents",
        status_code=302
    )