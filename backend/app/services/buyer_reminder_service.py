"""
Servicio de recordatorio de compradores que requieren atención.

Usa `buyer_attention_service` (PLAN_ALERTAS_DIAS_HABILES.md, ajustado por
PLAN_RECORDATORIO_SIN_RESPUESTA.md): R3 "volver a llamar" tras un «Sin
respuesta» y R1 "sin gestión", en horas hábiles de Jaén. Envía un único
email diario por agente con las dos secciones, solo en días hábiles, y en la
misma pasada crea los avisos in-app. Una pasada horaria solo in-app
(`run_buyer_callback_notifications`) avisa de R3 en cuanto vence.

Multiempresa: los recordatorios se agrupan por agente Y empresa. Un agente
que trabaja en MOYZA y en MOES PREMIUM recibe un correo por cada empresa,
cada uno con la marca correspondiente.
"""
import logging
from datetime import datetime
from html import escape
from typing import Optional

from sqlalchemy.orm import Session

from app.core import business_calendar as bc
from app.core.config import settings
from app.core.phone import phone_display
from app.models.agent import Agent
from app.models.alert_reminder_log import AlertReminderLog
from app.models.company import Company
from app.services.alert_view import OPEN_ALERT_STATUSES
from app.services.buyer_attention_service import RULE_CALLBACK
from app.services.buyer_attention_service import RULE_NO_ACTION
from app.services.buyer_attention_service import find_buyers_needing_attention
from app.services.buyer_attention_service import group_by_agent_and_company
from app.services.company_service import branding_for
from app.services.gmail_service import GmailService

logger = logging.getLogger(__name__)

# Alertas vigiladas: las abiertas. Abrir una alerta (pasa a IN_PROGRESS) ya no
# silencia los avisos (PLAN_ALERTAS_DIAS_HABILES.md, decisión 4).
REMINDER_STATUSES = list(OPEN_ALERT_STATUSES)


def get_pending_buyers_by_agent(
    db: Session,
    hours_threshold: int,
    now: Optional[datetime] = None,
    company_id: Optional[int] = None,
    agent_id: Optional[int] = None,
) -> dict[tuple[int, int], list[dict]]:
    """
    Devuelve un dict {(agent_id, company_id): [compradores que requieren atención]}.

    Envoltorio de `buyer_attention_service.find_buyers_needing_attention`
    (horas hábiles, reglas R3 "volver a llamar" y R1 "sin gestión", una fila
    por alerta). `hours_threshold` es el umbral de R1 en horas hábiles. Cada
    fila conserva la forma de siempre (`alert_id`, `buyer_name`,
    `buyer_phone`, `alert_status`, `last_action_at`, `hours_elapsed`, en horas
    hábiles) y añade `rule`, `due_at`, `attempts`, `is_last_attempt`, `text`…
    """
    items = find_buyers_needing_attention(
        db, company_id=company_id, agent_id=agent_id, now=now, no_action_hours=hours_threshold,
    )
    return {
        key: [item.as_dict() for item in group]
        for key, group in group_by_agent_and_company(items).items()
    }


_CELL = "padding:8px 12px;border-bottom:1px solid #eee;"
_HEAD = "padding:10px 12px;text-align:left;"


def _phone(value) -> str:
    """Teléfono legible (+34 600 111 222) o '—'."""
    if not value or value == "—":
        return "—"
    return phone_display(value) or value


