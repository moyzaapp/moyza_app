import logging
from datetime import datetime

from fastapi import APIRouter
from fastapi import Request
from fastapi import Depends
from fastapi import Form

from fastapi.responses import HTMLResponse
from fastapi.responses import RedirectResponse

from fastapi.templating import Jinja2Templates

from sqlalchemy.orm import Session

from app.core.constants import PropertyInteractionType
from app.core.constants import PropertyStatus
from app.core.constants import ReportType
from app.db.deps import get_db

from app.models.property import Property
from app.models.client import Client
from app.models.agent import Agent
from app.models.property_price_history import PropertyPriceHistory
from app.models.property_interaction import PropertyInteraction
from app.models.property_status_history import PropertyStatusHistory
from app.models.property_visit import PropertyVisit
from app.models.report import Report
from app.services.ai_valuation import AIValuationService

from pathlib import Path

from app.services.property_metrics import PropertyMetricsService
from app.services.report_generator import generate_property_report
from app.services.visit_sheet_generator import generate_visit_sheet
from app.services.whatsapp import send_report
from app.core.config import settings
from app.web.utils.flash import set_flash
from uuid import uuid4


router = APIRouter()
logger = logging.getLogger(__name__)

templates = Jinja2Templates(
    directory="app/web/templates"
)

@router.get("/properties", response_class=HTMLResponse)
async def properties_page(
    request: Request,
    db: Session = Depends(get_db)
):

    properties = db.query(Property).filter(Property.status != PropertyStatus.ARCHIVED).all()

    clients = db.query(Client).all()

    agents = db.query(Agent).all()

    current_user = request.state.user

    active_count = db.query(Property).filter(Property.status == PropertyStatus.ACTIVE).count()
    paused_count = db.query(Property).filter(Property.status == PropertyStatus.PAUSED).count()
    sold_count = db.query(Property).filter(Property.status == PropertyStatus.SOLD).count()

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

    try:
        property_item = Property(
            title=title,
            address=address,
            city=city,
            price=price,
            description=description,
            client_id=client_id,
            agent_id=agent_id,
            status=PropertyStatus.ACTIVE
        )

        db.add(property_item)
        db.commit()

        response = RedirectResponse(url="/properties", status_code=302)
        set_flash(response, "success", f"Propiedad '{title}' creada correctamente")
        return response

    except Exception:
        db.rollback()
        logger.exception("Error creando propiedad: title=%s", title)
        response = RedirectResponse(url="/properties", status_code=302)
        set_flash(response, "error", "Ocurrió un error al crear la propiedad")
        return response

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
    auto_send_report: bool = Form(False),
    report_frequency: str = Form(None),
    report_day: int = Form(None),
    report_hour: int = Form(None),
    db: Session = Depends(get_db)
):

    if not PropertyStatus.is_valid(status):
        logger.warning(
            "Estado inválido al actualizar propiedad: property_id=%s status=%s",
            property_id,
            status
        )
        response = RedirectResponse(url="/properties", status_code=302)
        set_flash(response, "error", "Estado de propiedad inválido")
        return response

    property = db.query(Property).filter(
        Property.id == property_id
    ).first()

    if not property:
        response = RedirectResponse(url="/properties", status_code=302)
        set_flash(response, "error", "Propiedad no encontrada")
        return response

    try:
        old_price = property.price
        old_status = property.status

        property.title = title
        property.price = price
        property.client_id = client_id
        property.agent_id = agent_id
        property.address = address
        property.status = status
        property.auto_send_report = auto_send_report
        property.report_frequency = report_frequency
        property.report_day = report_day
        property.report_hour = report_hour

        if old_price != price:

            history = PropertyPriceHistory(
                property_id=property_id,
                old_price=old_price,
                new_price=price,
                reason="Actualización manual"
            )

            db.add(history)

        if old_status != status:

            history = PropertyStatusHistory(
                property_id=property_id,
                old_status=old_status,
                new_status=status,
                changed_by=request.state.user.id
            )

            db.add(history)

        db.commit()

    except Exception:
        db.rollback()
        logger.exception("Error actualizando propiedad: property_id=%s", property_id)
        response = RedirectResponse(url="/properties", status_code=302)
        set_flash(response, "error", "Ocurrió un error al actualizar la propiedad")
        return response

    response = RedirectResponse(url="/properties", status_code=302)
    if old_price != price:
        set_flash(response, "success", "Precio actualizado correctamente")
    else:
        set_flash(response, "success", "Propiedad actualizada correctamente")
    return response

