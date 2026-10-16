"""
API endpoints para el flujo legal de visitas.

Estos endpoints manejan el proceso de:
- Aceptación de términos RGPD
- Captura de firma digital
- Finalización y generación de PDF

Las rutas /api no pasan por AuthMiddleware: cada endpoint resuelve usuario y
empresa activa desde las cookies con `_visit_for_api` (401 sin sesión, 404 si
la visita no es de la empresa activa). PLAN_FIRMA_AGENTES_VISITA.md, decisión 6.
"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter
from fastapi import Request
from fastapi import Depends
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.deps import get_db
from app.models.property import Property
from app.services.visit_audit_service import (
    log_visit_event,
    get_client_ip,
    get_user_agent
)
from app.services.visit_whatsapp_log_service import log_whatsapp_attempt
from app.services.company_scope import get_visit_in_company
from app.web.dependencies.company import get_api_user
from app.web.dependencies.company import resolve_company_for_api


router = APIRouter()
logger = logging.getLogger(__name__)


def _visit_for_api(request: Request, db: Session, visit_id: int):
    """Visita de la empresa activa del usuario de la sesión.

    Devuelve (visit, user). Lanza 401 si no hay sesión válida y 404 si la
    visita no existe o es de otra empresa (no se distingue, para no revelar
    visitas ajenas).
    """
    user = get_api_user(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="No autenticado")

    company = resolve_company_for_api(request, user, db)
    visit = get_visit_in_company(db, visit_id, company.id) if company is not None else None
    if visit is None:
        raise HTTPException(status_code=404, detail="Visita no encontrada")

    return visit, user


class AcceptTermsRequest(BaseModel):
    accepted: bool
    timestamp: Optional[str] = None


class SaveSignatureRequest(BaseModel):
    signature_data: str


class ConfirmAgentSignaturesRequest(BaseModel):
    confirmed: bool


def _agent_signatures_url(visit_id: int) -> str:
    return f"/visits/agent-signatures/{visit_id}"


def _missing_signature_detail(agents) -> str:
    names = " y ".join(agent.name for agent in agents)
    if len(agents) == 1:
        lead, action = f"{names} no tiene firma registrada", "Regístrala"
    else:
        lead, action = f"{names} no tienen firma registrada", "Regístralas"
    return (
        f"{lead}. {action} en Agentes o quita al acompañante "
        "para finalizar como visita individual."
    )


@router.post("/{visit_id}/accept-terms")
async def accept_terms(
    visit_id: int,
    data: AcceptTermsRequest,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Registra la aceptación de términos RGPD por parte del cliente.
    FASE 2 del flujo legal.
    """
    visit, user = _visit_for_api(request, db, visit_id)

    # Verificar que la visita está en estado preview
    if visit.visit_status != 'preview':
        raise HTTPException(
            status_code=400,
            detail=f"La visita debe estar en estado 'preview' (estado actual: '{visit.visit_status}')"
        )

    if not data.accepted:
        raise HTTPException(status_code=400, detail="Debe aceptar los términos para continuar")

    try:
        # Registrar aceptación de consentimiento
        visit.data_consent_accepted = True
        visit.data_consent_accepted_at = datetime.utcnow()
        visit.data_consent_ip = get_client_ip(request)
        visit.data_consent_user_agent = get_user_agent(request)

        db.commit()

        # Registrar en auditoría
        log_visit_event(
            visit=visit,
            event_type='consent_accepted',
            db=db,
            request=request,
            user_id=user.id,
            event_data={
                'accepted_at': visit.data_consent_accepted_at.isoformat(),
                'ip_masked': visit.data_consent_ip[:10] + "..." if visit.data_consent_ip else None
            }
        )

        logger.info(f"Terms accepted for visit {visit_id}")

        return {
            "success": True,
            "redirect_url": f"/visits/signature/{visit_id}"
        }

    except Exception as e:
        db.rollback()
        logger.exception(f"Error accepting terms for visit {visit_id}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{visit_id}/save-signature")
