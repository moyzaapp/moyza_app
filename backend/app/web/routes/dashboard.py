"""Inicio (/dashboard) para todos los roles. PLAN_DASHBOARD_INICIO.md y
PLAN_INICIO_SEMANA_MES.md.

El contenido depende del rol y siempre es de la empresa activa. Muestra a la
vez la semana en curso y el mes en curso (sin selector de período: los
usuarios no lo pulsaban y creían que no tenían objetivos). El año y la
navegación histórica quedan en Resultados Comerciales.

- Agente: sus KPIs contra objetivo de la semana y del mes, novedades
  (notificaciones in-app), agenda, cartera, tendencia y observaciones del
  admin, más el aviso de compradores sin atender.
- Admin: KPIs del equipo de la semana y del mes, cumplimiento por agente con
  ambos períodos, "Requiere atención", actividad reciente y tendencia de 12
  semanas, más el aviso de compradores sin atender agrupado por agente.
- Usuario sin ficha de agente en la empresa activa: vista mínima con aviso.

Vista unificada del agente (PLAN_VISTA_UNIFICADA_AGENTES.md, fase C): el
Inicio del agente es de todas sus empresas (`get_company_ids`), con métricas
y objetivos sumados, agenda, compradores y novedades de todas, y distintivo
de empresa en las filas si tiene más de una. Para el admin y la vista por
empresa, `company_ids` es [activa] y todo sigue como siempre.

Los parámetros antiguos `period_type` y `period_start` se aceptan y se
ignoran, para que los enlaces guardados sigan funcionando.
"""
from fastapi import APIRouter
from fastapi import Depends
from fastapi import Query
from fastapi import Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.constants import DashboardThresholds
from app.db.deps import get_db
from app.services import notification_service as notifications
from app.services.company_scope import in_company
from app.services.dashboard_service import DashboardService
from app.services.dashboard_service import long_date_es
from app.services.dashboard_service import madrid_now
from app.web.dependencies.auth import get_agent_from_user
from app.web.dependencies.auth import is_admin
from app.web.dependencies.company import get_active_company
from app.web.dependencies.company import get_company_ids
from app.web.template_env import templates

router = APIRouter()


def _first_name(user) -> str:
    name = (getattr(user, "full_name", "") or "").strip()
    return name.split()[0] if name else ""


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    period_type: str = Query(default=""),   # heredado, se ignora
    period_start: str = Query(default=""),  # heredado, se ignora
    db: Session = Depends(get_db),
):
    current_user = request.state.user
    company = get_active_company(request)
    admin = bool(is_admin(current_user))
    # Admin: siempre la empresa activa. Agente: todas sus empresas (vista
    # unificada) o la activa (vista por empresa, `company_ids` == [activa])
    company_ids = [company.id] if admin else get_company_ids(request)
    svc = DashboardService(db, company_ids)
    week, month = svc.current_periods()

    context = {
        "request": request,
        "current_user": current_user,
        "is_admin": admin,
        "week": week,
        "month": month,
        "today_label": long_date_es(madrid_now().date()),
        "first_name": _first_name(current_user),
        "agent": None,
        "home": None,
        "buyer_reminder_hours": settings.BUYER_REMINDER_HOURS,
    }

    if admin:
        context.update({"view": "admin", "home": svc.admin_home(week=week, month=month)})
    else:
        agent = get_agent_from_user(current_user, db)
        # La ficha de agente tiene que pertenecer a alguna de sus empresas
        if agent is not None and in_company(agent, company_ids):
            home = svc.agent_home(agent, week=week, month=month)
            # Novedades: notificaciones in-app del usuario en sus empresas
            with_company = svc.is_multi
            home.update({
                "show_news": True,
                "news": [
                    notifications.serialize(n, with_company=with_company)
                    for n in notifications.recent(db, current_user.id, company_ids, DashboardThresholds.NEWS_LIMIT)
                ],
                "news_unread": notifications.unread_count(db, current_user.id, company_ids),
            })
            context.update({"view": "agent", "agent": agent, "home": home})
        else:
            context["view"] = "no_agent"

    return templates.TemplateResponse(
        request=request,
        name="dashboard/home.html",
        context=context,
    )
