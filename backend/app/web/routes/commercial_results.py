"""Resultados Comerciales (solo admin). PLAN_RESULTADOS_COMERCIALES.md.

Una sección con tres pestañas, todas sobre la empresa activa:

- rendimiento: objetivos y resultados por agente (semana / mes / año).
- evolucion: gráficas del año (barras por agente y evolución mensual).
- compradores: estado de las alertas y desempeño por agente (antes la
  pestaña "General" de /alerts-dashboard).

Sustituye a /alerts-dashboard y /performance-reports, que redirigen aquí.
"""
import logging
from datetime import datetime, timedelta
from urllib.parse import urlencode

from fastapi import APIRouter
from fastapi import Request
from fastapi import Depends
from fastapi import Form
from fastapi import Query

from fastapi.responses import HTMLResponse
from fastapi.responses import RedirectResponse

from sqlalchemy.orm import Session

from app.core.constants import AlertStatus
from app.core.constants import PerformanceObjectives
from app.core.constants import PeriodType
from app.db.deps import get_db
from app.models.agent import Agent
from app.models.property_alert import PropertyAlert
from app.services.company_scope import get_agent_in_company
from app.services.company_scope import scope_agents
from app.services.company_scope import scope_alerts
from app.services.notification_service import notify_admin_note
from app.services.performance_report_service import PerformanceReportService
from app.web.dependencies.auth import is_admin
from app.web.dependencies.company import get_active_company
from app.web.template_env import templates
from app.web.utils.flash import set_flash

router = APIRouter()
logger = logging.getLogger(__name__)

BASE_URL = "/commercial-results"

TAB_PERFORMANCE = "rendimiento"
TAB_EVOLUTION = "evolucion"
TAB_BUYERS = "compradores"
TABS = (TAB_PERFORMANCE, TAB_EVOLUTION, TAB_BUYERS)

# Pestañas de /alerts-dashboard -> pestañas nuevas
LEGACY_DASHBOARD_TABS = {
    "general": TAB_BUYERS,
    "rendimiento": TAB_PERFORMANCE,
}


def _results_url(**params) -> str:
    query = urlencode({k: v for k, v in params.items() if v not in (None, "")})
    return f"{BASE_URL}?{query}" if query else BASE_URL


def _performance_url(period_type: str, period_start: str, agent_id: int = None) -> str:
    url = _results_url(
        tab=TAB_PERFORMANCE,
        period_type=period_type,
        period_start=period_start,
        open=agent_id,
    )
    return f"{url}#agent-{agent_id}" if agent_id else url


def _forbidden_redirect(message: str = "Solo administradores pueden acceder a Resultados Comerciales"):
    response = RedirectResponse(url="/alerts", status_code=302)
    set_flash(response, "error", message)
    return response


def _company_agents(db: Session, company_id: int):
    return scope_agents(db.query(Agent), company_id).order_by(Agent.name.asc()).all()


# ---------------------------------------------------------------------------
# Pestaña Compradores (estado de las alertas de la empresa activa)
# ---------------------------------------------------------------------------

def _hours(delta) -> float:
    return delta.total_seconds() / 3600


def buyers_context(db: Session, company_id: int) -> dict:
    all_alerts = scope_alerts(db.query(PropertyAlert), company_id).all()

    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    abandoned_alerts = [
        a for a in all_alerts
        if a.status == AlertStatus.PENDING and a.created_at and a.created_at < seven_days_ago
    ]

    response_times = [
        _hours(a.read_at - a.created_at) for a in all_alerts if a.read_at and a.created_at
    ]
    avg_response_time = sum(response_times) / len(response_times) if response_times else 0

    agents_data = []
    for agent in scope_agents(db.query(Agent), company_id).all():
        agent_alerts = [a for a in all_alerts if a.agent_id == agent.id]
        if not agent_alerts:
            continue
        agent_times = [
            _hours(a.read_at - a.created_at) for a in agent_alerts if a.read_at and a.created_at
        ]
        latest = max(agent_alerts, key=lambda a: a.created_at or datetime.min)
        agents_data.append({
            "agent": agent,
            "total_alerts": len(agent_alerts),
            "pending": sum(1 for a in agent_alerts if a.status == AlertStatus.PENDING),
            "in_progress": sum(1 for a in agent_alerts if a.status == AlertStatus.IN_PROGRESS),
            "completed": sum(1 for a in agent_alerts if a.status == AlertStatus.COMPLETED),
            "avg_response_time": round(sum(agent_times) / len(agent_times), 1) if agent_times else 0,
            "last_activity": latest.created_at,
        })

    agents_data.sort(key=lambda x: x["pending"], reverse=True)

    return {
        "total_alerts": len(all_alerts),
        "pending_alerts": sum(1 for a in all_alerts if a.status == AlertStatus.PENDING),
        "in_progress_alerts": sum(1 for a in all_alerts if a.status == AlertStatus.IN_PROGRESS),
        "completed_alerts": sum(1 for a in all_alerts if a.status == AlertStatus.COMPLETED),
        "abandoned_alerts": abandoned_alerts,
        "avg_response_time": round(avg_response_time, 1),
        "agents_data": agents_data,
    }