async def save_signature(
    visit_id: int,
    data: SaveSignatureRequest,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Guarda la firma digital del cliente como archivo en disco.
    FASE 3 del flujo legal.
    """
    from app.services.signature_service import (
        validate_signature_not_empty,
        save_signature_to_file
    )

    visit, user = _visit_for_api(request, db, visit_id)

    # Verificar que se aceptaron los términos
    if not visit.data_consent_accepted:
        raise HTTPException(
            status_code=400,
            detail="Debe aceptar los términos antes de firmar"
        )

    # Validar que la firma no esté vacía (con threshold más bajo para mayor tolerancia)
    is_valid, error_message = validate_signature_not_empty(data.signature_data, min_variance=10.0)
    if not is_valid:
        logger.warning(f"Signature validation failed for visit {visit_id}: {error_message}")
        raise HTTPException(status_code=400, detail=error_message)

    try:
        # Guardar firma como archivo
        filename, filepath = save_signature_to_file(
            signature_base64=data.signature_data,
            visit_id=visit_id
        )

        # Actualizar registro de visita
        visit.signature_filename = filename
        visit.signature_filepath = filepath
        visit.signature_captured_at = datetime.utcnow()
        visit.signature_ip = get_client_ip(request)
        visit.visit_status = 'signed'

        db.commit()

        # Registrar en auditoría
        log_visit_event(
            visit=visit,
            event_type='signature_captured',
            db=db,
            request=request,
            user_id=user.id,
            event_data={
                'filename': filename,
                'captured_at': visit.signature_captured_at.isoformat()
            }
        )

        logger.info(f"Signature saved for visit {visit_id}: {filepath}")

        # Visita conjunta: antes de finalizar, los agentes confirman sus
        # firmas registradas (PLAN_FIRMA_AGENTES_VISITA.md §3.2)
        if visit.requires_agent_confirmation:
            redirect_url = _agent_signatures_url(visit_id)
        else:
            redirect_url = f"/visits/complete/{visit_id}"

        return {
            "success": True,
            "redirect_url": redirect_url
        }

    except Exception as e:
        db.rollback()
        logger.exception(f"Error saving signature for visit {visit_id}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{visit_id}/confirm-agent-signatures")
async def confirm_agent_signatures(
    visit_id: int,
    data: ConfirmAgentSignaturesRequest,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    El agente logueado confirma que la ficha de una visita conjunta se firma
    con las firmas registradas de los dos agentes (modalidad A).
    PLAN_FIRMA_AGENTES_VISITA.md §3.3. Se registra quién, cuándo y desde qué IP.
    """
    visit, user = _visit_for_api(request, db, visit_id)

    if not data.confirmed:
        raise HTTPException(status_code=400, detail="Marca la casilla de confirmación para continuar")

    if visit.visit_status != 'signed':
        raise HTTPException(
            status_code=400,
            detail=f"El cliente debe haber firmado la visita (estado actual: '{visit.visit_status}')"
        )

    if not visit.requires_agent_confirmation:
        raise HTTPException(status_code=400, detail="La visita no tiene agente acompañante")

    if visit.agent_signatures_confirmed:
        raise HTTPException(status_code=409, detail="Las firmas de los agentes ya están confirmadas")

    missing = visit.agents_missing_signature
    if missing:
        raise HTTPException(status_code=400, detail=_missing_signature_detail(missing))

    principal = visit.signing_agent
    companion = visit.companion_agent

    try:
        visit.agent_signatures_confirmed_at = datetime.utcnow()
        visit.agent_signatures_confirmed_by = user.id
        visit.agent_signatures_confirmed_ip = get_client_ip(request)
        db.commit()

        log_visit_event(
            visit=visit,
            event_type='agent_signatures_confirmed',
            db=db,
            request=request,
            user_id=user.id,
            event_data={
                'agent_id': principal.id,
                'companion_agent_id': companion.id,
                'agent_signature_uploaded_at': (
                    principal.signature_uploaded_at.isoformat() if principal.signature_uploaded_at else None
                ),
                'companion_signature_uploaded_at': (
                    companion.signature_uploaded_at.isoformat() if companion.signature_uploaded_at else None
                ),
                'confirmed_at': visit.agent_signatures_confirmed_at.isoformat(),
            }
        )

        logger.info(f"Agent signatures confirmed for visit {visit_id} by user {user.id}")

        return {
            "success": True,
            "redirect_url": f"/visits/complete/{visit_id}"
        }

    except Exception as e:
        db.rollback()
        logger.exception(f"Error confirming agent signatures for visit {visit_id}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{visit_id}/finalize")
async def finalize_visit(
    visit_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Finaliza la visita, genera PDF con firma y envía por WhatsApp.
    FASE 4 del flujo legal.
    """
    from pathlib import Path
    from time import perf_counter
    from uuid import uuid4
    from app.services.visit_sheet_generator import generate_visit_sheet
    from app.services.whatsapp import send_report
    from app.core.config import settings

    visit, user = _visit_for_api(request, db, visit_id)

    property_item = db.query(Property).filter(
        Property.id == visit.property_id
    ).first()

    if not property_item:
        raise HTTPException(status_code=404, detail="Propiedad no encontrada")

    # Verificar que está en estado 'signed'
    if visit.visit_status != 'signed':
        raise HTTPException(
            status_code=400,
            detail=f"La visita debe estar firmada (estado actual: '{visit.visit_status}')"
        )

    # Verificar que tiene firma
    if not visit.signature_filepath:
        raise HTTPException(status_code=400, detail="Falta la firma digital")

    # Visita conjunta: firmas de los agentes confirmadas y registradas
    if visit.requires_agent_confirmation:
        if not visit.agent_signatures_confirmed:
            return JSONResponse(status_code=409, content={
                "detail": "Falta confirmar las firmas de los agentes",
                "redirect_url": _agent_signatures_url(visit_id),
            })
        missing = visit.agents_missing_signature
        if missing:
            raise HTTPException(status_code=400, detail=_missing_signature_detail(missing))

    try:
        # Generar PDF con firma
        visits_dir = Path("storage/visit_sheets")
        visits_dir.mkdir(parents=True, exist_ok=True)

        filename = f"ficha_visita_{property_item.id}_{visit.id}_{uuid4().hex[:8]}.pdf"
        output_path = visits_dir / filename

        generate_visit_sheet(
            property_item=property_item,
            visit=visit,
            agent=visit.signing_agent,
            companion_agent=visit.companion_agent,
            output_path=str(output_path)
        )

        visit.visit_sheet_filename = filename
        visit.visit_sheet_filepath = str(output_path)
        visit.visit_sheet_generated_at = datetime.utcnow()

        # Registrar evento de generación
        log_visit_event(
            visit=visit,
            event_type='pdf_generated',
            db=db,
            request=request,
            user_id=user.id,
            event_data={
                'filename': filename,
                'generated_at': visit.visit_sheet_generated_at.isoformat()
            }
        )

        logger.info(f"Visit sheet generated: {output_path}")

        # Enviar por WhatsApp
        file_url = settings.public_url(str(output_path))
        sent_to = []
        send_failed = False

        if visit.phone:
            started_at = perf_counter()
            try:
                send_report(
                    phone=visit.phone,
                    file_url=file_url,
                    caption=f"Ficha de visita - {property_item.title}"
                )
                sent_to.append("comprador")
                logger.info(f"Sheet sent to buyer: {visit.phone}")
                log_whatsapp_attempt(
                    db=db,
                    visit_id=visit.id,
                    property_id=property_item.id,
                    recipient_type="comprador",
                    recipient_name=visit.visitor_name,
                    recipient_phone=visit.phone,
                    status="SENT",
                    trigger="finalize",
                    file_url=file_url,
                    duration_ms=int((perf_counter() - started_at) * 1000)
                )
            except Exception as e:
                send_failed = True
                logger.exception(f"Error sending sheet to buyer: {visit.phone}")
                log_whatsapp_attempt(
                    db=db,
                    visit_id=visit.id,
                    property_id=property_item.id,
                    recipient_type="comprador",
                    recipient_name=visit.visitor_name,
                    recipient_phone=visit.phone,
                    status="ERROR",
                    trigger="finalize",
                    error_message=str(e),
                    file_url=file_url,
                    duration_ms=int((perf_counter() - started_at) * 1000)
                )
        else:
            log_whatsapp_attempt(
                db=db,
                visit_id=visit.id,
                property_id=property_item.id,
                recipient_type="comprador",
                recipient_name=visit.visitor_name,
                status="SKIPPED",
                trigger="finalize",
                error_message="Visita sin teléfono registrado"
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
        #         logger.info(f"Sheet sent to agent: {property_item.agent.phone}")
        #     except Exception as e:
        #         logger.exception(f"Error sending sheet to agent: {property_item.agent.phone}")

        visit.visit_sheet_sent_to = ", ".join(sent_to) if sent_to else None

        # Cambiar estado a completado
        visit.visit_status = 'completed'
        db.commit()

        # Registrar completación
        log_visit_event(
            visit=visit,
            event_type='visit_completed',
            db=db,
            request=request,
            user_id=user.id,
            event_data={
                'sent_to': sent_to,
                'completed_at': datetime.utcnow().isoformat()
            }
        )

        logger.info(f"Visit {visit_id} completed successfully")

        # Avisos in-app (nunca email ni WhatsApp). Esta ruta /api no pasa por
        # el middleware: el actor es el usuario de la cookie (_visit_for_api).
        from app.services.notification_service import notify_visit_completed
        from app.services.notification_service import notify_visit_sheet_failed

        notify_visit_completed(db, visit, actor=user, sent=bool(sent_to))
        if send_failed:
            notify_visit_sheet_failed(db, visit, actor=user)

        return {
            "success": True,
            "pdf_generated": True,
            "pdf_sent": len(sent_to) > 0,
            "sent_to": sent_to,
            "visit_sheet_url": f"/visits/{visit_id}/download",
            "redirect_url": f"/properties/{property_item.id}"
        }

    except Exception as e:
        db.rollback()
        logger.exception(f"Error finalizing visit {visit_id}")
        raise HTTPException(status_code=500, detail=str(e))
