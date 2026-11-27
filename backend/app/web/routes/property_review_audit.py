"""Seguimiento de propiedades nuevas y compradores compatibles (solo admin, solo lectura).

GET /properties/seguimiento-nuevas          listado con filtros (días, estado, empresa)
GET /properties/seguimiento-nuevas/{id}     detalle: revisión, avisos y todas las alertas evaluadas

Pantalla de diagnóstico (`property_review_audit_service`): no escribe nada. El
router se incluye ANTES que el de propiedades para que
`/properties/{property_id}` no capture la ruta.
"""
from datetime import datetime

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Query
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy.orm import joinedload

from app.core.constants import PropertyReviewStatus as S
from app.db.deps import get_db
from app.models.property import Property
from app.services import property_review_audit_service as audit
from app.web.dependencies.auth import deny_if_not_admin
from app.web.dependencies.company import get_active_company
from app.web.dependencies.company import get_allowed_companies_from_request
from app.web.dependencies.company import get_company_ids
from app.web.template_env import templates
from app.web.utils.flash import set_flash

router = APIRouter()

BASE_URL = "/properties/seguimiento-nuevas"
DAYS_OPTIONS = (7, 15, 30, 60, 90, 180)
STATUS_OPTIONS = (
    ("todas", "Todos los estados"),
    (S.OK, "Revisadas (OK)"),
    (S.PENDING, "Por revisar"),
    (S.ISSUES, "Con observaciones"),
    (S.FIXED, "Corregidas · pendientes de OK"),
    (S.SKIPPED, "Sin revisión (históricas)"),
)


def _company_scope(request: Request, empresa: str):
    """Ids de empresa del filtro: la activa (por defecto) o todas las del admin."""
    if empresa == "todas":
        return [c.id for c in get_allowed_companies_from_request(request)]
    return get_company_ids(request)


@router.get(BASE_URL, response_class=HTMLResponse)
async def review_audit_list(
    request: Request,
    dias: int = Query(default=30),
    estado: str = Query(default="todas"),
    empresa: str = Query(default="activa"),
    q: str = Query(default=""),
    db: Session = Depends(get_db),
):
    denied = deny_if_not_admin(request, "/properties")
    if denied is not None:
        return denied
    dias = dias if dias in DAYS_OPTIONS else 30
    estado = estado if estado in {key for key, _ in STATUS_OPTIONS} else "todas"
    empresa = "todas" if empresa == "todas" else "activa"

    q = (q or "").strip()[:120]
    data = audit.audit_rows(db, _company_scope(request, empresa), days=dias, status=estado, search=q)
    return templates.TemplateResponse(
        request=request,
        name="properties/review_audit.html",
        context={
            "request": request,
            "current_user": request.state.user,
            "is_admin": True,
            "rows": data["rows"],
            "summary": data["summary"],
            "now": data["now"],
            "dias": dias,
            "estado": estado,
            "empresa": empresa,
            "q": q,
            "days_options": [(d, f"Últimos {d} días") for d in DAYS_OPTIONS],
            "status_options": STATUS_OPTIONS,
            "active_company": get_active_company(request),
            "can_choose_company": len(get_allowed_companies_from_request(request)) > 1,
            "base_url": BASE_URL,
        },
    )


@router.get(BASE_URL + "/{property_id}", response_class=HTMLResponse)
async def review_audit_detail(property_id: int, request: Request, db: Session = Depends(get_db)):
    denied = deny_if_not_admin(request, "/properties")
    if denied is not None:
        return denied
    allowed = [c.id for c in get_allowed_companies_from_request(request)]
    prop = (
        db.query(Property)
        .options(joinedload(Property.agent), joinedload(Property.company))
        .filter(Property.id == property_id)
        .first()
    )
    if prop is None or prop.company_id not in allowed:
        response = RedirectResponse(url=BASE_URL, status_code=302)
        set_flash(response, "error", "Propiedad no encontrada")
        return response

    data = audit.audit_detail(db, prop, now=datetime.utcnow())
    return templates.TemplateResponse(
        request=request,
        name="properties/review_audit_detail.html",
        context={
            "request": request,
            "current_user": request.state.user,
            "is_admin": True,
            "base_url": BASE_URL,
            **data,
        },
    )