def _section(title: str, intro: str, columns: list, buyers: list[dict]) -> str:
    """Tabla de una sección del email (vacía si no hay compradores).

    `columns`: [(cabecera, valor(b), resaltar)] además de Comprador y Teléfono.
    """
    if not buyers:
        return ""
    headers = "".join(f'<th style="{_HEAD}">{escape(header)}</th>' for header, _, _ in columns)
    rows = "".join(
        f"""
        <tr>
            <td style="{_CELL}">{escape(b['buyer_name'] or 'Comprador sin nombre')}</td>
            <td style="{_CELL}">{escape(_phone(b['buyer_phone']))}</td>"""
        + "".join(
            f'<td style="{_CELL}{"color:#c0392b;font-weight:bold;" if strong else ""}">{escape(value(b))}</td>'
            for _, value, strong in columns
        )
        + "</tr>"
        for b in buyers
    )
    return f"""
      <h3 style="color:#0E567B;margin:24px 0 4px;">{title} ({len(buyers)})</h3>
      <p style="margin:0 0 8px;">{intro}</p>
      <table style="width:100%;border-collapse:collapse;">
        <thead>
          <tr style="background:#0E567B;color:#fff;">
            <th style="{_HEAD}">Comprador</th>
            <th style="{_HEAD}">Teléfono</th>{headers}
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>"""


def _attempt_cell(b: dict) -> str:
    """'Intento 2 de 3' o 'Intento 3 de 3 · cierra la alerta (Sin interés)'."""
    text = f"Intento {b['attempts']} de {b['max_attempts']}"
    return text + " · cierra la alerta (Sin interés)" if b["is_last_attempt"] else text


def _build_email_body(
    agent_name: str,
    buyers: list[dict],
    hours_threshold: int,
    system_name: str = "sistema MOYZA",
) -> str:
    """Email diario con dos secciones: "Pendientes de volver a llamar" (R3) y "Sin gestión" (R1).

    Horas hábiles (lunes a viernes sin festivos de Jaén). Cada comprador sale
    una sola vez, en la sección de su regla.
    """
    by_age = sorted(buyers, key=lambda b: -b["business_hours_elapsed"])
    callback = [b for b in by_age if b["rule"] == RULE_CALLBACK]
    no_action = [b for b in by_age if b["rule"] == RULE_NO_ACTION]

    sections = _section(
        "Pendientes de volver a llamar",
        f"No contestaron y ya han pasado <strong>{settings.BUYER_CALLBACK_HOURS} horas hábiles</strong>. "
        "Vuelve a llamar y registra el seguimiento; al tercer intento sin respuesta, cierra la alerta "
        "como «Sin interés».",
        [
            ("Intento", _attempt_cell, True),
            ("Sin respuesta desde", lambda b: b["since_label"], False),
        ],
        callback,
    ) + _section(
        "Sin gestión",
        f"Llevan más de <strong>{hours_threshold} horas hábiles</strong> sin ninguna gestión registrada. "
        "Registra un seguimiento (también «Sin respuesta» si no contestan).",
        [
            ("Sin gestión (horas hábiles)", lambda b: b["elapsed_label"], True),
            ("Venció el", lambda b: b["due_label"], False),
        ],
        no_action,
    )

    return f"""
    <html><body style="font-family:Arial,sans-serif;color:#333;max-width:680px;margin:auto;">
      <h2 style="color:#0E567B;">Recordatorio: compradores que requieren atención</h2>
      <p>Hola <strong>{escape(agent_name or '')}</strong>,</p>
      <p>Estos compradores necesitan que los gestiones. Las horas cuentan solo en días hábiles
         (lunes a viernes, sin festivos de Jaén).</p>
      {sections}
      <p style="margin-top:24px;font-size:13px;color:#888;">
        Este es un recordatorio automático del {escape(system_name)}.
      </p>
    </body></html>
    """


def run_buyer_callback_notifications(db: Session, now: Optional[datetime] = None) -> dict:
    """Pasada horaria, solo in-app: avisa de R3 «volver a llamar» en cuanto vence.

    El email y R1 siguen en el job diario (`run_buyer_reminders`); aquí solo se
    crea la notificación del intento vencido (una por intento, deduplicada en
    `notification_service.run_buyer_attention`), sin email ni WhatsApp. Así un
    «Sin respuesta» del viernes a las 17:00 avisa el lunes a las 17:00 y no el
    martes a las 08:00.
    """
    from app.services import notification_service

    now = now or datetime.utcnow()
    items = [item for item in find_buyers_needing_attention(db, now=now) if item.rule == RULE_CALLBACK]
    created = notification_service.run_buyer_attention(db, items, now=now)
    if created:
        logger.info(f"Avisos «volver a llamar»: {created} creados.")
    return {"callbacks": len(items), "notifications": created}


