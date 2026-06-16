"""
Servicio de auditoría para el sistema de visitas legales.

Este servicio proporciona funciones para:
- Registrar eventos del flujo de visitas
- Capturar metadatos de auditoría (IP, User-Agent, timestamps)
- Generar trazas de auditoría para cumplimiento legal
"""

import logging
from datetime import datetime
from typing import Optional, Dict, Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.models.property_visit import PropertyVisit
from app.models.visit_audit_log import VisitAuditLog


logger = logging.getLogger(__name__)


def get_client_ip(request: Request) -> str:
    """
    Obtiene la dirección IP del cliente desde la request.

    Considera headers de proxy (X-Forwarded-For, X-Real-IP)
    para obtener la IP real del cliente.
    """
    # Intentar obtener IP desde headers de proxy
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        # X-Forwarded-For puede contener múltiples IPs, tomamos la primera
        return forwarded_for.split(",")[0].strip()

    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()

    # Si no hay headers de proxy, usar la IP del cliente directo
    if request.client:
        return request.client.host

    return "unknown"


def get_user_agent(request: Request) -> str:
    """
    Obtiene el User-Agent del cliente desde la request.
    """
    return request.headers.get("user-agent", "unknown")


def create_audit_log(
    visit_id: int,
    event_type: str,
    db: Session,
    request: Request = None,
    event_data: Optional[Dict[str, Any]] = None,
    user_id: Optional[int] = None
) -> VisitAuditLog:
    """
    Crea un registro de auditoría para un evento de visita.

    Args:
        visit_id: ID de la visita
        event_type: Tipo de evento (ver VisitAuditLog para tipos válidos)
        db: Sesión de base de datos
        request: Request de FastAPI (para capturar IP y User-Agent)
        event_data: Datos adicionales del evento en formato dict
        user_id: ID del usuario que ejecuta la acción

    Returns:
        VisitAuditLog creado
    """
    ip_address = None
    user_agent = None

    if request:
        ip_address = get_client_ip(request)
        user_agent = get_user_agent(request)

        # Si no se proporciona user_id, intentar obtenerlo del request.state
        if user_id is None and hasattr(request.state, 'user'):
            user_id = request.state.user.id

    audit_log = VisitAuditLog(
        visit_id=visit_id,
        event_type=event_type,
        event_data=event_data,
        timestamp=datetime.utcnow(),
        ip_address=ip_address,
        user_agent=user_agent,
        user_id=user_id
    )

    db.add(audit_log)
    db.commit()
    db.refresh(audit_log)

    logger.info(
        f"Audit log created: visit_id={visit_id}, event={event_type}, ip={ip_address}"
    )

    return audit_log


def update_visit_audit_trail(
    visit: PropertyVisit,
    event_type: str,
    event_data: Optional[Dict[str, Any]],
    db: Session
):
    """
    Actualiza el audit_trail JSON de una visita con un nuevo evento.

    El audit_trail es un array JSON que mantiene un resumen
    de los eventos principales directamente en el registro de visita.
    """
    if visit.audit_trail is None:
        visit.audit_trail = []

    event_entry = {
        "event_type": event_type,
        "timestamp": datetime.utcnow().isoformat(),
        "data": event_data or {}
    }

    visit.audit_trail.append(event_entry)
    db.commit()


def log_visit_event(
    visit: PropertyVisit,
    event_type: str,
    db: Session,
    request: Request = None,
    event_data: Optional[Dict[str, Any]] = None,
    user_id: Optional[int] = None
):
    """
    Función de conveniencia que registra un evento tanto en
    VisitAuditLog (tabla) como en audit_trail (JSON del visit).

    Esta es la función recomendada para usar en los endpoints.
    """
    # Crear registro detallado en tabla
    create_audit_log(
        visit_id=visit.id,
        event_type=event_type,
        db=db,
        request=request,
        event_data=event_data,
        user_id=user_id
    )

    # Actualizar resumen en JSON
    update_visit_audit_trail(
        visit=visit,
        event_type=event_type,
        event_data=event_data,
        db=db
    )


def get_visit_audit_history(visit_id: int, db: Session) -> list:
    """
    Obtiene el historial completo de auditoría de una visita.

    Returns:
        Lista de VisitAuditLog ordenados por timestamp
    """
    return (
        db.query(VisitAuditLog)
        .filter(VisitAuditLog.visit_id == visit_id)
        .order_by(VisitAuditLog.timestamp)
        .all()
    )


def validate_visit_compliance(visit: PropertyVisit) -> Dict[str, Any]:
    """
    Valida que una visita cumple con todos los requisitos legales.

    Returns:
        Dict con:
        - compliant: bool indicando si cumple
        - issues: lista de problemas encontrados
        - warnings: lista de advertencias
    """
    issues = []
    warnings = []

    # Verificar consentimiento de datos
    if not visit.data_consent_accepted:
        issues.append("Consentimiento RGPD no aceptado")

    if visit.data_consent_accepted and not visit.data_consent_accepted_at:
        issues.append("Falta timestamp de aceptación de consentimiento")

    if visit.data_consent_accepted and not visit.data_consent_ip:
        warnings.append("No se registró IP de aceptación de consentimiento")

    # Verificar firma
    if not visit.signature_filepath:
        issues.append("Falta firma digital")

    if visit.signature_filepath and not visit.signature_captured_at:
        issues.append("Falta timestamp de captura de firma")

    if visit.signature_filepath and not visit.signature_ip:
        warnings.append("No se registró IP de captura de firma")

    # Verificar estado
    if visit.visit_status != 'completed':
        warnings.append(f"Visita en estado '{visit.visit_status}', no completada")

    # Verificar audit trail
    if not visit.audit_trail or len(visit.audit_trail) == 0:
        warnings.append("Audit trail vacío o inexistente")

    return {
        "compliant": len(issues) == 0,
        "issues": issues,
        "warnings": warnings
    }


def mask_ip_address(ip_address: str) -> str:
    """
    Ofusca una dirección IP para cumplir con privacidad.

    Ejemplo: 192.168.1.100 -> 192.168.xxx.xxx
    """
    if not ip_address or ip_address == "unknown":
        return "unknown"

    parts = ip_address.split(".")
    if len(parts) == 4:
        return f"{parts[0]}.{parts[1]}.xxx.xxx"

    # Para IPv6 o formatos no estándar, solo mostrar los primeros caracteres
    if len(ip_address) > 8:
        return ip_address[:8] + "..." + "x" * 8

    return "xxx.xxx.xxx.xxx"
