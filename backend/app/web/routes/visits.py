import logging
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter
from fastapi import Request
from fastapi import Depends
from fastapi import Form
from fastapi.responses import HTMLResponse
from fastapi.responses import RedirectResponse
from fastapi.responses import FileResponse
from fastapi.templating import Jinja2Templates

from sqlalchemy.orm import Session

from app.db.deps import get_db
from app.models.property import Property
from app.models.property_visit import PropertyVisit
from app.services.visit_sheet_generator import generate_visit_sheet
from app.services.whatsapp import send_report
from app.core.config import settings
from app.web.utils.flash import set_flash


router = APIRouter()
logger = logging.getLogger(__name__)

templates = Jinja2Templates(
    directory="app/web/templates"
)


@router.get("/visits", response_class=HTMLResponse)
async def visits_page(
    request: Request,
    db: Session = Depends(get_db)
):
    visits = (
        db.query(PropertyVisit)
        .order_by(PropertyVisit.created_at.desc())
        .all()
    )

    current_user = request.state.user

    return templates.TemplateResponse(
        request=request,
        name="visits/home.html",
        context={
            "request": request,
            "visits": visits,
            "current_user": current_user
        }
    )


@router.get("/visits/select-property", response_class=HTMLResponse)
async def select_property(
    request: Request,
    db: Session = Depends(get_db)
):
    from app.core.constants import PropertyStatus

    properties = (
        db.query(Property)
        .filter(Property.status != PropertyStatus.ARCHIVED)
        .order_by(Property.title)
        .all()
    )

    return templates.TemplateResponse(
        request=request,
        name="visits/select_property.html",
        context={
            "request": request,
            "properties": properties,
            "current_user": request.state.user
        }
    )


@router.get("/visits/new/{property_id}", response_class=HTMLResponse)
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

    if not property_item:
        response = RedirectResponse(url="/properties", status_code=302)
        set_flash(response, "error", "Propiedad no encontrada")
        return response

    return templates.TemplateResponse(
        request=request,
        name="properties/visit_form.html",
        context={
            "request": request,
            "property": property_item,
            "current_user": request.state.user
        }
    )


@router.post("/visits/create/{property_id}")
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

                visit.visit_sheet_filename = filename
                visit.visit_sheet_filepath = str(output_path)
                visit.visit_sheet_generated_at = datetime.utcnow()
                db.commit()

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

                visit.visit_sheet_sent_to = ", ".join(sent_to) if sent_to else None
                db.commit()

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


