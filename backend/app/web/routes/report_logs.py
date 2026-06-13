from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import Optional

from app.db.deps import get_db
from app.models.report_job_log import ReportJobLog
from app.models.property import Property
from app.models.report import Report
from app.services.report_job_service import ReportJobService

router = APIRouter()

templates = Jinja2Templates(directory="app/web/templates")


@router.get("/report-logs", response_class=HTMLResponse)
async def report_logs_page(
    request: Request,
    status: Optional[str] = Query(None),
    property_id: Optional[int] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db)
):
    """
    Página para visualizar logs de ejecución de reportes automáticos.
    """
    query = db.query(ReportJobLog)

    if status:
        query = query.filter(ReportJobLog.status == status)

    if property_id:
        query = query.filter(ReportJobLog.property_id == property_id)

    logs = query.order_by(ReportJobLog.job_run_at.desc()).limit(limit).all()

    properties = db.query(Property).filter(Property.auto_send_report == True).all()

    current_user = request.state.user

    return templates.TemplateResponse(
        request=request,
        name="report_logs/home.html",
        context={
            "request": request,
            "logs": logs,
            "properties": properties,
            "current_user": current_user,
            "selected_status": status,
            "selected_property_id": property_id
        }
    )


@router.get("/api/report-logs", response_class=JSONResponse)
async def get_report_logs_api(
    status: Optional[str] = Query(None),
    property_id: Optional[int] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db)
):
    """
    API endpoint para obtener logs de reportes en formato JSON.
    """
    query = db.query(ReportJobLog)

    if status:
        query = query.filter(ReportJobLog.status == status)

    if property_id:
        query = query.filter(ReportJobLog.property_id == property_id)

    logs = query.order_by(ReportJobLog.job_run_at.desc()).limit(limit).all()

    return {
        "logs": [
            {
                "id": log.id,
                "property_id": log.property_id,
                "property_title": log.property.title if log.property else None,
                "report_id": log.report_id,
                "job_run_at": log.job_run_at.isoformat() if log.job_run_at else None,
                "status": log.status,
                "stage": log.stage,
                "error_message": log.error_message,
                "retry_count": log.retry_count,
                "duration_seconds": float(log.duration_seconds) if log.duration_seconds else None,
                "metadata": log.metadatas,
                "created_at": log.created_at.isoformat() if log.created_at else None
            }
            for log in logs
        ],
        "total": len(logs)
    }


@router.post("/api/report-logs/{log_id}/retry")
async def retry_failed_report(
    log_id: int,
    db: Session = Depends(get_db)
):
    """
    Endpoint para reintentar un reporte que falló.
    """
    report_service = ReportJobService(db)
    success = report_service.retry_failed_job(log_id, max_retries=3)

    if success:
        return {"status": "success", "message": f"Reporte reintentado exitosamente"}
    else:
        return {"status": "error", "message": "No se pudo reintentar el reporte"}


@router.get("/api/report-logs/stats")
async def get_report_stats(db: Session = Depends(get_db)):
    """
    Endpoint para obtener estadísticas de los reportes.
    """
    total_logs = db.query(ReportJobLog).count()
    success_count = db.query(ReportJobLog).filter(ReportJobLog.status == "success").count()
    failed_count = db.query(ReportJobLog).filter(ReportJobLog.status == "failed").count()
    pending_count = db.query(ReportJobLog).filter(ReportJobLog.status == "pending").count()
    skipped_count = db.query(ReportJobLog).filter(ReportJobLog.status == "skipped").count()

    return {
        "total": total_logs,
        "success": success_count,
        "failed": failed_count,
        "pending": pending_count,
        "skipped": skipped_count,
        "success_rate": round((success_count / total_logs * 100), 2) if total_logs > 0 else 0
    }
