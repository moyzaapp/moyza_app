import os
import base64
from datetime import datetime

from fastapi import APIRouter
from fastapi import Request
from fastapi import Depends
from fastapi import Form
from fastapi import File
from fastapi import UploadFile

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
        dni: str = Form(None),
        phone: str = Form(...),
        zone: str = Form(...),
        db: Session = Depends(get_db)
    ):

    existing_agent = db.query(Agent).filter(
        Agent.email == email
    ).first()

    if existing_agent:
        return RedirectResponse(
            url="/agents?error=email_exists",
            status_code=302
        )

    agent = Agent(
        name=name,
        email=email,
        dni=dni if dni else None,
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
    dni: str = Form(None),
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
        agent.dni = dni if dni else None
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


@router.post("/agents/{agent_id}/upload-signature")
async def upload_agent_signature(
    agent_id: int,
    signature_data: str = Form(...),
    db: Session = Depends(get_db)
):
    """
    Endpoint para subir la firma del agente.
    signature_data viene como base64 string desde el canvas del frontend
    """
    agent = db.query(Agent).filter(
        Agent.id == agent_id
    ).first()

    if not agent:
        return RedirectResponse(
            url="/agents?error=agent_not_found",
            status_code=302
        )

    # Crear directorio de firmas si no existe
    signatures_dir = "storage/signatures/agents"
    os.makedirs(signatures_dir, exist_ok=True)

    # Decodificar base64
    if signature_data.startswith("data:image/png;base64,"):
        signature_data = signature_data.replace("data:image/png;base64,", "")

    signature_bytes = base64.b64decode(signature_data)

    # Generar nombre de archivo único
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"agent_{agent_id}_{timestamp}.png"
    filepath = os.path.join(signatures_dir, filename)

    # Guardar archivo
    with open(filepath, "wb") as f:
        f.write(signature_bytes)

    # Actualizar agente
    agent.signature_filename = filename
    agent.signature_filepath = filepath
    agent.signature_uploaded_at = datetime.utcnow()

    db.commit()

    return RedirectResponse(
        url="/agents",
        status_code=302
    )