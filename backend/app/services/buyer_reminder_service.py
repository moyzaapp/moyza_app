"""
Servicio de recordatorio de compradores sin gestión.

Identifica compradores cuya última gestión (follow-up o creación de alerta)
supera el umbral de horas configurado, y envía un email de recordatorio al
agente responsable con el listado de compradores pendientes.

Multiempresa: los recordatorios se agrupan por agente Y empresa. Un agente
que trabaja en MOYZA y en MOES PREMIUM recibe un correo por cada empresa,
cada uno con la marca correspondiente.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session
from sqlalchemy.orm import joinedload
from sqlalchemy.orm import selectinload

from app.models.agent import Agent
from app.models.alert_follow_up import AlertFollowUp
from app.models.alert_reminder_log import AlertReminderLog
from app.models.company import Company
from app.models.property_alert import PropertyAlert
from app.services.company_service import branding_for
from app.services.gmail_service import GmailService

logger = logging.getLogger(__name__)

# Cambiar a ["PENDING"] para notificar solo alertas nuevas sin abrir.
# Dejar ["PENDING", "IN_PROGRESS"] para notificar cualquier alerta activa.
REMINDER_STATUSES = ["PENDING"]


def _last_action_subquery(db: Session):
    """Subconsulta: fecha del último follow-up por alerta."""
    return (
        db.query(
            AlertFollowUp.alert_id,
            func.max(AlertFollowUp.created_at).label("last_followup_at"),
        )
        .group_by(AlertFollowUp.alert_id)
        .subquery()
    )


def get_pending_buyers_by_agent(
    db: Session,
    hours_threshold: int
) -> dict[tuple[int, int], list[dict]]:
    """
    Devuelve un dict {(agent_id, company_id): [lista de compradores pendientes]}.
    Un comprador aparece si tiene al menos una alerta activa cuya
    última gestión supera `hours_threshold` horas. La empresa es la de la
    propiedad de la alerta.
    """
    cutoff = datetime.utcnow() - timedelta(hours=hours_threshold)

    last_followup = _last_action_subquery(db)

    alerts = (
        db.query(PropertyAlert)
        # Seguimientos y propiedad en lote (antes, 2 consultas por alerta);
        # el Inicio llama a esta función en cada carga.
        .options(selectinload(PropertyAlert.follow_ups), joinedload(PropertyAlert.property))
        .outerjoin(last_followup, last_followup.c.alert_id == PropertyAlert.id)
        .filter(PropertyAlert.status.in_(REMINDER_STATUSES))
        .filter(
            func.coalesce(last_followup.c.last_followup_at, PropertyAlert.created_at)
            < cutoff
        )
        .all()
    )

    result: dict[tuple[int, int], list[dict]] = {}

    for alert in alerts:
        last_action = max(
            (fu.created_at for fu in alert.follow_ups),
            default=alert.created_at,
        )
        entry = {
            "alert_id": alert.id,
            "buyer_name": alert.lead_name,
            "buyer_phone": alert.lead_phone or "—",
            "alert_status": alert.status,
            "last_action_at": last_action,
            "hours_elapsed": int((datetime.utcnow() - last_action).total_seconds() // 3600),
        }

        company_id = alert.property.company_id if alert.property else None
        result.setdefault((alert.agent_id, company_id), []).append(entry)

    return result


def _build_email_body(
    agent_name: str,
    buyers: list[dict],
    hours_threshold: int,
    system_name: str = "sistema MOYZA",
) -> str:
    rows = ""
    for b in sorted(buyers, key=lambda x: x["last_action_at"]):
        rows += f"""
        <tr>
            <td style="padding:8px 12px;border-bottom:1px solid #eee;">{b['buyer_name']}</td>
            <td style="padding:8px 12px;border-bottom:1px solid #eee;">{b['buyer_phone']}</td>
            <td style="padding:8px 12px;border-bottom:1px solid #eee;">{b['alert_status']}</td>
            <td style="padding:8px 12px;border-bottom:1px solid #eee;color:#c0392b;font-weight:bold;">
                {b['hours_elapsed']} horas
            </td>
        </tr>"""

    return f"""
    <html><body style="font-family:Arial,sans-serif;color:#333;max-width:680px;margin:auto;">
      <h2 style="color:#0E567B;">Recordatorio: compradores sin gestión</h2>
      <p>Hola <strong>{agent_name}</strong>,</p>
      <p>Los siguientes compradores llevan más de <strong>{hours_threshold} horas</strong>
         sin recibir gestión:</p>
      <table style="width:100%;border-collapse:collapse;margin-top:16px;">
        <thead>
          <tr style="background:#0E567B;color:#fff;">
            <th style="padding:10px 12px;text-align:left;">Comprador</th>
            <th style="padding:10px 12px;text-align:left;">Teléfono</th>
            <th style="padding:10px 12px;text-align:left;">Estado</th>
            <th style="padding:10px 12px;text-align:left;">Sin gestión</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
      <p style="margin-top:24px;font-size:13px;color:#888;">
        Este es un recordatorio automático del {system_name}.
      </p>
    </body></html>
    """


def run_buyer_reminders(
    db: Session,
    gmail_service: GmailService,
    hours_threshold: int,
    sender_name: Optional[str] = None,
):
    """
    Punto de entrada principal llamado desde el scheduler.
    Consulta compradores pendientes y envía un email por agente y empresa.
    Registra una fila en alert_reminder_logs por cada comprador/alerta procesada.

    `sender_name` se mantiene por compatibilidad; el remitente visible lo
    define cada empresa (`companies.email_sender_name`).
    """
    logger.info(
        f"Iniciando recordatorio de compradores (umbral: {hours_threshold}h, "
        f"estados: {REMINDER_STATUSES})"
    )

    pending_by_group = get_pending_buyers_by_agent(db, hours_threshold)

    if not pending_by_group:
        logger.info("No hay compradores pendientes de atención. No se envían recordatorios.")
        return

    agent_ids = {agent_id for agent_id, _ in pending_by_group.keys()}
    agents_by_id = {
        a.id: a for a in db.query(Agent).filter(Agent.id.in_(agent_ids)).all()
    }

    company_ids = {cid for _, cid in pending_by_group.keys() if cid is not None}
    companies_by_id = {
        c.id: c for c in db.query(Company).filter(Company.id.in_(company_ids)).all()
    } if company_ids else {}

    sent, skipped = 0, 0
    executed_at = datetime.utcnow()

    for (agent_id, company_id), buyers in pending_by_group.items():
        agent = agents_by_id.get(agent_id)
        brand = branding_for(companies_by_id.get(company_id))

        if not agent:
            logger.warning(f"Agente {agent_id} no encontrado, omitiendo.")
            for b in buyers:
                db.add(AlertReminderLog(
                    executed_at=executed_at,
                    agent_id=None,
                    agent_name=f"[Desconocido id={agent_id}]",
                    agent_email="",
                    alert_id=b["alert_id"],
                    buyer_name=b["buyer_name"],
                    status="SKIPPED",
                    skip_reason="agente_no_encontrado",
                ))
            skipped += len(buyers)
            continue

        if not agent.email:
            logger.warning(
                f"Agente {agent.name} (id={agent_id}) no tiene email configurado, omitiendo."
            )
            for b in buyers:
                db.add(AlertReminderLog(
                    executed_at=executed_at,
                    agent_id=agent.id,
                    agent_name=agent.name,
                    agent_email="",
                    alert_id=b["alert_id"],
                    buyer_name=b["buyer_name"],
                    status="SKIPPED",
                    skip_reason="sin_email",
                ))
            skipped += len(buyers)
            continue

        subject = f"[{brand.name}] {len(buyers)} comprador(es) pendiente(s) de atención"
        body = _build_email_body(agent.name, buyers, hours_threshold, brand.system_name)
        success = gmail_service.send_email(agent.email, subject, body)

        for b in buyers:
            db.add(AlertReminderLog(
                executed_at=executed_at,
                agent_id=agent.id,
                agent_name=agent.name,
                agent_email=agent.email,
                alert_id=b["alert_id"],
                buyer_name=b["buyer_name"],
                status="SENT" if success else "ERROR",
                error_message=None if success else "Fallo al enviar via Gmail API",
            ))

        if success:
            sent += 1
        else:
            skipped += 1

    db.commit()
    logger.info(
        f"Recordatorios completados: {sent} correos enviados (agente × empresa), {skipped} omitidos."
    )
