"""
API endpoints para el flujo legal de visitas.

Estos endpoints manejan el proceso de:
- Aceptación de términos RGPD
- Captura de firma digital
- Finalización y generación de PDF
"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter
from fastapi import Request
from fastapi import Depends
from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.deps import get_db
from app.models.property_visit import PropertyVisit
from app.models.property import Property
from app.services.visit_audit_service import (
    log_visit_event,
    get_client_ip,
    get_user_agent
)


router = APIRouter()
logger = logging.getLogger(__name__)


class AcceptTermsRequest(BaseModel):
    accepted: bool
    timestamp: Optional[str] = None


class SaveSignatureRequest(BaseModel):
    signature_data: str


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
    visit = db.query(PropertyVisit).filter(
        PropertyVisit.id == visit_id
    ).first()

    if not visit:
        raise HTTPException(status_code=404, detail="Visita no encontrada")

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

    visit = db.query(PropertyVisit).filter(
        PropertyVisit.id == visit_id
    ).first()

    if not visit:
        raise HTTPException(status_code=404, detail="Visita no encontrada")

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
            event_data={
                'filename': filename,
                'captured_at': visit.signature_captured_at.isoformat()
            }
        )

        logger.info(f"Signature saved for visit {visit_id}: {filepath}")

        return {
            "success": True,
            "redirect_url": f"/visits/complete/{visit_id}"
        }

    except Exception as e:
        db.rollback()
        logger.exception(f"Error saving signature for visit {visit_id}")
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
    from uuid import uuid4
    from app.services.visit_sheet_generator import generate_visit_sheet
    from app.services.whatsapp import send_report
    from app.core.config import settings

    visit = db.query(PropertyVisit).filter(
        PropertyVisit.id == visit_id
    ).first()

    if not visit:
        raise HTTPException(status_code=404, detail="Visita no encontrada")

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

    try:
        # Generar PDF con firma
        visits_dir = Path("storage/visit_sheets")
        visits_dir.mkdir(parents=True, exist_ok=True)

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

        # Registrar evento de generación
        log_visit_event(
            visit=visit,
            event_type='pdf_generated',
            db=db,
            request=request,
            event_data={
                'filename': filename,
                'generated_at': visit.visit_sheet_generated_at.isoformat()
            }
        )

        logger.info(f"Visit sheet generated: {output_path}")

        # Enviar por WhatsApp
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
                logger.info(f"Sheet sent to buyer: {visit.phone}")
            except Exception as e:
                logger.exception(f"Error sending sheet to buyer: {visit.phone}")

        if property_item.agent and property_item.agent.phone:
            try:
                send_report(
                    phone=property_item.agent.phone,
                    file_url=file_url,
                    caption=f"Ficha de visita - {property_item.title}"
                )
                sent_to.append("agente")
                logger.info(f"Sheet sent to agent: {property_item.agent.phone}")
            except Exception as e:
                logger.exception(f"Error sending sheet to agent: {property_item.agent.phone}")

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
            event_data={
                'sent_to': sent_to,
                'completed_at': datetime.utcnow().isoformat()
            }
        )

        logger.info(f"Visit {visit_id} completed successfully")

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