# ---------------------------------------------------------------------------
# Página
# ---------------------------------------------------------------------------

@router.get(BASE_URL, response_class=HTMLResponse)
async def commercial_results(
    request: Request,
    tab: str = Query(default=TAB_PERFORMANCE),
    period_type: str = Query(default=PeriodType.DEFAULT),
    period_start: str = Query(default=""),
    year: str = Query(default=""),
    open_agent: str = Query(default="", alias="open"),
    db: Session = Depends(get_db),
):
    current_user = request.state.user

    if not is_admin(current_user):
        return _forbidden_redirect()

    if tab not in TABS:
        tab = TAB_PERFORMANCE

    company = get_active_company(request)
    svc = PerformanceReportService(db, company.id)

    context = {
        "request": request,
        "current_user": current_user,
        "tab": tab,
        "period_labels": PeriodType.labels(),
        "metric_labels": PerformanceObjectives.LABELS,
        "target_fields": PerformanceObjectives.TARGET_FIELDS,
    }

    if tab == TAB_PERFORMANCE:
        period = svc.period(period_type, period_start)
        agents = _company_agents(db, company.id)
        context.update({
            "period": period,
            "objective_keys": svc.objective_keys(period.period_type),
            "agents_data": svc.agents_period_data(agents, period),
            # Tras guardar objetivos o notas se reabre el panel de ese agente
            "open_agent_id": int(open_agent) if open_agent.isdigit() else None,
        })

    elif tab == TAB_EVOLUTION:
        # Año elegido (por defecto el en curso); la navegación reutiliza el período anual
        year_period = svc.period(PeriodType.YEARLY, f"{year}-01-01" if year.isdigit() else "")
        if year_period.start > year_period.current_start:
            year_period = svc.period(PeriodType.YEARLY, "")
        agents = _company_agents(db, company.id)
        context.update({
            "year_period": year_period,
            "evolution": svc.yearly_evolution(year_period.start.year, agents),
        })

    elif tab == TAB_BUYERS:
        context.update(buyers_context(db, company.id))

    return templates.TemplateResponse(
        request=request,
        name="commercial_results/home.html",
        context=context,
    )


# ---------------------------------------------------------------------------
# Objetivos y observaciones por agente
# ---------------------------------------------------------------------------

class _TargetValueError(ValueError):
    pass


def _parse_target(raw):
    """Entero >= 0, None si viene vacío. Lanza _TargetValueError si no es válido."""
    if raw is None or not str(raw).strip():
        return None
    try:
        value = int(str(raw).strip())
    except ValueError:
        raise _TargetValueError()
    if value < 0:
        raise _TargetValueError()
    return value


