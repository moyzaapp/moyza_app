import logging
from datetime import datetime
import os
import json
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler

from app.core.constants import PropertyStatus
from app.db.session import SessionLocal
from app.models.property import Property
from app.services.report_job_service import ReportJobService

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
                Property.status == PropertyStatus.ACTIVE
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
