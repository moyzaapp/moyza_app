"""Inicio (/dashboard) para todos los roles. PLAN_DASHBOARD_INICIO.md.

El contenido depende del rol y siempre es de la empresa activa:

- Agente: sus KPIs contra objetivo, novedades (notificaciones in-app),
  agenda, cartera, tendencia y observaciones del admin, más el aviso de
  compradores sin atender.
- Admin: KPIs del equipo, cumplimiento por agente, "Requiere atención",
  actividad reciente y tendencia de 12 semanas, más el aviso de compradores
  sin atender agrupado por agente.
- Usuario sin ficha de agente en la empresa activa: vista mínima con aviso.
"""
from fastapi import APIRouter
from fastapi import Depends
from fastapi import Query
from fastapi import Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.constants import DashboardThresholds
from app.core.constants import PeriodType
from app.db.deps import get_db
from app.services import notification_service as notifications
from app.services.company_scope import in_company
from app.services.dashboard_service import DashboardService
from app.services.dashboard_service import long_date_es
from app.services.dashboard_service import madrid_now
from app.web.dependencies.auth import get_agent_from_user
from app.web.dependencies.auth import is_admin
from app.web.dependencies.company import get_active_company
from app.web.template_env import templates

router = APIRouter()


def _first_name(user) -> str:
    name = (getattr(user, "full_name", "") or "").strip()
    return name.split()[0] if name else ""


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    period_type: str = Query(default=PeriodType.DEFAULT),
    period_start: str = Query(default=""),
    db: Session = Depends(get_db),
):
    current_user = request.state.user
    company = get_active_company(request)
    svc = DashboardService(db, company.id)
    period = svc.period(period_type, period_start)
    admin = bool(is_admin(current_user))

    context = {
        "request": request,
        "current_user": current_user,
        "is_admin": admin,
        "period": period,
        "period_labels": PeriodType.labels(),
        "today_label": long_date_es(madrid_now().date()),
        "first_name": _first_name(current_user),
        "agent": None,
        "home": None,
        "buyer_reminder_hours": settings.BUYER_REMINDER_HOURS,
    }

    if admin:
        context.update({"view": "admin", "home": svc.admin_home(period)})
    else:
        agent = get_agent_from_user(current_user, db)
        # La ficha de agente tiene que pertenecer a la empresa activa
        if agent is not None and in_company(agent, company.id):
            home = svc.agent_home(agent, period)
            # Novedades: notificaciones in-app del usuario en la empresa activa
            home.update({
                "show_news": True,
                "news": [
                    notifications.serialize(n)
                    for n in notifications.recent(db, current_user.id, company.id, DashboardThresholds.NEWS_LIMIT)
                ],
                "news_unread": notifications.unread_count(db, current_user.id, company.id),
            })
            context.update({"view": "agent", "agent": agent, "home": home})
        else:
            context["view"] = "no_agent"

    return templates.TemplateResponse(
        request=request,
        name="dashboard/home.html",
        context=context,
    )
