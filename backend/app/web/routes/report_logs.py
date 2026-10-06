from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse, JSONResponse
from app.web.template_env import templates
from sqlalchemy.orm import Session
from typing import Optional

from app.db.deps import get_db
from app.models.alert_reminder_log import AlertReminderLog
from app.models.report_job_log import ReportJobLog
from app.models.visit_whatsapp_log import VisitWhatsappLog
from app.models.property import Property
from app.models.report import Report
from app.services.report_job_service import ReportJobService
from app.services.company_scope import scope_properties, scope_agents
from app.models.agent import Agent
from app.web.dependencies.company import get_active_company
from app.web.dependencies.company import get_api_user
from app.web.dependencies.company import resolve_company_for_api

router = APIRouter()


def _scope_report_logs(query, company_id: int):
    return query.filter(ReportJobLog.property.has(Property.company_id == company_id))


def _scope_reminder_logs(query, company_id: int):
    agent_ids = scope_agents(query.session.query(Agent.id), company_id).subquery()
    return query.filter(AlertReminderLog.agent_id.in_(agent_ids))


def _scope_visit_whatsapp_logs(query, company_id: int):
    return query.filter(VisitWhatsappLog.property.has(Property.company_id == company_id))


def _api_company(request: Request, db: Session):
    """Empresa activa para los endpoints /api (sin AuthMiddleware). None si no hay sesión."""
    user = get_api_user(request, db)
    if not user:
        return None
    return resolve_company_for_api(request, user, db)



@router.get("/report-logs", response_class=HTMLResponse)
async def report_logs_page(
    request: Request,
    tab: Optional[str] = Query("reports"),
    status: Optional[str] = Query(None),
    property_id: Optional[int] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    reminder_status: Optional[str] = Query(None),
    visit_whatsapp_status: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    company = get_active_company(request)

    query = _scope_report_logs(db.query(ReportJobLog), company.id)
    if status:
        query = query.filter(ReportJobLog.status == status)
    if property_id:
        query = query.filter(ReportJobLog.property_id == property_id)
    logs = query.order_by(ReportJobLog.job_run_at.desc()).limit(limit).all()

    reminder_query = _scope_reminder_logs(db.query(AlertReminderLog), company.id)
    if reminder_status:
        reminder_query = reminder_query.filter(AlertReminderLog.status == reminder_status)
    reminder_logs = reminder_query.order_by(AlertReminderLog.executed_at.desc()).limit(limit).all()

    visit_whatsapp_query = _scope_visit_whatsapp_logs(db.query(VisitWhatsappLog), company.id)
    if visit_whatsapp_status:
        visit_whatsapp_query = visit_whatsapp_query.filter(VisitWhatsappLog.status == visit_whatsapp_status)
    visit_whatsapp_logs = visit_whatsapp_query.order_by(VisitWhatsappLog.attempted_at.desc()).limit(limit).all()

    properties = scope_properties(
        db.query(Property).filter(Property.auto_send_report == True),
        company.id
    ).all()

    return templates.TemplateResponse(
        request=request,
        name="report_logs/home.html",
        context={
            "request": request,
            "logs": logs,
            "reminder_logs": reminder_logs,
            "visit_whatsapp_logs": visit_whatsapp_logs,
            "properties": properties,
            "current_user": request.state.user,
            "selected_status": status,
            "selected_property_id": property_id,
            "selected_reminder_status": reminder_status,
            "selected_visit_whatsapp_status": visit_whatsapp_status,
            "active_tab": tab,
        }
    )


@router.get("/api/report-logs", response_class=JSONResponse)
async def get_report_logs_api(
    request: Request,
    status: Optional[str] = Query(None),
    property_id: Optional[int] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db)
):
    """
    API endpoint para obtener logs de reportes en formato JSON (empresa activa).
    """
    company = _api_company(request, db)
    if company is None:
        return JSONResponse(status_code=401, content={"logs": [], "total": 0})

    query = _scope_report_logs(db.query(ReportJobLog), company.id)

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


@router.get("/api/reminder-logs")
async def get_reminder_logs_api(
    request: Request,
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db)
):
    company = _api_company(request, db)
    if company is None:
        return JSONResponse(status_code=401, content={"logs": [], "total": 0})

    query = _scope_reminder_logs(db.query(AlertReminderLog), company.id)
    if status:
        query = query.filter(AlertReminderLog.status == status)
    logs = query.order_by(AlertReminderLog.executed_at.desc()).limit(limit).all()
    return {
        "logs": [
            {
                "id": log.id,
                "executed_at": log.executed_at.isoformat() if log.executed_at else None,
                "agent_id": log.agent_id,
                "agent_name": log.agent_name,
                "agent_email": log.agent_email,
                "buyers_count": log.buyers_count,
                "status": log.status,
                "skip_reason": log.skip_reason,
                "error_message": log.error_message,
            }
            for log in logs
        ],
        "total": len(logs),
    }


@router.get("/api/report-logs/stats")
async def get_report_stats(request: Request, db: Session = Depends(get_db)):
    """
    Endpoint para obtener estadísticas de los reportes de la empresa activa.
    """
    company = _api_company(request, db)
    if company is None:
        return JSONResponse(status_code=401, content={"error": "No autenticado"})

    base = _scope_report_logs(db.query(ReportJobLog), company.id)

    total_logs = base.count()
    success_count = base.filter(ReportJobLog.status == "success").count()
    failed_count = base.filter(ReportJobLog.status == "failed").count()
    pending_count = base.filter(ReportJobLog.status == "pending").count()
    skipped_count = base.filter(ReportJobLog.status == "skipped").count()

    return {
        "total": total_logs,
        "success": success_count,
        "failed": failed_count,
        "pending": pending_count,
        "skipped": skipped_count,
        "success_rate": round((success_count / total_logs * 100), 2) if total_logs > 0 else 0
    }
