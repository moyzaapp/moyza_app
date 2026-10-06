import logging
import re
from datetime import datetime
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from fastapi import APIRouter
from fastapi import Request
from fastapi import Depends
from fastapi import Form
from fastapi.responses import HTMLResponse
from fastapi.responses import RedirectResponse
from fastapi.responses import FileResponse
from app.web.template_env import templates

from sqlalchemy.orm import Session

from app.db.deps import get_db
from app.models.property import Property
from app.models.property_visit import PropertyVisit
from app.services.visit_sheet_generator import generate_visit_sheet
from app.services.whatsapp import send_report
from app.core.config import settings
from app.web.utils.flash import set_flash
from app.web.dependencies.auth import is_admin, get_agent_from_user
from app.core.constants import PhoneCountryCodes
from app.services.visit_whatsapp_log_service import log_whatsapp_attempt
from app.services.company_scope import (
    scope_visits,
    scope_properties,
    get_visit_in_company,
    get_property_in_company,
)
from app.web.dependencies.company import get_active_company


router = APIRouter()
logger = logging.getLogger(__name__)

# Importe de honorarios: dígitos con separadores opcionales (2500, 2.500, 2500,50)
PURCHASE_FEES_PATTERN = re.compile(r"\d[\d.,]*")



@router.get("/visits", response_class=HTMLResponse)
async def visits_page(
    request: Request,
    db: Session = Depends(get_db)
):
    current_user = request.state.user

    # Si es admin, mostrar todas las visitas de la empresa activa
    # Si es agente, mostrar solo visitas de sus propiedades
    visits_query = scope_visits(db.query(PropertyVisit), get_active_company(request).id)

    if not is_admin(current_user):
        agent = get_agent_from_user(current_user, db)
        if agent:
            # Filtrar visitas por propiedades del agente
            visits_query = visits_query.join(Property).filter(Property.agent_id == agent.id)
        else:
            # Si no tiene agente, no mostrar nada
            visits_query = visits_query.filter(PropertyVisit.id == -1)

    visits = visits_query.order_by(PropertyVisit.created_at.desc()).all()

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

    current_user = request.state.user

    properties_query = scope_properties(
        db.query(Property).filter(
            Property.status != PropertyStatus.ARCHIVED,
            Property.available_clause()
        ),
        get_active_company(request).id
    )

    # Si no es admin, filtrar solo sus propiedades
    if not is_admin(current_user):
        agent = get_agent_from_user(current_user, db)
        if agent:
            properties_query = properties_query.filter(Property.agent_id == agent.id)
        else:
            properties_query = properties_query.filter(Property.id == -1)

    properties = properties_query.order_by(Property.title).all()

    return templates.TemplateResponse(
        request=request,
        name="visits/select_property.html",
        context={
            "request": request,
            "properties": properties,
            "current_user": current_user
        }
    )