def run_buyer_reminders(
    db: Session,
    gmail_service: GmailService,
    hours_threshold: int,
    sender_name: Optional[str] = None,
    now: Optional[datetime] = None,
    notify_in_app: bool = True,
) -> dict:
    """
    Punto de entrada del job diario (08:00 Madrid, solo días hábiles).

    - En un día no hábil (sábado, domingo o festivo de Jaén) no hace nada.
    - Una sola consulta de compradores que requieren atención (R3 y R1): con
      ella se envía un email por agente y empresa (dos secciones) y, en la
      misma pasada, los avisos in-app con su cadencia y la limpieza de los que
      ya no aplican. El admin no recibe email (decisión 9).
    - Registra una fila en alert_reminder_logs por cada comprador/alerta procesada.

    `now` (UTC naive) se inyecta en los tests y en las pruebas con fecha
    simulada. `sender_name` se mantiene por compatibilidad; el remitente
    visible lo define cada empresa (`companies.email_sender_name`).

    Devuelve un resumen: {"business_day", "emails": [{to, subject, callback,
    no_action, sent}], "skipped", "notifications", "resolved"}.
    """
    from app.services import notification_service

    now = now or datetime.utcnow()
    today = bc.madrid_today(now)
    summary = {"business_day": bc.is_business_day(today), "date": today, "emails": [],
               "skipped": 0, "notifications": 0, "resolved": 0}

    if not summary["business_day"]:
        logger.info(f"Recordatorio de compradores: {today} no es día hábil en Jaén; no se envía nada.")
        return summary

    logger.info(
        f"Iniciando recordatorio de compradores (R1 {hours_threshold} h hábiles, "
        f"R3 {settings.BUYER_CALLBACK_HOURS} h hábiles, estados: {REMINDER_STATUSES})"
    )

    items = find_buyers_needing_attention(db, now=now, no_action_hours=hours_threshold)
    pending_by_group = {
        key: [item.as_dict() for item in group]
        for key, group in group_by_agent_and_company(items).items()
    }

    if not pending_by_group:
        logger.info("No hay compradores pendientes de atención. No se envían recordatorios.")

    agent_ids = {agent_id for agent_id, _ in pending_by_group.keys()}
    agents_by_id = {
        a.id: a for a in db.query(Agent).filter(Agent.id.in_(agent_ids)).all()
    } if agent_ids else {}

    company_ids = {cid for _, cid in pending_by_group.keys() if cid is not None}
    companies_by_id = {
        c.id: c for c in db.query(Company).filter(Company.id.in_(company_ids)).all()
    } if company_ids else {}

    sent, skipped = 0, 0
    executed_at = now

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

        subject = f"[{brand.name}] {len(buyers)} comprador(es) requieren atención"
        body = _build_email_body(agent.name, buyers, hours_threshold, brand.system_name)
        success = gmail_service.send_email(agent.email, subject, body)
        summary["emails"].append({
            "to": agent.email,
            "agent": agent.name,
            "company": brand.name,
            "subject": subject,
            "callback": [b["buyer_name"] for b in buyers if b["rule"] == RULE_CALLBACK],
            "no_action": [b["buyer_name"] for b in buyers if b["rule"] == RULE_NO_ACTION],
            "sent": success,
        })

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
    summary["skipped"] = skipped
    logger.info(
        f"Recordatorios completados: {sent} correos enviados (agente × empresa), {skipped} omitidos."
    )

    if notify_in_app:
        # Misma pasada: los avisos in-app usan la lista ya calculada
        summary["notifications"] = notification_service.run_buyer_attention(db, items, now=now)
        summary["resolved"] = notification_service.resolve_buyer_notifications(db, items=items, now=now)
        logger.info(
            f"Avisos in-app de compradores: {summary['notifications']} creados, "
            f"{summary['resolved']} marcados leídos por no aplicar ya."
        )
    return summary
