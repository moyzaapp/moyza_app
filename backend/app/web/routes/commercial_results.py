"""Resultados Comerciales (solo admin). PLAN_RESULTADOS_COMERCIALES.md.

Una sección con tres pestañas, todas sobre la empresa activa:

- rendimiento: objetivos y resultados por agente (semana / mes / año).
- evolucion: gráficas del año (barras por agente y evolución mensual).
- compradores: estado de las alertas y desempeño por agente (antes la
  pestaña "General" de /alerts-dashboard).

Sustituye a /alerts-dashboard y /performance-reports, que redirigen aquí.
"""
import csv
import io
import logging
import re
import unicodedata
from datetime import datetime, timedelta
from urllib.parse import urlencode

from fastapi import APIRouter
from fastapi import Request
from fastapi import Depends
from fastapi import Form
from fastapi import Query

from fastapi.responses import HTMLResponse
from fastapi.responses import RedirectResponse
from fastapi.responses import Response

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
from app.services.performance_report_service import INDICATOR_ROWS_PAGE
from app.services.performance_report_service import PerformanceReportService
from app.web.dependencies.auth import is_admin
from app.web.dependencies.company import get_active_company
from app.web.template_env import madrid_dt
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


def _assigned(alert):
    """Desde cuándo tiene la alerta su agente actual (PLAN_ASIGNACION_ALERTAS.md §2.5)."""
    return alert.assigned_at or alert.created_at


