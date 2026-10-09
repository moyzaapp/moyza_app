import logging
from datetime import datetime
import os
import json
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler

from app.core.config import settings
from app.core.constants import PeriodType
from app.core.constants import PropertyStatus
from app.db.session import SessionLocal
from app.models.property import Property
from app.services.report_job_service import ReportJobService
from app.services.performance_report_service import PerformanceReportService
from app.services.buyer_reminder_service import run_buyer_reminders
from app.services.gmail_service import GmailService

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()

# Archivo compartido para estado de workers
WORKER_STATE_FILE = Path("/tmp/moyza_workers_state.json")


def check_automatic_reports():
    """
    Revisa propiedades con auto_send_report activo y genera informes
    según la frecuencia configurada.
    """
    db = SessionLocal()

    try:
        now = datetime.now()
        current_day = now.day
        current_hour = now.hour

        logger.info(f"Ejecutando check_automatic_reports - Día: {current_day}, Hora: {current_hour}")

        properties = (
            db.query(Property)
            .filter(
                Property.auto_send_report == True,
                Property.status == PropertyStatus.ACTIVE,
                Property.available_clause()
            )
            .all()
        )

        logger.debug(f"Propiedades encontradas con auto_send_report: {len(properties)}")

        for property_item in properties:
            try:
                if (
                    property_item.report_frequency == "MONTHLY"
                    and property_item.report_day == current_day
                    and property_item.report_hour == current_hour
                ):
                    logger.info(
                        f"Generando informe automático para propiedad {property_item.id} "
                        f"({property_item.title})"
                    )

                    report_service = ReportJobService(db)
                    success = report_service.execute(property_item)

                    if success:
                        logger.info(
                            f"Informe generado exitosamente para propiedad {property_item.id}"
                        )
                    else:
                        logger.warning(
                            f"No se pudo generar informe para propiedad {property_item.id}"
                        )

            except Exception as e:
                logger.error(
                    f"Error procesando propiedad {property_item.id}: {str(e)}",
                    exc_info=True
                )
                continue

    except Exception as e:
        logger.error(f"Error en check_automatic_reports: {str(e)}", exc_info=True)
    finally:
        db.close()


def send_buyer_reminders():
    """Envía recordatorio por email a agentes con compradores sin gestión."""
    if not settings.BUYER_REMINDER_ENABLED:
        logger.info("Recordatorio de compradores deshabilitado (BUYER_REMINDER_ENABLED=false)")
        return

    db = SessionLocal()
    try:
        gmail = GmailService(
            credentials_path=settings.GMAIL_CREDENTIALS_PATH,
            token_path=settings.GMAIL_TOKEN_PATH,
        )
        run_buyer_reminders(
            db=db,
            gmail_service=gmail,
            hours_threshold=settings.BUYER_REMINDER_HOURS,
        )
    except Exception as e:
        logger.error(f"Error en send_buyer_reminders: {e}", exc_info=True)
    finally:
        db.close()


def _freeze_previous_period(period_type: str, now: datetime = None):
    """Congela, en todas las empresas, el período anterior al que contiene `now`.

    `now` (UTC) se inyecta en los tests; el scheduler usa la hora actual.
    Devuelve (period_start, period_end) congelados.
    """
    db = SessionLocal()
    try:
        # Sin empresa: freeze_all_for_period recorre empresas x agentes
        svc = PerformanceReportService(db)
        period_start = svc.previous_period_start(period_type, now)
        _, period_end = svc.period_bounds(period_type, period_start)
        logger.info(
            f"Congelando reportes {period_type}: {period_start.date()} – {period_end.date()}"
        )
        svc.freeze_all_for_period(period_type, period_start, period_end)
        logger.info(f"Reportes {period_type} congelados correctamente")
        return period_start, period_end
    except Exception as e:
        logger.error(f"Error congelando reportes {period_type}: {e}", exc_info=True)
    finally:
        db.close()


def freeze_weekly_reports(now: datetime = None):
    """Cada lunes a las 00:01 congela los reportes de la semana anterior."""
    return _freeze_previous_period(PeriodType.WEEKLY, now)


def freeze_monthly_reports(now: datetime = None):
    """El día 1 de cada mes a las 00:01 congela los reportes del mes anterior."""
    return _freeze_previous_period(PeriodType.MONTHLY, now)


def freeze_yearly_reports(now: datetime = None):
    """El 1 de enero a las 00:01 congela los reportes del año anterior."""
    return _freeze_previous_period(PeriodType.YEARLY, now)


def notify_follow_ups_due(now: datetime = None):
    """Cada día a las 08:00 (Madrid): aviso in-app de seguimientos de hoy o vencidos.

    Uno por alerta y día (deduplicación de 24 h). Solo in-app: sin email ni WhatsApp.
    """
    from app.services.notification_service import run_follow_up_due

    db = SessionLocal()
    try:
        created = run_follow_up_due(db, now=now)
        logger.info(f"Avisos de seguimiento creados: {created}")
        return created
    except Exception as e:
        logger.error(f"Error en notify_follow_ups_due: {e}", exc_info=True)
    finally:
        db.close()


