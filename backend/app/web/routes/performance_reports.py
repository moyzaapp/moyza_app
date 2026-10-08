import logging

from fastapi import APIRouter
from fastapi import Request
from fastapi import Depends
from fastapi import Form
from fastapi import Query

from fastapi.responses import HTMLResponse
from fastapi.responses import RedirectResponse

from sqlalchemy.orm import Session

from app.web.template_env import templates
from app.db.deps import get_db
from app.models.agent import Agent
from app.services.performance_report_service import PerformanceReportService
from app.web.utils.flash import set_flash
from app.web.dependencies.auth import is_admin, require_admin_role
from app.web.dependencies.company import get_active_company
from app.services.company_scope import scope_agents, get_agent_in_company

router = APIRouter()
logger = logging.getLogger(__name__)


def _parse_period(period_type: str, period_start_str: str):
    """Devuelve (period_start, period_end); la lógica vive en PerformanceReportService.period."""
    period = PerformanceReportService.period(period_type, period_start_str)
    return period.start, period.end


@router.get("/performance-reports", response_class=HTMLResponse)
async def performance_reports(
    request: Request,
    period_type: str = Query(default="WEEKLY"),
    period_start: str = Query(default=""),
    db: Session = Depends(get_db),
):
    current_user = request.state.user

    if not is_admin(current_user):
        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "error", "Solo administradores pueden acceder a los reportes")
        return response

    period = PerformanceReportService.period(period_type, period_start)
    company_id = get_active_company(request).id
    svc = PerformanceReportService(db, company_id)

    # Solo agentes de la empresa activa
    agents = (
        scope_agents(db.query(Agent), company_id)
        .order_by(Agent.name.asc())
        .all()
    )

    # Período actual: calcular en vivo. Período pasado: leer snapshot.
    agents_data = svc.agents_period_data(agents, period)

    return templates.TemplateResponse(
        request=request,
        name="alerts/performance_report.html",
        context={
            "request": request,
            "current_user": current_user,
            "period_type": period.period_type,
            "period_start": period.start,
            "period_end": period.end,
            "is_current": period.is_current,
            "prev_start": period.prev_start,
            "next_start": period.next_start,
            "show_next": period.show_next,
            "agents_data": agents_data,
        },
    )


@router.post("/performance-reports/{agent_id}/targets")
async def save_targets(
    agent_id: int,
    request: Request,
    period_type: str = Form(...),
    period_start_str: str = Form(...),
    target_contactos: str = Form(None),
    target_bajadas: str = Form(None),
    target_captaciones_crm: str = Form(None),
    target_cierres: str = Form(None),
    target_hojas_visita: str = Form(None),
    db: Session = Depends(get_db),
):
    current_user = request.state.user

    if not is_admin(current_user):
        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "error", "Acceso no autorizado")
        return response

    def to_int(v):
        try:
            return int(v) if v and str(v).strip() else None
        except (ValueError, TypeError):
            return None

    if not get_agent_in_company(db, agent_id, get_active_company(request).id):
        response = RedirectResponse(url="/alerts-dashboard?tab=rendimiento", status_code=302)
        set_flash(response, "error", "Agente no encontrado en la empresa activa")
        return response

    ps, _ = _parse_period(period_type, period_start_str)

    svc = PerformanceReportService(db, get_active_company(request).id)

    # Solo se pueden definir objetivos en períodos activos (no cerrados)
    report = svc.get_report(agent_id, period_type, ps)
    if report and report.is_locked:
        response = RedirectResponse(
            url=f"/alerts-dashboard?tab=rendimiento&period_type={period_type}&period_start={period_start_str}",
            status_code=302,
        )
        set_flash(response, "error", "No se pueden modificar objetivos en períodos ya cerrados")
        return response

    try:
        svc.save_target(
            agent_id=agent_id,
            period_type=period_type,
            period_start=ps,
            created_by=current_user.id,
            target_contactos=to_int(target_contactos),
            target_bajadas=to_int(target_bajadas),
            target_captaciones_crm=to_int(target_captaciones_crm),
            target_cierres=to_int(target_cierres),
            target_hojas_visita=to_int(target_hojas_visita),
        )
        response = RedirectResponse(
            url=f"/alerts-dashboard?tab=rendimiento&period_type={period_type}&period_start={period_start_str}",
            status_code=302,
        )
        set_flash(response, "success", "Objetivos guardados correctamente")
        return response

    except Exception:
        db.rollback()
        logger.exception("Error guardando objetivos: agent_id=%s", agent_id)
        response = RedirectResponse(
            url=f"/alerts-dashboard?tab=rendimiento&period_type={period_type}&period_start={period_start_str}",
            status_code=302,
        )
        set_flash(response, "error", "Error al guardar los objetivos")
        return response


@router.post("/performance-reports/{agent_id}/notes")
async def save_notes(
    agent_id: int,
    request: Request,
    period_type: str = Form(...),
    period_start_str: str = Form(...),
    admin_notes: str = Form(None),
    db: Session = Depends(get_db),
):
    current_user = request.state.user

    if not is_admin(current_user):
        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "error", "Acceso no autorizado")
        return response

    if not get_agent_in_company(db, agent_id, get_active_company(request).id):
        response = RedirectResponse(url="/alerts-dashboard?tab=rendimiento", status_code=302)
        set_flash(response, "error", "Agente no encontrado en la empresa activa")
        return response

    ps, pe = _parse_period(period_type, period_start_str)
    svc = PerformanceReportService(db, get_active_company(request).id)

    try:
        svc.save_notes(
            agent_id=agent_id,
            period_type=period_type,
            period_start=ps,
            period_end=pe,
            admin_notes=(admin_notes or "").strip(),
        )
        response = RedirectResponse(
            url=f"/alerts-dashboard?tab=rendimiento&period_type={period_type}&period_start={period_start_str}",
            status_code=302,
        )
        set_flash(response, "success", "Observaciones guardadas")
        return response

    except Exception:
        db.rollback()
        logger.exception("Error guardando notas: agent_id=%s", agent_id)
        response = RedirectResponse(
            url=f"/alerts-dashboard?tab=rendimiento&period_type={period_type}&period_start={period_start_str}",
            status_code=302,
        )
        set_flash(response, "error", "Error al guardar las observaciones")
        return response