def buyers_context(db: Session, company_id: int) -> dict:
    all_alerts = scope_alerts(db.query(PropertyAlert), company_id).all()

    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    abandoned_alerts = [
        a for a in all_alerts
        # Desde la asignación: una alerta recién reasignada no está abandonada
        if a.status == AlertStatus.PENDING and _assigned(a) and _assigned(a) < seven_days_ago
    ]

    response_times = [
        _hours(a.read_at - _assigned(a)) for a in all_alerts if a.read_at and _assigned(a)
    ]
    avg_response_time = sum(response_times) / len(response_times) if response_times else 0

    agents_data = []
    for agent in scope_agents(db.query(Agent), company_id).all():
        agent_alerts = [a for a in all_alerts if a.agent_id == agent.id]
        if not agent_alerts:
            continue
        agent_times = [
            _hours(a.read_at - _assigned(a)) for a in agent_alerts if a.read_at and _assigned(a)
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
        # Lupa de trazabilidad en cada tarjeta (PLAN_TRAZABILIDAD_INDICADORES.md): solo admin
        "can_trace": is_admin(current_user),
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
# Detalle de un indicador: de dónde sale el número (solo admin)
# PLAN_TRAZABILIDAD_INDICADORES.md
# ---------------------------------------------------------------------------

KIND_LABELS = {"venta": "Venta", "alquiler": "Alquiler", "otros": "Otros"}

VISIT_STATUS_LABELS = {
    "draft": "Borrador",
    "preview": "Vista previa",
    "signed": "Firmada",
    "completed": "Completada",
}

ALERT_STATUS_LABELS = {
    AlertStatus.PENDING: "Pendiente",
    AlertStatus.IN_PROGRESS: "En proceso",
    AlertStatus.COMPLETED: "Completada",
    AlertStatus.CANCELLED: "Cancelada",
}


def _csv_date(value) -> str:
    return madrid_dt(value) if value else ""


def _csv_price(value) -> str:
    return "" if value is None else f"{float(value):.0f}"


def _csv_property(row) -> str:
    if row["property_id"] is None:
        return "Búsqueda general"
    return " · ".join(p for p in (row["property_ref"], row["property_title"]) if p)


# Columnas del CSV por indicador: (cabecera, valor de la fila). La tabla del
# panel pinta los mismos datos (commercial_results/_metric_detail.html).
METRIC_CSV_COLUMNS = {
    "contactos": (
        ("Fecha", lambda r: _csv_date(r["date"])),
        ("Comprador", lambda r: r["buyer_name"]),
        ("Propiedad", _csv_property),
        ("Ciudad", lambda r: r["property_city"] or ""),
        ("Tipo", lambda r: KIND_LABELS[r["kind"]]),
        ("Origen", lambda r: r["source"] or ""),
        ("Estado", lambda r: ALERT_STATUS_LABELS.get(r["status"], r["status"] or "")),
        ("Alerta", lambda r: f"/alerts/{r['alert_id']}"),
    ),
    "captaciones_crm": (
        ("Fecha de entrada", lambda r: _csv_date(r["date"])),
        ("Propiedad", _csv_property),
        ("Ciudad", lambda r: r["property_city"] or ""),
        ("Tipo", lambda r: KIND_LABELS[r["kind"]]),
        ("Precio", lambda r: _csv_price(r["price"])),
        ("Estado", lambda r: r["status"] or ""),
        ("Enlace", lambda r: f"/properties/{r['property_id']}"),
    ),
    "bajadas": (
        ("Fecha", lambda r: _csv_date(r["date"])),
        ("Propiedad", _csv_property),
        ("Ciudad", lambda r: r["property_city"] or ""),
        ("Tipo", lambda r: KIND_LABELS[r["kind"]]),
        ("Precio anterior", lambda r: _csv_price(r["old_price"])),
        ("Precio nuevo", lambda r: _csv_price(r["new_price"])),
        ("Motivo", lambda r: r["reason"] or ""),
        ("Enlace", lambda r: f"/properties/{r['property_id']}"),
    ),
    "cierres": (
        ("Fecha", lambda r: _csv_date(r["date"])),
        ("Comprador", lambda r: r["buyer_name"]),
        ("Propiedad", _csv_property),
        ("Tipo", lambda r: KIND_LABELS[r["kind"]]),
        ("Nota del cierre", lambda r: r["notes"] or ""),
        ("Alerta", lambda r: f"/alerts/{r['alert_id']}"),
    ),
    "hojas_visita": (
        ("Fecha", lambda r: _csv_date(r["date"])),
        ("Visitante", lambda r: r["visitor_name"]),
        ("Propiedad", _csv_property),
        ("Ciudad", lambda r: r["property_city"] or ""),
        ("Participación", lambda r: r["role"].capitalize()),
        ("Estado", lambda r: VISIT_STATUS_LABELS.get(r["status"], r["status"] or "")),
        ("Ficha", lambda r: f"/visits/{r['visit_id']}/download" if r["has_pdf"] else ""),
    ),
}


def _slug(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-") or "agente"


def _metric_url(agent_id: int, key: str, period, **extra) -> str:
    params = {"period_type": period.period_type, "period_start": period.start_str, **extra}
    return f"{BASE_URL}/{agent_id}/metric/{key}?{urlencode(params)}"


def _metric_csv(key: str, rows: list, filename: str) -> Response:
    buffer = io.StringIO()
    # Punto y coma y BOM: Excel en español lo abre en columnas y con tildes
    writer = csv.writer(buffer, delimiter=";")
    columns = METRIC_CSV_COLUMNS[key]
    writer.writerow([header for header, _ in columns])
    for row in rows:
        writer.writerow([value(row) for _, value in columns])
    return Response(
        content="﻿" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(BASE_URL + "/{agent_id}/metric/{key}")
async def metric_detail(
    agent_id: int,
    key: str,
    request: Request,
    period_type: str = Query(default=PeriodType.DEFAULT),
    period_start: str = Query(default=""),
    offset: int = Query(default=0, ge=0),
    output: str = Query(default="", alias="format"),
    db: Session = Depends(get_db),
):
    """Parcial HTML del panel lateral (o CSV con `?format=csv`) de un indicador.

    `?offset=N` devuelve solo la página siguiente de filas ("Ver más").
    """
    if not is_admin(request.state.user):
        return HTMLResponse("Solo administradores pueden ver el detalle de los indicadores.", status_code=403)

    company = get_active_company(request)
    svc = PerformanceReportService(db, company.id)
    agent = get_agent_in_company(db, agent_id, company.id)
    if agent is None or not svc.is_traceable(key):
        return HTMLResponse("Agente o indicador no encontrado en la empresa activa.", status_code=404)

    period = svc.period(period_type, period_start)

    if output == "csv":
        rows = svc.indicator_rows(key, agent.id, period.start, period.end, limit=None)
        filename = f"{key}_{_slug(agent.name)}_{company.code.lower()}_{period.period_type.lower()}_{period.start_str}.csv"
        return _metric_csv(key, rows, filename)

    live = svc.indicator_live_counts(key, agent.id, period.start, period.end)
    rows = svc.indicator_rows(key, agent.id, period.start, period.end, limit=INDICATOR_ROWS_PAGE, offset=offset)
    next_offset = offset + len(rows)
    has_more = next_offset < live["total"]

    context = {
        "request": request,
        "key": key,
        "label": PerformanceObjectives.LABELS[key],
        "agent": agent,
        "company": company,
        "period": period,
        "rows": rows,
        "live": live,
        "offset": offset,
        "rows_only": offset > 0,
        "has_more": has_more,
        "remaining": max(live["total"] - next_offset, 0),
        "more_url": _metric_url(agent.id, key, period, offset=next_offset) if has_more else None,
        "kind_labels": KIND_LABELS,
        "visit_status_labels": VISIT_STATUS_LABELS,
    }
    if offset == 0:
        context.update({
            "rule_text": svc.indicator_rule_text(key, agent, period.start, period.end, company),
            "frozen": svc.indicator_frozen(key, agent.id, period),
            "csv_url": _metric_url(agent.id, key, period, format="csv"),
        })

    return templates.TemplateResponse(
        request=request,
        name="commercial_results/_metric_detail.html",
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