@router.get("/visits/{visit_id}/download")
async def download_visit_sheet(
    visit_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    visit = db.query(PropertyVisit).filter(
        PropertyVisit.id == visit_id
    ).first()

    if not visit or not visit.visit_sheet_filepath:
        response = RedirectResponse(url="/properties", status_code=302)
        set_flash(response, "error", "Ficha de visita no encontrada")
        return response

    filepath = Path(visit.visit_sheet_filepath)

    if not filepath.exists():
        response = RedirectResponse(url=f"/properties/{visit.property_id}", status_code=302)
        set_flash(response, "error", "Archivo de ficha de visita no existe")
        return response

    return FileResponse(
        path=str(filepath),
        filename=visit.visit_sheet_filename,
        media_type="application/pdf"
    )


@router.post("/visits/{visit_id}/send-whatsapp")
async def send_visit_sheet_whatsapp(
    visit_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    visit = db.query(PropertyVisit).filter(
        PropertyVisit.id == visit_id
    ).first()

    redirect_url = request.headers.get("referer") or "/visits"

    if not visit:
        response = RedirectResponse(url=redirect_url, status_code=302)
        set_flash(response, "error", "Visita no encontrada")
        return response

    property_item = db.query(Property).filter(Property.id == visit.property_id).first()

    if not property_item:
        response = RedirectResponse(url=redirect_url, status_code=302)
        set_flash(response, "error", "Propiedad no encontrada")
        return response

    if not visit.visit_sheet_filepath:
        response = RedirectResponse(url=redirect_url, status_code=302)
        set_flash(response, "error", "Esta visita no tiene ficha generada")
        return response

    filepath = Path(visit.visit_sheet_filepath)

    if not filepath.exists():
        response = RedirectResponse(url=redirect_url, status_code=302)
        set_flash(response, "error", "Archivo de ficha no existe")
        return response

    file_url = settings.public_url(str(filepath))

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
        response = RedirectResponse(url=redirect_url, status_code=302)
        set_flash(response, "success", f"Ficha enviada a {' y '.join(sent_to)}")
        return response
    else:
        response = RedirectResponse(url=redirect_url, status_code=302)
        set_flash(response, "error", "No se pudo enviar la ficha (verifique números de teléfono)")
        return response


@router.get("/visits/edit/{visit_id}", response_class=HTMLResponse)
async def edit_visit(
    visit_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    visit = db.query(PropertyVisit).filter(
        PropertyVisit.id == visit_id
    ).first()

    if not visit:
        response = RedirectResponse(url="/visits", status_code=302)
        set_flash(response, "error", "Visita no encontrada")
        return response

    return templates.TemplateResponse(
        request=request,
        name="visits/edit_form.html",
        context={
            "request": request,
            "visit": visit,
            "current_user": request.state.user
        }
    )


@router.post("/visits/update/{visit_id}")
async def update_visit(
    visit_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    visit = db.query(PropertyVisit).filter(
        PropertyVisit.id == visit_id
    ).first()

    if not visit:
        response = RedirectResponse(url="/visits", status_code=302)
        set_flash(response, "error", "Visita no encontrada")
        return response

    form = await request.form()

    interest_level_raw = form.get("interest_level")
    interest_level = None
    if interest_level_raw not in (None, ""):
        try:
            interest_level = int(interest_level_raw)
        except (TypeError, ValueError):
            interest_level = None

    # Guardar si tenía PDF antes de actualizar
    had_pdf = visit.visit_sheet_filepath is not None

    try:
        visit.visitor_name = form.get("visitor_name")
        visit.dni = form.get("dni") or None
        visit.phone = form.get("phone") or None
        visit.email = form.get("email") or None
        visit.interest_level = interest_level
        visit.price_feedback = form.get("price_feedback") or None
        visit.location_feedback = form.get("location_feedback") or None
        visit.condition_feedback = form.get("condition_feedback") or None
        visit.lighting_feedback = form.get("lighting_feedback") or None
        visit.elevator_feedback = form.get("elevator_feedback") or None
        visit.garage_feedback = form.get("garage_feedback") or None
        visit.notes = form.get("notes") or None

        db.commit()

        # Si tenía PDF, regenerarlo automáticamente con los datos actualizados
        if had_pdf:
            try:
                property_item = db.query(Property).filter(Property.id == visit.property_id).first()

                if property_item:
                    visits_dir = Path("storage/visit_sheets")
                    visits_dir.mkdir(parents=True, exist_ok=True)

                    # Eliminar PDF anterior
                    if visit.visit_sheet_filepath:
                        old_path = Path(visit.visit_sheet_filepath)
                        if old_path.exists():
                            old_path.unlink()
                            logger.info("PDF anterior eliminado antes de regenerar: %s", visit.visit_sheet_filepath)

                    # Generar nuevo PDF con datos actualizados
                    filename = f"ficha_visita_{property_item.id}_{visit.id}_{uuid4().hex[:8]}.pdf"
                    output_path = visits_dir / filename

                    generate_visit_sheet(
                        property_item=property_item,
                        visit=visit,
                        agent=property_item.agent,
                        output_path=str(output_path)
                    )

                    visit.visit_sheet_filename = filename
                    visit.visit_sheet_filepath = str(output_path)
                    visit.visit_sheet_generated_at = datetime.utcnow()
                    db.commit()

                    logger.info("Ficha de visita regenerada después de edición: %s", output_path)

                    response = RedirectResponse(url="/visits", status_code=302)
                    set_flash(response, "success", "Visita actualizada y ficha PDF regenerada correctamente")
                    return response

            except Exception:
                logger.exception("Error regenerando PDF después de editar visita: visit_id=%s", visit_id)
                response = RedirectResponse(url="/visits", status_code=302)
                set_flash(response, "warning", "Visita actualizada, pero no se pudo regenerar el PDF")
                return response

        response = RedirectResponse(url="/visits", status_code=302)
        set_flash(response, "success", "Visita actualizada correctamente")
        return response

    except Exception:
        db.rollback()
        logger.exception("Error actualizando visita: visit_id=%s", visit_id)
        response = RedirectResponse(url="/visits", status_code=302)
        set_flash(response, "error", "Ocurrió un error al actualizar la visita")
        return response


@router.post("/visits/delete")
async def delete_visit(
    request: Request,
    visit_id: int = Form(...),
    db: Session = Depends(get_db)
):
    import os

    visit = db.query(PropertyVisit).filter(
        PropertyVisit.id == visit_id
    ).first()

    response = RedirectResponse(url="/visits", status_code=302)

    if not visit:
        set_flash(response, "error", "Visita no encontrada")
        return response

    try:
        # Eliminar archivo PDF si existe
        if visit.visit_sheet_filepath and os.path.exists(visit.visit_sheet_filepath):
            os.remove(visit.visit_sheet_filepath)
            logger.info("Archivo PDF eliminado: %s", visit.visit_sheet_filepath)

        db.delete(visit)
        db.commit()

        set_flash(response, "success", "Visita eliminada correctamente")
    except Exception:
        db.rollback()
        logger.exception("Error eliminando visita: visit_id=%s", visit_id)
        set_flash(response, "error", "Ocurrió un error al eliminar la visita")

    return response


@router.post("/visits/{visit_id}/generate-pdf")
async def generate_visit_pdf(
    visit_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    visit = db.query(PropertyVisit).filter(
        PropertyVisit.id == visit_id
    ).first()

    redirect_url = request.headers.get("referer") or "/visits"

    if not visit:
        response = RedirectResponse(url=redirect_url, status_code=302)
        set_flash(response, "error", "Visita no encontrada")
        return response

    property_item = db.query(Property).filter(Property.id == visit.property_id).first()

    if not property_item:
        response = RedirectResponse(url=redirect_url, status_code=302)
        set_flash(response, "error", "Propiedad no encontrada")
        return response

    try:
        visits_dir = Path("storage/visit_sheets")
        visits_dir.mkdir(parents=True, exist_ok=True)

        # Si ya existe un PDF, eliminarlo
        if visit.visit_sheet_filepath:
            old_path = Path(visit.visit_sheet_filepath)
            if old_path.exists():
                old_path.unlink()
                logger.info("PDF anterior eliminado: %s", visit.visit_sheet_filepath)

        filename = f"ficha_visita_{property_item.id}_{visit.id}_{uuid4().hex[:8]}.pdf"
        output_path = visits_dir / filename

        generate_visit_sheet(
            property_item=property_item,
            visit=visit,
            agent=property_item.agent,
            output_path=str(output_path)
        )

        visit.visit_sheet_filename = filename
        visit.visit_sheet_filepath = str(output_path)
        visit.visit_sheet_generated_at = datetime.utcnow()
        db.commit()

        logger.info("Ficha de visita generada: %s", output_path)

        response = RedirectResponse(url=redirect_url, status_code=302)
        set_flash(response, "success", "Ficha de visita generada correctamente")
        return response

    except Exception:
        db.rollback()
        logger.exception("Error generando ficha de visita: visit_id=%s", visit_id)
        response = RedirectResponse(url=redirect_url, status_code=302)
        set_flash(response, "error", "Ocurrió un error al generar la ficha")
        return response