@router.get("/visits/new/{property_id}", response_class=HTMLResponse)
async def new_visit(
    property_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    property_item = get_property_in_company(db, property_id, get_active_company(request).id)

    if not property_item:
        response = RedirectResponse(url="/properties", status_code=302)
        set_flash(response, "error", "Propiedad no encontrada")
        return response

    if not property_item.is_available:
        response = RedirectResponse(url=f"/properties/{property_id}", status_code=302)
        set_flash(response, "error", "No se pueden registrar visitas en una propiedad No disponible")
        return response

    return templates.TemplateResponse(
        request=request,
        name="properties/visit_form.html",
        context={
            "request": request,
            "property": property_item,
            "current_user": request.state.user,
            "phone_countries": PhoneCountryCodes.choices(),
            "default_country_code": PhoneCountryCodes.DEFAULT
        }
    )


@router.post("/visits/create/{property_id}")
async def create_visit(
    property_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    from app.services.visit_audit_service import log_visit_event

    property_item = get_property_in_company(db, property_id, get_active_company(request).id)

    if not property_item or not property_item.is_available:
        response = RedirectResponse(url=f"/properties/{property_id}", status_code=302)
        set_flash(response, "error", "No se pueden registrar visitas en una propiedad No disponible")
        return response

    form = await request.form()

    interest_level_raw = form.get("interest_level")
    interest_level = None
    if interest_level_raw not in (None, ""):
        try:
            interest_level = int(interest_level_raw)
        except (TypeError, ValueError):
            interest_level = None

    generate_sheet = form.get("generate_sheet") == "true"

    phone_country_code = (form.get("phone_country_code") or PhoneCountryCodes.DEFAULT).strip()
    phone_number_digits = "".join(ch for ch in (form.get("phone_number") or "") if ch.isdigit())
    phone = f"{phone_country_code}{phone_number_digits}" if phone_number_digits else ""

    visitor_name = (form.get("visitor_name") or "").strip()
    purchase_fees = PropertyVisit.clean_purchase_fees(form.get("purchase_fees"))
    notes = (form.get("notes") or "").strip()

    if not visitor_name or not phone or not purchase_fees or not notes:
        response = RedirectResponse(url=f"/visits/new/{property_id}", status_code=302)
        set_flash(response, "error", "Nombre, teléfono, honorarios y observaciones son obligatorios")
        return response

    if not PURCHASE_FEES_PATTERN.fullmatch(purchase_fees):
        response = RedirectResponse(url=f"/visits/new/{property_id}", status_code=302)
        set_flash(response, "error", "Los honorarios deben ser solo el importe (ej: 2500)")
        return response

    try:
        # Crear visita en estado 'draft' para seguir el nuevo flujo legal
        visit = PropertyVisit(
            property_id=property_id,
            visitor_name=visitor_name,
            dni=form.get("dni"),
            phone=phone,
            email=form.get("email"),
            purchase_fees=purchase_fees,
            interest_level=interest_level,
            price_feedback=form.get("price_feedback"),
            location_feedback=form.get("location_feedback"),
            condition_feedback=form.get("condition_feedback"),
            lighting_feedback=form.get("lighting_feedback"),
            elevator_feedback=form.get("elevator_feedback"),
            garage_feedback=form.get("garage_feedback"),
            notes=notes,
            created_by=request.state.user.id,
            visit_status='draft'  # Nuevo flujo: inicia en draft
        )

        db.add(visit)
        db.commit()
        db.refresh(visit)

        # Registrar evento de auditoría
        log_visit_event(
            visit=visit,
            event_type='draft_created',
            db=db,
            request=request,
            event_data={
                'property_id': property_id,
                'visitor_name': visit.visitor_name,
                'generate_sheet': generate_sheet
            }
        )

        # Redirigir al preview en vez de generar PDF inmediatamente
        if generate_sheet:
            response = RedirectResponse(url=f"/visits/preview/{visit.id}", status_code=302)
            set_flash(response, "info", "Por favor, revise el documento antes de firmar")
            return response

        # El PDF no se genera aquí. Se generará después de que el cliente
        # revise el documento, acepte términos y firme (nuevo flujo legal)

        # Si no se solicita generar ficha, comportamiento antiguo (para compatibilidad)
        if not generate_sheet:
            visit.visit_status = 'completed'  # Completar directamente sin flujo legal
            db.commit()

            response = RedirectResponse(url=f"/properties/{property_id}", status_code=302)
            set_flash(response, "success", "Visita registrada")
            return response

    except Exception:
        db.rollback()
        logger.exception("Error registrando visita: property_id=%s", property_id)
        response = RedirectResponse(url=f"/properties/{property_id}", status_code=302)
        set_flash(response, "error", "Ocurrió un error al registrar la visita")
        return response


@router.get("/visits/{visit_id}/download")
async def download_visit_sheet(
    visit_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    visit = get_visit_in_company(db, visit_id, get_active_company(request).id)

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
    visit = get_visit_in_company(db, visit_id, get_active_company(request).id)

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

    triggered_by = request.state.user.id if request.state.user else None

    if visit.phone:
        started_at = perf_counter()
        try:
            send_report(
                phone=visit.phone,
                file_url=file_url,
                caption=f"Ficha de visita - {property_item.title}"
            )
            sent_to.append("comprador")
            logger.info("Ficha enviada al comprador: %s", visit.phone)
            log_whatsapp_attempt(
                db=db,
                visit_id=visit.id,
                property_id=property_item.id,
                recipient_type="comprador",
                recipient_name=visit.visitor_name,
                recipient_phone=visit.phone,
                status="SENT",
                trigger="manual_resend",
                file_url=file_url,
                duration_ms=int((perf_counter() - started_at) * 1000),
                triggered_by=triggered_by
            )
        except Exception as e:
            logger.exception("Error enviando ficha al comprador: %s", visit.phone)
            log_whatsapp_attempt(
                db=db,
                visit_id=visit.id,
                property_id=property_item.id,
                recipient_type="comprador",
                recipient_name=visit.visitor_name,
                recipient_phone=visit.phone,
                status="ERROR",
                trigger="manual_resend",
                error_message=str(e),
                file_url=file_url,
                duration_ms=int((perf_counter() - started_at) * 1000),
                triggered_by=triggered_by
            )
    else:
        log_whatsapp_attempt(
            db=db,
            visit_id=visit.id,
            property_id=property_item.id,
            recipient_type="comprador",
            recipient_name=visit.visitor_name,
            status="SKIPPED",
            trigger="manual_resend",
            error_message="Visita sin teléfono registrado",
            triggered_by=triggered_by
        )

    # # Envio al numero del agente
    # if property_item.agent and property_item.agent.phone:
    #     try:
    #         send_report(
    #             phone=property_item.agent.phone,
    #             file_url=file_url,
    #             caption=f"Ficha de visita - {property_item.title}"
    #         )
    #         sent_to.append("agente")
    #         logger.info("Ficha enviada al agente: %s", property_item.agent.phone)
    #     except Exception:
    #         logger.exception("Error enviando ficha al agente: %s", property_item.agent.phone)

    if sent_to:
        response = RedirectResponse(url=redirect_url, status_code=302)
        set_flash(response, "success", f"Ficha enviada a {' y '.join(sent_to)}")
        return response
    else:
        response = RedirectResponse(url=redirect_url, status_code=302)
        set_flash(response, "error", "No se pudo enviar la ficha (verifique números de teléfono)")
        return response


@router.get("/visits/preview/{visit_id}", response_class=HTMLResponse)
async def preview_visit(
    visit_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Muestra la vista previa del documento de visita antes de la firma.
    FASE 2 del nuevo flujo legal.
    """
    from app.services.visit_audit_service import log_visit_event

    visit = get_visit_in_company(db, visit_id, get_active_company(request).id)

    if not visit:
        response = RedirectResponse(url="/visits", status_code=302)
        set_flash(response, "error", "Visita no encontrada")
        return response

    property_item = db.query(Property).filter(
        Property.id == visit.property_id
    ).first()

    if not property_item:
        response = RedirectResponse(url="/visits", status_code=302)
        set_flash(response, "error", "Propiedad no encontrada")
        return response

    # Verificar que la visita está en estado draft o preview
    if visit.visit_status not in ['draft', 'preview']:
        response = RedirectResponse(url=f"/properties/{property_item.id}", status_code=302)
        set_flash(response, "warning", "Esta visita ya ha sido procesada")
        return response

    # Actualizar estado a preview si viene de draft
    if visit.visit_status == 'draft':
        visit.visit_status = 'preview'
        db.commit()

        # Registrar evento de auditoría
        log_visit_event(
            visit=visit,
            event_type='preview_viewed',
            db=db,
            request=request,
            event_data={'viewed_at': datetime.utcnow().isoformat()}
        )

    # Identidad de la empresa propietaria del inmueble: el preview debe
    # coincidir exactamente con el PDF que se firmará.
    from app.services.company_service import branding_for
    brand = branding_for(property_item.company)

    # Preparar datos para el template
    visit_date = visit.created_at.strftime("%d/%m/%Y") if visit.created_at else datetime.now().strftime("%d/%m/%Y")
    visit_time = visit.created_at.strftime("%H:%M") if visit.created_at else datetime.now().strftime("%H:%M")
    agent_name = property_item.agent.name if property_item.agent else f"Agente {brand.name}"

    logo_exists = brand.logo_fs_path is not None

    return templates.TemplateResponse(
        request=request,
        name="visits/preview.html",
        context={
            "request": request,
            "visit": visit,
            "property": property_item,
            "visit_date": visit_date,
            "visit_time": visit_time,
            "agent_name": agent_name,
            "logo_exists": logo_exists,
            "brand": brand,
            "current_user": request.state.user
        }
    )


@router.get("/visits/signature/{visit_id}", response_class=HTMLResponse)
async def signature_visit(
    visit_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Muestra el canvas de firma digital.
    FASE 3 del nuevo flujo legal.
    """
    visit = get_visit_in_company(db, visit_id, get_active_company(request).id)

    if not visit:
        response = RedirectResponse(url="/visits", status_code=302)
        set_flash(response, "error", "Visita no encontrada")
        return response

    # Verificar que se aceptaron los términos
    if not visit.data_consent_accepted:
        response = RedirectResponse(url=f"/visits/preview/{visit_id}", status_code=302)
        set_flash(response, "warning", "Debe aceptar los términos antes de firmar")
        return response

    # Verificar que no esté ya firmada
    if visit.visit_status == 'signed' or visit.visit_status == 'completed':
        response = RedirectResponse(url=f"/visits/complete/{visit_id}", status_code=302)
        set_flash(response, "info", "Esta visita ya ha sido firmada")
        return response

    return templates.TemplateResponse(
        request=request,
        name="visits/signature.html",
        context={
            "request": request,
            "visit": visit,
            "current_user": request.state.user
        }
    )


@router.get("/visits/complete/{visit_id}", response_class=HTMLResponse)
async def complete_visit_page(
    visit_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Página de confirmación que finaliza el proceso y genera el PDF.
    FASE 4 del nuevo flujo legal.
    """
    visit = get_visit_in_company(db, visit_id, get_active_company(request).id)

    if not visit:
        response = RedirectResponse(url="/visits", status_code=302)
        set_flash(response, "error", "Visita no encontrada")
        return response

    property_item = db.query(Property).filter(
        Property.id == visit.property_id
    ).first()

    if not property_item:
        response = RedirectResponse(url="/visits", status_code=302)
        set_flash(response, "error", "Propiedad no encontrada")
        return response

    # Verificar que tiene firma
    if not visit.signature_filepath:
        response = RedirectResponse(url=f"/visits/signature/{visit_id}", status_code=302)
        set_flash(response, "warning", "Debe firmar antes de continuar")
        return response

    return templates.TemplateResponse(
        request=request,
        name="visits/complete.html",
        context={
            "request": request,
            "visit": visit,
            "property": property_item,
            "current_user": request.state.user
        }
    )


@router.get("/visits/edit/{visit_id}", response_class=HTMLResponse)
async def edit_visit(
    visit_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    visit = get_visit_in_company(db, visit_id, get_active_company(request).id)

    if not visit:
        response = RedirectResponse(url="/visits", status_code=302)
        set_flash(response, "error", "Visita no encontrada")
        return response

    phone_country_code, phone_local_number = PhoneCountryCodes.split(visit.phone)

    return templates.TemplateResponse(
        request=request,
        name="visits/edit_form.html",
        context={
            "request": request,
            "visit": visit,
            "current_user": request.state.user,
            "phone_countries": PhoneCountryCodes.choices(),
            "phone_country_code": phone_country_code,
            "phone_local_number": phone_local_number
        }
    )


@router.post("/visits/update/{visit_id}")
async def update_visit(
    visit_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    visit = get_visit_in_company(db, visit_id, get_active_company(request).id)

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

    phone_country_code = (form.get("phone_country_code") or PhoneCountryCodes.DEFAULT).strip()
    phone_number_digits = "".join(ch for ch in (form.get("phone_number") or "") if ch.isdigit())
    phone = f"{phone_country_code}{phone_number_digits}" if phone_number_digits else ""

    visitor_name = (form.get("visitor_name") or "").strip()
    purchase_fees = PropertyVisit.clean_purchase_fees(form.get("purchase_fees"))
    notes = (form.get("notes") or "").strip()

    if not visitor_name or not phone or not purchase_fees or not notes:
        response = RedirectResponse(url=f"/visits/edit/{visit_id}", status_code=302)
        set_flash(response, "error", "Nombre, teléfono, honorarios y observaciones son obligatorios")
        return response

    if not PURCHASE_FEES_PATTERN.fullmatch(purchase_fees):
        response = RedirectResponse(url=f"/visits/edit/{visit_id}", status_code=302)
        set_flash(response, "error", "Los honorarios deben ser solo el importe (ej: 2500)")
        return response

    try:
        visit.visitor_name = visitor_name
        visit.dni = form.get("dni") or None
        visit.phone = phone
        visit.email = form.get("email") or None
        visit.purchase_fees = purchase_fees
        visit.interest_level = interest_level
        visit.price_feedback = form.get("price_feedback") or None
        visit.location_feedback = form.get("location_feedback") or None
        visit.condition_feedback = form.get("condition_feedback") or None
        visit.lighting_feedback = form.get("lighting_feedback") or None
        visit.elevator_feedback = form.get("elevator_feedback") or None
        visit.garage_feedback = form.get("garage_feedback") or None
        visit.notes = notes

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

    visit = get_visit_in_company(db, visit_id, get_active_company(request).id)

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
    visit = get_visit_in_company(db, visit_id, get_active_company(request).id)

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
