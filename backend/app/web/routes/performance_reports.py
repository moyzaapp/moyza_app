import logging
from datetime import datetime, timedelta

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
    """Devuelve (period_start, period_end) como datetime a partir de los query params."""
    svc = PerformanceReportService.__new__(PerformanceReportService)

    if period_type == "MONTHLY":
        if period_start_str:
            try:
                period_start = datetime.strptime(period_start_str, "%Y-%m-%d")
                period_start = datetime(period_start.year, period_start.month, 1)
            except ValueError:
                period_start = svc.current_month_start()
        else:
            period_start = svc.current_month_start()
        _, period_end = svc.month_bounds(period_start)
    else:
        if period_start_str:
            try:
                period_start = datetime.strptime(period_start_str, "%Y-%m-%d")
                # Normalizar al lunes de esa semana
                period_start = period_start - timedelta(days=period_start.weekday())
                period_start = datetime(period_start.year, period_start.month, period_start.day)
            except ValueError:
                period_start = svc.current_week_start()
        else:
            period_start = svc.current_week_start()
        _, period_end = svc.week_bounds(period_start)

    return period_start, period_end


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

    if period_type not in ("WEEKLY", "MONTHLY"):
        period_type = "WEEKLY"

    ps, pe = _parse_period(period_type, period_start)
    svc = PerformanceReportService(db)
    is_current = svc.is_current_period(period_type, ps)

    # Navegación de períodos
    if period_type == "WEEKLY":
        prev_start = ps - timedelta(days=7)
        next_start = ps + timedelta(days=7)
        current_start = svc.current_week_start()
    else:
        import calendar as _cal
        # Mes anterior
        if ps.month == 1:
            prev_start = datetime(ps.year - 1, 12, 1)
        else:
            prev_start = datetime(ps.year, ps.month - 1, 1)
        # Mes siguiente
        if ps.month == 12:
            next_start = datetime(ps.year + 1, 1, 1)
        else:
            next_start = datetime(ps.year, ps.month + 1, 1)
        current_start = svc.current_month_start()

    # No mostrar botón "siguiente" si el período siguiente es futuro
    show_next = next_start <= current_start

    # Solo agentes de la empresa activa
    agents = (
        scope_agents(db.query(Agent), get_active_company(request).id)
        .order_by(Agent.name.asc())
        .all()
    )

    agents_data = []
    for agent in agents:
        # Período actual: calcular en vivo. Período pasado: leer snapshot.
        report = svc.get_report(agent.id, period_type, ps)

        if is_current or report is None or not report.is_locked:
            metrics = svc.calculate_metrics(agent.id, ps, pe)
        else:
            metrics = {
                "contactos_venta": report.contactos_venta,
                "contactos_alquiler": report.contactos_alquiler,
                "bajadas": report.bajadas,
                "captaciones_crm": report.captaciones_crm,
                "cierres": report.cierres,
                "hojas_visita": report.hojas_visita,
                "calidad_cartera": report.calidad_cartera,
            }

        target = svc.get_target(agent.id, period_type, ps)

        agents_data.append({
            "agent": agent,
            "metrics": metrics,
            "target": target,
            "report": report,
            "admin_notes": report.admin_notes if report else "",
            "is_locked": report.is_locked if report else False,
        })

    return templates.TemplateResponse(
        request=request,
        name="alerts/performance_report.html",
        context={
            "request": request,
            "current_user": current_user,
            "period_type": period_type,
            "period_start": ps,
            "period_end": pe,
            "is_current": is_current,
            "prev_start": prev_start,
            "next_start": next_start,
            "show_next": show_next,
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

    svc = PerformanceReportService(db)

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
    svc = PerformanceReportService(db)

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
