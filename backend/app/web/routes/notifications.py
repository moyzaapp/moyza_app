"""Notificaciones in-app: página /notifications y API de la campana.

PLAN_DASHBOARD_INICIO.md §4.4. Todo sobre el usuario y la empresa activa.

- Las rutas /api/notifications/* no pasan por AuthMiddleware: resuelven
  usuario y empresa desde las cookies (`get_api_user` +
  `resolve_company_for_api`), como /api/alerts/unread-count. Sin sesión
  responden 401.
- Mismo prefijo /api que el resto de endpoints de la interfaz (no /api/v1):
  la campana sigue el patrón del badge de compradores.
"""
from fastapi import APIRouter
from fastapi import Depends
from fastapi import Form
from fastapi import Query
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.responses import JSONResponse
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.db.deps import get_db
from app.services import notification_service as notifications
from app.web.dependencies.company import get_active_company
from app.web.dependencies.company import get_api_user
from app.web.dependencies.company import resolve_company_for_api
from app.web.template_env import templates
from app.web.utils.flash import set_flash

router = APIRouter()

PER_PAGE = 25
FILTERS = ("all", "unread", "read")


def _api_context(request: Request, db: Session):
    user = get_api_user(request, db)
    if user is None:
        return None, None
    return user, resolve_company_for_api(request, user, db)


def _unauthorized():
    return JSONResponse(status_code=401, content={"detail": "No autenticado"})


# ---------------------------------------------------------------------------
# API (campana)
# ---------------------------------------------------------------------------

@router.get("/api/notifications/unread-count")
async def api_unread_count(request: Request, db: Session = Depends(get_db)):
    user, company = _api_context(request, db)
    if user is None:
        return _unauthorized()
    if company is None:
        return {"unread_count": 0}
    return {"unread_count": notifications.unread_count(db, user.id, company.id)}


@router.get("/api/notifications/recent")
async def api_recent(request: Request, limit: int = Query(default=8, ge=1, le=50), db: Session = Depends(get_db)):
    user, company = _api_context(request, db)
    if user is None:
        return _unauthorized()
    if company is None:
        return {"items": [], "unread_count": 0}
    return {
        "items": [notifications.serialize(n) for n in notifications.recent(db, user.id, company.id, limit)],
        "unread_count": notifications.unread_count(db, user.id, company.id),
    }


@router.post("/api/notifications/mark-read")
async def api_mark_read(request: Request, db: Session = Depends(get_db)):
    """Cuerpo JSON: {"ids": [1, 2]} o {"all": true}."""
    user, company = _api_context(request, db)
    if user is None:
        return _unauthorized()
    if company is None:
        return {"marked": 0, "unread_count": 0}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    marked = notifications.mark_read(
        db, user.id, company.id,
        ids=payload.get("ids") or [],
        all_=bool(payload.get("all")),
    )
    return {"marked": marked, "unread_count": notifications.unread_count(db, user.id, company.id)}


# ---------------------------------------------------------------------------
# Página
# ---------------------------------------------------------------------------

@router.get("/notifications", response_class=HTMLResponse)
async def notifications_page(
    request: Request,
    status: str = Query(default="all"),
    page: int = Query(default=1, ge=1),
    db: Session = Depends(get_db),
):
    user = request.state.user
    company = get_active_company(request)
    if status not in FILTERS:
        status = "all"

    items, total = notifications.page(db, user.id, company.id, status, page, PER_PAGE)
    pages = max((total + PER_PAGE - 1) // PER_PAGE, 1)

    return templates.TemplateResponse(
        request=request,
        name="notifications/list.html",
        context={
            "request": request,
            "current_user": user,
            "items": [notifications.serialize(n) for n in items],
            "status": status,
            "page": page,
            "pages": pages,
            "total": total,
            "per_page": PER_PAGE,
            "unread_total": notifications.unread_count(db, user.id, company.id),
        },
    )


@router.get("/notifications/{notification_id}/open")
async def open_notification(notification_id: int, request: Request, db: Session = Depends(get_db)):
    """Marca la notificación como leída y lleva a su destino."""
    user = request.state.user
    company = get_active_company(request)
    notification = notifications.get_for_user(db, notification_id, user.id, company.id)
    if notification is None:
        response = RedirectResponse(url="/notifications", status_code=302)
        set_flash(response, "error", "Notificación no encontrada")
        return response
    notifications.mark_read(db, user.id, company.id, ids=[notification.id])
    return RedirectResponse(url=notifications.safe_redirect_url(notification.url), status_code=302)


@router.post("/notifications/mark-all-read")
async def mark_all_read(request: Request, next_url: str = Form("/notifications", alias="next"),
                        db: Session = Depends(get_db)):
    user = request.state.user
    company = get_active_company(request)
    marked = notifications.mark_read(db, user.id, company.id, all_=True)
    response = RedirectResponse(url=notifications.safe_redirect_url(next_url), status_code=302)
    if marked:
        set_flash(response, "success", f"{marked} {'notificación marcada' if marked == 1 else 'notificaciones marcadas'} como leída{'s' if marked != 1 else ''}")
    return response