@router.post(BASE_URL + "/{agent_id}/targets")
async def save_targets(
    agent_id: int,
    request: Request,
    period_type: str = Form(...),
    period_start_str: str = Form(""),
    db: Session = Depends(get_db),
):
    current_user = request.state.user

    if not is_admin(current_user):
        return _forbidden_redirect("Acceso no autorizado")

    if not PeriodType.is_valid(period_type):
        response = RedirectResponse(url=_results_url(tab=TAB_PERFORMANCE), status_code=302)
        set_flash(response, "error", "Tipo de período no válido")
        return response

    company_id = get_active_company(request).id
    svc = PerformanceReportService(db, company_id)
    period = svc.period(period_type, period_start_str)
    back_url = _performance_url(period.period_type, period.start_str, agent_id)

    if not get_agent_in_company(db, agent_id, company_id):
        response = RedirectResponse(url=_performance_url(period.period_type, period.start_str), status_code=302)
        set_flash(response, "error", "Agente no encontrado en la empresa activa")
        return response

    # Solo se pueden definir objetivos en períodos activos (no cerrados)
    report = svc.get_report(agent_id, period.period_type, period.start)
    if report and report.is_locked:
        response = RedirectResponse(url=back_url, status_code=302)
        set_flash(response, "error", "No se pueden modificar objetivos en períodos ya cerrados")
        return response

    # Solo se leen los campos con objetivo en este tipo de período
    form = await request.form()
    values = {}
    try:
        for field in svc.allowed_target_fields(period.period_type):
            values[field] = _parse_target(form.get(field))
    except _TargetValueError:
        response = RedirectResponse(url=back_url, status_code=302)
        set_flash(response, "error", "Los objetivos deben ser números enteros iguales o mayores que 0")
        return response

    try:
        svc.save_target(
            agent_id=agent_id,
            period_type=period.period_type,
            period_start=period.start,
            created_by=current_user.id,
            **values,
        )
    except Exception:
        db.rollback()
        logger.exception("Error guardando objetivos: agent_id=%s", agent_id)
        response = RedirectResponse(url=back_url, status_code=302)
        set_flash(response, "error", "Error al guardar los objetivos")
        return response

    response = RedirectResponse(url=back_url, status_code=302)
    set_flash(response, "success", "Objetivos guardados correctamente")
    return response


@router.post(BASE_URL + "/{agent_id}/notes")
async def save_notes(
    agent_id: int,
    request: Request,
    period_type: str = Form(...),
    period_start_str: str = Form(""),
    admin_notes: str = Form(None),
    db: Session = Depends(get_db),
):
    current_user = request.state.user

    if not is_admin(current_user):
        return _forbidden_redirect("Acceso no autorizado")

    if not PeriodType.is_valid(period_type):
        response = RedirectResponse(url=_results_url(tab=TAB_PERFORMANCE), status_code=302)
        set_flash(response, "error", "Tipo de período no válido")
        return response

    company_id = get_active_company(request).id
    svc = PerformanceReportService(db, company_id)
    period = svc.period(period_type, period_start_str)
    back_url = _performance_url(period.period_type, period.start_str, agent_id)

    agent = get_agent_in_company(db, agent_id, company_id)
    if not agent:
        response = RedirectResponse(url=_performance_url(period.period_type, period.start_str), status_code=302)
        set_flash(response, "error", "Agente no encontrado en la empresa activa")
        return response

    notes = (admin_notes or "").strip()
    try:
        report = svc.save_notes(
            agent_id=agent_id,
            period_type=period.period_type,
            period_start=period.start,
            period_end=period.end,
            admin_notes=notes,
        )
    except Exception:
        db.rollback()
        logger.exception("Error guardando notas: agent_id=%s", agent_id)
        response = RedirectResponse(url=back_url, status_code=302)
        set_flash(response, "error", "Error al guardar las observaciones")
        return response

    # Aviso in-app al agente (solo si hay texto; no al propio admin)
    if notes:
        notify_admin_note(db, agent=agent, company_id=company_id, period=period, report=report, actor=current_user)

    response = RedirectResponse(url=back_url, status_code=302)
    set_flash(response, "success", "Observaciones guardadas")
    return response


# ---------------------------------------------------------------------------
# Rutas antiguas: redirección permanente conservando los query params
# ---------------------------------------------------------------------------

@router.get("/alerts-dashboard")
async def legacy_alerts_dashboard(request: Request):
    params = dict(request.query_params)
    # Sin pestaña, /alerts-dashboard mostraba la pestaña General (Compradores)
    params["tab"] = LEGACY_DASHBOARD_TABS.get(params.get("tab", "general"), TAB_PERFORMANCE)
    return RedirectResponse(url=_results_url(**params), status_code=301)


@router.get("/performance-reports")
async def legacy_performance_reports(request: Request):
    params = dict(request.query_params)
    params["tab"] = TAB_PERFORMANCE
    return RedirectResponse(url=_results_url(**params), status_code=301)