def cleanup_read_notifications(now: datetime = None):
    """Cada día: borra las notificaciones leídas hace más de 90 días."""
    from app.services.notification_service import cleanup_read

    db = SessionLocal()
    try:
        deleted = cleanup_read(db, now=now)
        logger.info(f"Notificaciones leídas eliminadas (> 90 días): {deleted}")
        return deleted
    except Exception as e:
        logger.error(f"Error en cleanup_read_notifications: {e}", exc_info=True)
    finally:
        db.close()


def update_worker_heartbeat():
    """Actualiza el heartbeat de este worker en el archivo compartido."""
    worker_id = os.getenv("WORKER_ID", "unknown")

    try:
        import fcntl

        # Usar file locking para evitar race conditions
        with open(WORKER_STATE_FILE, 'a+') as f:
            # Obtener lock exclusivo con timeout
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                # Si no se puede obtener el lock, saltar esta actualización
                logger.debug(f"Worker {worker_id}: No se pudo obtener lock para heartbeat, saltando")
                return

            try:
                f.seek(0)
                content = f.read()
                workers_state = json.loads(content) if content else {}
            except (json.JSONDecodeError, ValueError):
                workers_state = {}

            # Actualizar este worker
            workers_state[worker_id] = {
                "worker_id": worker_id,
                "scheduler_running": scheduler.running if scheduler else False,
                "is_master": worker_id == "0",
                "last_heartbeat": datetime.now().isoformat(),
                "pid": os.getpid()
            }

            # Guardar estado actualizado
            f.seek(0)
            f.truncate()
            json.dump(workers_state, f)  # Sin indent para ser más rápido

    except Exception as e:
        logger.error(f"Error actualizando heartbeat del worker {worker_id}: {str(e)}")


def start_scheduler():
    """Inicia el scheduler con los jobs configurados."""

    # Solo iniciar en el worker maestro o proceso único
    # En Gunicorn multi-worker, solo un proceso debe ejecutar tareas programadas
    worker_id = os.getenv("WORKER_ID", "0")
    is_master = worker_id == "0"

    # Registrar existencia del worker (maestro o no)
    update_worker_heartbeat()

    if not is_master:
        logger.info(f"Worker {worker_id}: Scheduler deshabilitado (solo corre en worker maestro)")
        return

    logger.info("Worker maestro: Iniciando scheduler")

    # Ejecutar cada hora (los informes tienen precisión horaria)
    scheduler.add_job(
        check_automatic_reports,
        "cron",
        hour="*",
        minute=5,
        id="check_automatic_reports",
        replace_existing=True
    )

    # Congelar reportes semanales: cada lunes a las 00:01
    scheduler.add_job(
        freeze_weekly_reports,
        "cron",
        day_of_week="mon",
        hour=0,
        minute=1,
        id="freeze_weekly_reports",
        replace_existing=True
    )

    # Congelar reportes mensuales: día 1 de cada mes a las 00:01
    scheduler.add_job(
        freeze_monthly_reports,
        "cron",
        day=1,
        hour=0,
        minute=1,
        id="freeze_monthly_reports",
        replace_existing=True
    )

    # Congelar reportes anuales: 1 de enero a las 00:01
    scheduler.add_job(
        freeze_yearly_reports,
        "cron",
        month=1,
        day=1,
        hour=0,
        minute=1,
        id="freeze_yearly_reports",
        replace_existing=True
    )

    # Recordatorio de compradores sin gestión
    scheduler.add_job(
        send_buyer_reminders,
        "cron",
        hour=settings.BUYER_REMINDER_HOUR,
        # hour=3,
        minute=10,
        id="send_buyer_reminders",
        replace_existing=True
    )

    # Avisos in-app de seguimientos: 08:00 hora de Madrid
    scheduler.add_job(
        notify_follow_ups_due,
        "cron",
        hour=8,
        minute=0,
        timezone="Europe/Madrid",
        id="notify_follow_ups_due",
        replace_existing=True
    )

    # Limpieza de notificaciones leídas (retención 90 días)
    scheduler.add_job(
        cleanup_read_notifications,
        "cron",
        hour=3,
        minute=30,
        id="cleanup_read_notifications",
        replace_existing=True
    )

    # Heartbeat periódico (solo si está habilitado)
    heartbeat_enabled = os.getenv("WORKER_HEARTBEAT_ENABLED", "true").lower() == "true"
    if heartbeat_enabled:
        heartbeat_interval = int(os.getenv("WORKER_HEARTBEAT_INTERVAL", "60"))
        scheduler.add_job(
            update_worker_heartbeat,
            "interval",
            seconds=heartbeat_interval,
            id="worker_heartbeat",
            replace_existing=True
        )
        logger.info(f"Worker heartbeat habilitado (intervalo: {heartbeat_interval}s)")

    scheduler.start()
    logger.info("Scheduler iniciado correctamente en worker maestro")


def shutdown_scheduler():
    """Detiene el scheduler de manera limpia."""
    if scheduler.running:
        scheduler.shutdown(wait=True)
        logger.info("Scheduler detenido correctamente")
