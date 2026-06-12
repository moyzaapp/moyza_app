import logging
import os
import json
from datetime import datetime, timedelta
from typing import Optional, Dict
from uuid import uuid4
from sqlalchemy.orm import Session

from app.core.constants import ReportType
from app.core.config import settings
from app.models.property import Property
from app.models.report import Report
from app.models.report_job_log import ReportJobLog
from app.services.property_metrics import PropertyMetricsService
from app.services.report_generator import generate_property_report
from app.services.whatsapp import send_report, WhatsAppServiceError
from app.services.ai_valuation import AIValuationService

logger = logging.getLogger(__name__)


class ReportJobService:
    """
    Servicio para orquestar la generación y envío automático de reportes.
    Maneja validación, generación, almacenamiento, envío y logging.
    """

    def __init__(self, db: Session):
        self.db = db

    def execute(self, property_item: Property) -> bool:
        """
        Ejecuta el flujo completo de generación y envío de reporte para una propiedad.

        Args:
            property_item: Propiedad para la cual generar el reporte

        Returns:
            True si el proceso fue exitoso, False en caso contrario
        """
        start_time = datetime.utcnow()
        log_entry = None

        try:
            log_entry = self._create_log(property_item.id)

            if self._report_exists_today(property_item.id):
                self._update_log(
                    log_entry,
                    status="skipped",
                    stage="validation",
                    metadata={"reason": "Report already exists for today"}
                )
                logger.info(f"Reporte ya existe para propiedad {property_item.id} hoy")
                return False

            self._update_log(log_entry, stage="validation", status="pending")

            report_data = self._collect_report_data(property_item)

            # Generar análisis con IA
            self._update_log(log_entry, stage="ai_analysis", status="pending")
            ai_analysis = self._generate_ai_analysis(property_item, report_data)
            if ai_analysis:
                report_data["ai_valuation"] = ai_analysis.get("valuation")
                report_data["ai_observations"] = ai_analysis.get("observations")
                logger.info(f"Análisis de IA generado para propiedad {property_item.id}")
            else:
                logger.warning(f"No se pudo generar análisis de IA para propiedad {property_item.id}")

            self._update_log(log_entry, stage="generation", status="pending")

            file_path = self._generate_pdf(property_item, report_data)
            self._update_log(log_entry, stage="storage", status="pending")

            report = self._save_report(property_item, file_path)
            log_entry.report_id = report.id
            self.db.commit()

            self._update_log(log_entry, stage="whatsapp", status="pending")

            self._send_whatsapp_notification(property_item, report)

            duration = (datetime.utcnow() - start_time).total_seconds()
            self._update_log(
                log_entry,
                status="success",
                stage="completed",
                duration_seconds=duration
            )

            logger.info(
                f"Reporte generado y enviado exitosamente para propiedad {property_item.id} "
                f"en {duration:.2f} segundos"
            )
            return True

        except Exception as e:
            duration = (datetime.utcnow() - start_time).total_seconds()
            error_message = str(e)

            self.db.rollback()

            if log_entry:
                try:
                    self._update_log(
                        log_entry,
                        status="failed",
                        error_message=error_message,
                        duration_seconds=duration
                    )
                except Exception:
                    self.db.rollback()
                    logger.exception(
                        "Error actualizando log fallido para propiedad %s",
                        property_item.id
                    )

            logger.error(
                f"Error procesando reporte para propiedad {property_item.id}: {error_message}",
                exc_info=True
            )
            return False

    def _create_log(self, property_id: int) -> ReportJobLog:
        """Crea una entrada de log inicial."""
        log_entry = ReportJobLog(
            property_id=property_id,
            job_run_at=datetime.utcnow(),
            status="pending",
            stage="initialization"
        )
        self.db.add(log_entry)
        self.db.commit()
        self.db.refresh(log_entry)
        return log_entry

    def _update_log(
        self,
        log_entry: ReportJobLog,
        status: Optional[str] = None,
        stage: Optional[str] = None,
        error_message: Optional[str] = None,
        duration_seconds: Optional[float] = None,
        metadata: Optional[Dict] = None
    ):
        """Actualiza una entrada de log existente."""
        if status:
            log_entry.status = status
        if stage:
            log_entry.stage = stage
        if error_message:
            log_entry.error_message = error_message
        if duration_seconds is not None:
            log_entry.duration_seconds = duration_seconds
        if metadata:
            log_entry.metadatas = json.dumps(metadata)

        log_entry.updated_at = datetime.utcnow()
        self.db.commit()

    def _report_exists_today(self, property_id: int) -> bool:
        """
        Verifica si ya existe un reporte generado hoy para esta propiedad.

        Args:
            property_id: ID de la propiedad

        Returns:
            True si existe un reporte del día, False en caso contrario
        """
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)

        existing_report = (
            self.db.query(Report)
            .filter(
                Report.property_id == property_id,
                Report.created_at >= today_start,
                Report.created_at < today_end
            )
            .first()
        )

        return existing_report is not None

    def _collect_report_data(self, property_item: Property) -> Dict:
        """
        Recolecta los datos necesarios para generar el reporte.

        Args:
            property_item: Propiedad de la cual recolectar datos

        Returns:
            Diccionario con los datos del reporte
        """
        return PropertyMetricsService(self.db).report_data(property_item)

    def _generate_ai_analysis(self, property_item: Property, metrics_data: Dict) -> Optional[Dict]:
        """
        Genera análisis con IA (valuación + observaciones).

        Args:
            property_item: Propiedad a analizar
            metrics_data: Métricas calculadas de la propiedad

        Returns:
            Diccionario con análisis de IA o None si no está disponible
        """
        try:
            ai_service = AIValuationService(self.db)
            ai_analysis = ai_service.generate_analysis(property_item, metrics_data)
            if ai_analysis:
                ai_service.update_property_fair_price(
                    property_item,
                    ai_analysis.get("valuation")
                )

            return ai_analysis
        except Exception as e:
            logger.error(f"Error generando análisis de IA para propiedad {property_item.id}: {e}")
            return None

    def _generate_pdf(self, property_item: Property, report_data: Dict) -> str:
        """
        Genera el PDF del reporte.

        Args:
            property_item: Propiedad para el reporte
            report_data: Datos del reporte

        Returns:
            Ruta del archivo generado
        """
        os.makedirs("storage/reports", exist_ok=True)

        unique_filename = f"{uuid4()}.pdf"
        file_path = f"storage/reports/{unique_filename}"

        generate_property_report(
            property_item=property_item,
            report_data=report_data,
            output_path=file_path
        )

        logger.info(f"PDF generado en {file_path}")
        return file_path

    def _save_report(self, property_item: Property, file_path: str) -> Report:
        """
        Guarda el registro del reporte en la base de datos.

        Args:
            property_item: Propiedad asociada
            file_path: Ruta del archivo PDF

        Returns:
            Instancia del reporte guardado
        """
        report = Report(
            property_id=property_item.id,
            # uploaded_by=property_item.agent_id,
            report_type=ReportType.AUTOMATIC,
            filename=os.path.basename(file_path),
            filepath=file_path,
            notes="Reporte generado automáticamente por el sistema"
        )

        self.db.add(report)
        self.db.commit()
        self.db.refresh(report)

        logger.info(f"Reporte guardado con ID {report.id}")
        return report

    def _send_whatsapp_notification(self, property_item: Property, report: Report):
        """
        Envía el reporte por WhatsApp al cliente.

        Args:
            property_item: Propiedad asociada
            report: Reporte a enviar

        Raises:
            WhatsAppServiceError: Si hay un error al enviar el mensaje
        """
        if not property_item.client or not property_item.client.phone:
            logger.warning(
                f"Propiedad {property_item.id} no tiene cliente o teléfono asociado. "
                "Se omite el envío de WhatsApp."
            )
            return

        client_phone = property_item.client.phone
        file_url = settings.public_url(report.filepath)

        caption = (
            f"Hola! Te enviamos el reporte automático de tu propiedad: {property_item.title}\n"
            f"Fecha: {datetime.utcnow().strftime('%d/%m/%Y')}"
        )

        try:
            send_report(
                phone=client_phone,
                file_url=file_url,
                caption=caption
            )
            logger.info(f"WhatsApp enviado a {client_phone} para reporte {report.id}")

        except WhatsAppServiceError as e:
            logger.error(f"Error enviando WhatsApp a {client_phone}: {str(e)}")
            raise

    def retry_failed_job(self, log_id: int, max_retries: int = 3) -> bool:
        """
        Reintenta un job que falló previamente.

        Args:
            log_id: ID del log a reintentar
            max_retries: Número máximo de reintentos permitidos

        Returns:
            True si el reintento fue exitoso, False en caso contrario
        """
        log_entry = self.db.query(ReportJobLog).filter(ReportJobLog.id == log_id).first()

        if not log_entry:
            logger.error(f"Log con ID {log_id} no encontrado")
            return False

        if log_entry.retry_count >= max_retries:
            logger.warning(
                f"Log {log_id} alcanzó el máximo de reintentos ({max_retries})"
            )
            return False

        property_item = self.db.query(Property).filter(
            Property.id == log_entry.property_id
        ).first()

        if not property_item:
            logger.error(f"Propiedad {log_entry.property_id} no encontrada")
            return False

        log_entry.retry_count += 1
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            logger.exception("Error actualizando contador de reintentos: log_id=%s", log_id)
            return False

        logger.info(
            f"Reintentando job para propiedad {property_item.id} "
            f"(intento {log_entry.retry_count}/{max_retries})"
        )

        return self.execute(property_item)