@router.post("/properties/delete/{property_id}")
async def delete_property(
    property_id: int,
    request: Request,
    db: Session = Depends(get_db)
):

    property = db.query(Property).filter(
        Property.id == property_id
    ).first()

    if not property:
        response = RedirectResponse(url="/properties", status_code=302)
        set_flash(response, "error", "Propiedad no encontrada")
        return response

    try:
        old_status = property.status
        property.status = PropertyStatus.ARCHIVED

        history = PropertyStatusHistory(
            property_id=property_id,
            old_status=old_status,
            new_status=PropertyStatus.ARCHIVED,
            changed_by=request.state.user.id
        )

        db.add(history)
        db.commit()

    except Exception:
        db.rollback()
        logger.exception("Error archivando propiedad: property_id=%s", property_id)
        response = RedirectResponse(url="/properties", status_code=302)
        set_flash(response, "error", "Ocurrió un error al archivar la propiedad")
        return response

    response = RedirectResponse(url="/properties", status_code=302)
    set_flash(response, "success", "Propiedad archivada")
    return response

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

    metrics_service = PropertyMetricsService(db)
    report_data = metrics_service.report_data(
        property_item,
        reductions_count=len(history)
    )

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

    price_gap = metrics_service.price_gap(property_item)

    status_history = (
        db.query(PropertyStatusHistory)
        .filter(
            PropertyStatusHistory.property_id == property_id
        )
        .order_by(
            PropertyStatusHistory.created_at.desc()
        )
        .all()
    )

    visits_registered = (
        db.query(PropertyVisit)
        .filter(
            PropertyVisit.property_id == property_id
        )
        .order_by(
            PropertyVisit.created_at.desc()
        )
        .all()
    )

    visit_summary = metrics_service.visit_summary(visits_registered)

    property_reports = (
        db.query(Report)
        .filter(Report.property_id == property_id)
        .order_by(Report.created_at.desc())
        .all()
    )

    latest_report = property_reports[0] if property_reports else None

    return templates.TemplateResponse(
        request=request,
        name="properties/detail.html",
        context={
            "request": request,
            "property": property_item,
            "history": history,
            "reductions": report_data["reductions"],
            "days_on_market": report_data["days_on_market"],
            "interactions": interactions,
            "current_user": request.state.user,
            "price_gap": price_gap,
            "consultas": report_data["consultas"],
            "visitas": report_data["visitas"],
            "interesados": report_data["interesados"],
            "ofertas": report_data["ofertas"],
            "status_history": status_history,
            "visits_registered": visits_registered,
            "interest_avg": visit_summary["interest_avg"],
            "price_high_count": visit_summary["price_high_count"],
            "property_reports": property_reports,
            "latest_report": latest_report
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

    if not PropertyInteractionType.is_valid(interaction_type):
        logger.warning(
            "Tipo de interacción inválido: property_id=%s interaction_type=%s",
            property_id,
            interaction_type
        )
        response = RedirectResponse(url=f"/properties/{property_id}", status_code=302)
        set_flash(response, "error", "Tipo de actividad inválido")
        return response

    try:
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

        response = RedirectResponse(url=f"/properties/{property_id}", status_code=302)
        set_flash(response, "success", f"Actividad de tipo '{interaction_type}' registrada correctamente")
        return response

    except Exception:
        db.rollback()
        logger.exception(
            "Error registrando interacción: property_id=%s interaction_type=%s",
            property_id,
            interaction_type
        )
        response = RedirectResponse(url=f"/properties/{property_id}", status_code=302)
        set_flash(response, "error", "Ocurrió un error al registrar la actividad")
        return response

@router.get("/properties/{property_id}/visits/new")
async def new_visit(
        property_id: int,
        request: Request,
        db: Session = Depends(get_db)
    ):

    property_item = (
        db.query(Property)
        .filter(Property.id == property_id)
        .first()
    )

    return templates.TemplateResponse(
        request=request,
        name="properties/visit_form.html",
        context={
            "request": request,
            "property": property_item,
            "current_user": request.state.user
        }
    )

@router.post("/properties/{property_id}/visits/create")
async def create_visit(
        property_id: int,
        request: Request,
        db: Session = Depends(get_db)
    ):

    form = await request.form()

    interest_level_raw = form.get("interest_level")
    interest_level = None
    if interest_level_raw not in (None, ""):
        try:
            interest_level = int(interest_level_raw)
        except (TypeError, ValueError):
            interest_level = None

    generate_sheet = form.get("generate_sheet") == "true"

    try:
        visit = PropertyVisit(
            property_id=property_id,
            visitor_name=form.get("visitor_name"),
            dni=form.get("dni"),
            phone=form.get("phone"),
            email=form.get("email"),
            interest_level=interest_level,
            price_feedback=form.get("price_feedback"),
            location_feedback=form.get("location_feedback"),
            condition_feedback=form.get("condition_feedback"),
            lighting_feedback=form.get("lighting_feedback"),
            elevator_feedback=form.get("elevator_feedback"),
            garage_feedback=form.get("garage_feedback"),
            notes=form.get("notes"),
            created_by=request.state.user.id
        )

        db.add(visit)
        db.commit()
        db.refresh(visit)

        property_item = db.query(Property).filter(Property.id == property_id).first()

        if generate_sheet and property_item:
            try:
                visits_dir = Path("storage/visit_sheets")
                visits_dir.mkdir(parents=True, exist_ok=True)

                filename = f"ficha_visita_{property_id}_{visit.id}_{uuid4().hex[:8]}.pdf"
                output_path = visits_dir / filename

                generate_visit_sheet(
                    property_item=property_item,
                    visit=visit,
                    agent=property_item.agent,
                    output_path=str(output_path)
                )

                logger.info("Ficha de visita generada: %s", output_path)

                file_url = settings.public_url(str(output_path))

                sent_to = []

                if visit.phone:
                    try:
                        send_report(
                            phone=visit.phone,
                            file_url=file_url,
                            caption=f"Ficha de visita - {property_item.title}"
                        )
                        sent_to.append("comprador")
                        logger.info("Ficha enviada al comprador: %s", visit.phone)
                    except Exception:
                        logger.exception("Error enviando ficha al comprador: %s", visit.phone)

                if property_item.agent and property_item.agent.phone:
                    try:
                        send_report(
                            phone=property_item.agent.phone,
                            file_url=file_url,
                            caption=f"Ficha de visita - {property_item.title}"
                        )
                        sent_to.append("agente")
                        logger.info("Ficha enviada al agente: %s", property_item.agent.phone)
                    except Exception:
                        logger.exception("Error enviando ficha al agente: %s", property_item.agent.phone)

                if sent_to:
                    response = RedirectResponse(url=f"/properties/{property_id}", status_code=302)
                    set_flash(response, "success", f"Visita registrada y ficha enviada a {' y '.join(sent_to)}")
                    return response
                else:
                    response = RedirectResponse(url=f"/properties/{property_id}", status_code=302)
                    set_flash(response, "warning", "Visita registrada, pero no se pudo enviar la ficha (verifique números de teléfono)")
                    return response

            except Exception:
                logger.exception("Error generando/enviando ficha de visita: property_id=%s", property_id)
                response = RedirectResponse(url=f"/properties/{property_id}", status_code=302)
                set_flash(response, "warning", "Visita registrada, pero no se pudo generar/enviar la ficha")
                return response

    except Exception:
        db.rollback()
        logger.exception("Error registrando visita: property_id=%s", property_id)
        response = RedirectResponse(url=f"/properties/{property_id}", status_code=302)
        set_flash(response, "error", "Ocurrió un error al registrar la visita")
        return response

    response = RedirectResponse(url=f"/properties/{property_id}", status_code=302)
    set_flash(response, "success", "Visita registrada")
    return response

@router.post("/properties/{property_id}/generate-report")
async def generate_report(
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
        response = RedirectResponse(url="/properties", status_code=302)
        set_flash(response, "error", "Propiedad no encontrada")
        return response

    report_data = PropertyMetricsService(db).report_data(property_item)

    try:
        ai_service = AIValuationService(db)
        ai_analysis = ai_service.generate_analysis(property_item, report_data)
        if ai_analysis:
            report_data["ai_valuation"] = ai_analysis.get("valuation")
            report_data["ai_observations"] = ai_analysis.get("observations")
            ai_service.update_property_fair_price(
                property_item,
                ai_analysis.get("valuation")
            )
            logger.info("Análisis de IA generado para propiedad %s", property_item.id)
        else:
            logger.warning(
                "No se pudo generar análisis de IA para propiedad %s",
                property_item.id
            )
    except Exception:
        logger.exception(
            "Error generando análisis de IA para informe manual: property_id=%s",
            property_item.id
        )

    reports_dir = Path("storage/reports")

    reports_dir.mkdir(parents=True, exist_ok=True)

    filename = f"reporte_propiedad_{property_id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.pdf"

    output_path = reports_dir / filename

    try:
        generate_property_report(property_item, report_data, str(output_path))

        report = Report(
            property_id=property_id,
            uploaded_by=None,
            report_type=ReportType.AUTOMATIC,
            filename=filename,
            filepath=str(output_path)
        )

        db.add(report)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Error generando informe manual: property_id=%s", property_id)
        response = RedirectResponse(url=f"/properties/{property_id}", status_code=302)
        set_flash(response, "error", "No se pudo generar el informe")
        return response

    response = RedirectResponse(url=f"/properties/{property_id}", status_code=302)
    set_flash(response, "success", "Informe generado")
    return response
