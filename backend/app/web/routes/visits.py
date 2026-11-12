import logging
import re
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from time import perf_counter
from uuid import uuid4

from fastapi import APIRouter
from fastapi import Request
from fastapi import Depends
from fastapi import Form
from fastapi.responses import HTMLResponse
from fastapi.responses import RedirectResponse
from fastapi.responses import FileResponse
from app.web.template_env import templates

from sqlalchemy import or_
from sqlalchemy.orm import Session
from sqlalchemy.orm import joinedload

from app.db.deps import get_db
from app.models.agent import Agent
from app.models.property import Property
from app.models.property_visit import PropertyVisit
from app.services.visit_sheet_generator import generate_visit_sheet
from app.services.whatsapp import send_report
from app.core.business_calendar import fmt_madrid
from app.core.config import settings
from app.web.utils.flash import set_flash
from app.web.dependencies.auth import is_admin, get_agent_from_user
from app.core.numbers import parse_es_decimal
from app.core.phone import PhoneValidationError, canonical_phone, phone_from_form, split_phone
from app.services.visit_whatsapp_log_service import log_whatsapp_attempt
from app.services.notification_service import notify_visit_created
from app.services.notification_service import notify_visit_sheet_failed
from app.services.company_scope import (
    scope_active_agents,
    scope_visits,
    visit_agent_clause,
    visitable_property_clause,
    get_visit_in_company,
    get_visitable_property,
)
from app.services.visit_agents import VisitAgentsError
from app.services.visit_agents import companion_agent_groups
from app.services.visit_agents import parse_visit_agents
from app.services.visit_agents import visit_agents_locked
from app.web.dependencies.company import get_active_company
from app.web.dependencies.company import get_allowed_companies_from_request
from app.web.dependencies.company import get_company_ids
from app.web.dependencies.company import is_unified_view


router = APIRouter()
logger = logging.getLogger(__name__)

# Estados de una visita sin firmar: se edita desde la vista previa y vuelve a ella
UNSIGNED_VISIT_STATUSES = ("draft", "preview")

# Honorarios: importe o porcentaje, dígitos con separadores opcionales y '%'
# final si es porcentaje (2500, 2.500, 2500,50, 2%, 2,5%). La regla de los
# separadores (coma decimal, punto de miles) la comprueba `purchase_fees_error`
PURCHASE_FEES_PATTERN = re.compile(r"\d[\d.,]*%?")


def purchase_fees_from_form(form) -> str:
    """Honorarios del formulario limpios, con el signo: "2500" (euros) o "2,5%".

    El selector `purchase_fees_unit` ('€' por defecto o '%') pone el signo; si
    el agente escribe el '%' en el propio campo también vale
    (PLAN_CEDER_COMPRADORES.md §2). Antes de guardar se validan con
    `purchase_fees_error` y se normalizan con
    `PropertyVisit.normalize_purchase_fees`.
    """
    value = PropertyVisit.clean_purchase_fees(form.get("purchase_fees"))
    if value and form.get("purchase_fees_unit") == "%" and not value.endswith("%"):
        value += "%"
    return value


def purchase_fees_error(value: str):
    """Mensaje de error de unos honorarios ya limpios, o None si son válidos.

    Regla española (PLAN_VISITAS_INDICATIVO_HONORARIOS.md §2.2): coma para los
    decimales, punto solo para los miles; "1.2" se rechaza por ambiguo.
    """
    if not PURCHASE_FEES_PATTERN.fullmatch(value):
        return "Los honorarios deben ser solo el importe o el porcentaje (ej: 2500 o 2,5)"
    try:
        number = parse_es_decimal(value.rstrip("%"))
    except ValueError as error:
        return f"Revisa los honorarios: {error}"
    if value.endswith("%") and not 0 <= number <= 100:
        return "El porcentaje de honorarios debe estar entre 0 y 100"
    return None


def visit_phone_from_form(form) -> str | None:
    """Teléfono del visitante compuesto con el selector de país del macro
    `phone_field` (incluida la opción "Otro…" con el indicativo escrito en
    `phone_country_code_other`), en el formato guardado de compradores
    ("34600112233"; "+41791234567" si el indicativo no está en el selector).
    None si el número va vacío. Lanza PhoneValidationError si la parte local
    no tiene entre 6 y 12 dígitos o el indicativo escrito no existe
    (PLAN_VISITAS_INDICATIVO_HONORARIOS.md §2.1).
    """
    return phone_from_form(
        form.get("phone_country_code"),
        form.get("phone_number"),
        other_code=form.get("phone_country_code_other"),
    )


# Select "Empresa" del alta de visita (agente en vista unificada con varias empresas)
VISIT_COMPANY_FIELD = "visit_company_id"


def visit_company_options(request: Request) -> list:
    """Empresas entre las que un agente elige la de la visita nueva.

    Solo en la vista unificada con varias empresas
    (PLAN_VISTA_UNIFICADA_AGENTES.md §2.1): con una sola, el admin y la vista
    por empresa no se pregunta (lista vacía).
    """
    if not is_unified_view(request):
        return []
    company_ids = get_company_ids(request)
    if len(company_ids) < 2:
        return []
    return [c for c in get_allowed_companies_from_request(request) if c.id in company_ids]


def resolve_visit_company(request: Request, form=None):
    """Empresa de una visita nueva (PLAN_VISITAS_OTRA_EMPRESA.md, fase A).

    La visita es de la agencia desde la que se registra, no de la propiedad:
    - Admin o vista por empresa: la empresa activa.
    - Vista unificada con una empresa: esa (es su principal).
    - Vista unificada con varias: la elegida en el select "Empresa"
      (`visit_company_id`), validada contra `company_ids`; sin valor, la
      principal (la preseleccionada).
    Lanza VisitAgentsError (mensaje para el flash) si la elegida no es suya.
    """
    principal = get_active_company(request)
    options = visit_company_options(request)
    if not options:
        return principal
    raw = str(form.get(VISIT_COMPANY_FIELD) or "").strip() if form is not None else ""
    if not raw:
        return principal
    for company in options:
        if str(company.id) == raw:
            return company
    raise VisitAgentsError("La empresa elegida para la visita no es una de tus empresas")


def _street_visible(request: Request, property_item) -> bool:
    """Calle de la propiedad: regla de Propiedades (PLAN_CIERRES_MANUALES_Y_DIRECCIONES.md §2.2).

    Visible si la propiedad es de una empresa a la que pertenece el usuario
    (`allowed_companies`) o es admin. La ficha PDF y su vista previa la
    imprimen siempre (documento legal, PLAN_VISITAS_OTRA_EMPRESA.md §5).
    """
    if is_admin(request.state.user):
        return True
    allowed_ids = {c.id for c in get_allowed_companies_from_request(request)}
    return property_item.company_id in allowed_ids or property_item.company_id in get_company_ids(request)


def _property_back_url(property_item, company_ids) -> str:
    """Ficha de la propiedad si es de una empresa del usuario; si no, el selector."""
    if property_item is not None and property_item.company_id in company_ids:
        return f"/properties/{property_item.id}"
    return "/visits/select-property"


def _visit_agents_context(request: Request, db: Session, property_item, visit=None, company=None) -> dict:
    """Datos de la sección "Agentes de la visita" (alta y edición).

    - `agents`: agentes activos de la empresa de la visita (`company`; en la
      edición la de `visit`; si no, la activa) para el select del principal
      (admin), más el de la visita si está dado de baja, para no perderlo al
      editar (opción "(baja)", PLAN_BAJA_USUARIOS.md §4.3).
    - `companion_agents`: agentes de todas las empresas activas agrupados
      por empresa (select del acompañante); ver `companion_agent_groups`.
    - `principal_agent`: el que figura como "Realizada por" para un usuario
      agente (él mismo en el alta; el de la visita en la edición).
    - `selected_agent_id` / `selected_companion_agent_id`: valores iniciales
      de los selects (el admin parte del captador en el alta).
    """
    current_user = request.state.user
    current_agent = get_agent_from_user(current_user, db)

    if company is None:
        company = visit.company if visit is not None and visit.company is not None else get_active_company(request)
    company_id = company.id
    agents = (
        scope_active_agents(db.query(Agent), company_id)
        .order_by(Agent.name)
        .all()
    )

    if visit is not None and visit.agent is not None and visit.agent.is_active is False:
        agents = sorted([*agents, visit.agent], key=lambda a: a.name or "")

    # Lo mismo con el acompañante ya fijado: si está de baja se ofrece en un
    # grupo propio para que la edición no obligue a cambiarlo.
    companion_agents = companion_agent_groups(db, company_id)
    if (
        visit is not None
        and visit.companion_agent is not None
        and visit.companion_agent.is_active is False
    ):
        companion_agents.append({"label": "Dado de baja", "agents": [visit.companion_agent]})

    if visit is not None:
        principal_agent = visit.agent or current_agent
        selected_agent_id = visit.agent_id or property_item.agent_id
        selected_companion_agent_id = visit.companion_agent_id
    else:
        principal_agent = current_agent
        selected_agent_id = property_item.agent_id
        selected_companion_agent_id = None

    return {
        "agents": agents,
        "companion_agents": companion_agents,
        "current_agent": current_agent,
        "is_admin": bool(is_admin(current_user)),
        "principal_agent": principal_agent,
        "selected_agent_id": selected_agent_id,
        "selected_companion_agent_id": selected_companion_agent_id,
    }



@router.get("/visits", response_class=HTMLResponse)
async def visits_page(
    request: Request,
    db: Session = Depends(get_db)
):
    current_user = request.state.user
    current_agent = None

    # Si es admin, mostrar todas las visitas de la empresa activa.
    # Si es agente: las visitas en las que participó (principal o
    # acompañante) y las que otros hicieron a sus propiedades.
    visits_query = scope_visits(
        db.query(PropertyVisit).options(
            joinedload(PropertyVisit.agent),
            joinedload(PropertyVisit.companion_agent),
            joinedload(PropertyVisit.creator),
            joinedload(PropertyVisit.property).joinedload(Property.agent),
        ),
        get_company_ids(request)
    )

    if not is_admin(current_user):
        current_agent = get_agent_from_user(current_user, db)
        if current_agent:
            visits_query = visits_query.filter(
                or_(
                    visit_agent_clause(current_agent.id),
                    PropertyVisit.property.has(Property.agent_id == current_agent.id),
                )
            )
        else:
            # Si no tiene agente, no mostrar nada
            visits_query = visits_query.filter(PropertyVisit.id == -1)

    visits = visits_query.order_by(PropertyVisit.created_at.desc()).all()

    return templates.TemplateResponse(
        request=request,
        name="visits/home.html",
        context={
            "request": request,
            "visits": visits,
            "current_user": current_user,
            "current_agent": current_agent
        }
    )


@router.get("/visits/select-property", response_class=HTMLResponse)
async def select_property(
    request: Request,
    db: Session = Depends(get_db)
):
    from app.models.company import Company

    current_user = request.state.user
    admin = bool(is_admin(current_user))
    company_ids = get_company_ids(request)
    active_company = get_active_company(request)

    # Cualquier agente puede registrar visita en cualquier propiedad
    # disponible (decisión 1: sin aprobación previa), de cualquier empresa
    # (PLAN_VISITAS_OTRA_EMPRESA.md §5, decisión 4): de las suyas, todo lo no
    # archivado; de las demás, el inventario activo.
    properties = (
        db.query(Property)
        .options(joinedload(Property.agent), joinedload(Property.company))
        .filter(visitable_property_clause(company_ids), Property.available_clause())
        .order_by(Property.title)
        .all()
    )
    companies = db.query(Company).filter(Company.is_active.is_(True)).order_by(Company.id).all()

    # Calle de una propiedad de otra empresa: la regla de Propiedades (`_street_visible`)
    def street_visible(company):
        return _street_visible(request, SimpleNamespace(company_id=company.id))

    # Empresa en la que quedará la visita, para el texto de las secciones
    options = visit_company_options(request)
    visit_company_label = "la empresa que elijas" if options else active_company.name

    agent = None if admin else get_agent_from_user(current_user, db)
    sections = []

    if not admin:
        own = [p for p in properties if agent is not None and p.agent_id == agent.id and p.company_id in company_ids]
        sections.append({
            "title": "Mis propiedades",
            "subtitle": None,
            "properties": own,
            "show_street": True,
        })

    for company in companies:
        rows = [p for p in properties if p.company_id == company.id]
        if not admin:
            # Un usuario sin ficha de agente no registra visitas: no se le ofrece nada
            rows = [p for p in rows if agent is not None and p.agent_id != agent.id]
        own_company = company.id in company_ids
        if admin:
            title = f"Propiedades de {company.name}"
        elif own_company:
            title = f"Otras propiedades de {company.name}"
        else:
            title = f"Propiedades de {company.name}"
        if own_company and not admin:
            subtitle = "Captadas por otros agentes. La visita quedará registrada a tu nombre."
        elif own_company:
            subtitle = None
        else:
            subtitle = (
                f"Inmuebles comercializados por {company.name}. "
                f"La visita se registra en {visit_company_label} y la ficha lleva su marca."
            )
        sections.append({
            "title": title,
            "subtitle": subtitle,
            "properties": rows,
            "show_street": street_visible(company),
        })

    return templates.TemplateResponse(
        request=request,
        name="visits/select_property.html",
        context={
            "request": request,
            "is_admin": admin,
            "sections": sections,
            "current_user": current_user
        }
    )


@router.get("/visits/new/{property_id}", response_class=HTMLResponse)
async def new_visit(
    property_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    company_ids = get_company_ids(request)
    # Propiedad de cualquier empresa (PLAN_VISITAS_OTRA_EMPRESA.md, fase B)
    property_item = get_visitable_property(db, property_id, company_ids)

    if not property_item:
        response = RedirectResponse(url="/visits/select-property", status_code=302)
        set_flash(response, "error", "Propiedad no encontrada")
        return response

    if not property_item.is_available:
        response = RedirectResponse(url=_property_back_url(property_item, company_ids), status_code=302)
        set_flash(response, "error", "No se pueden registrar visitas en una propiedad No disponible")
        return response

    # Empresa de la visita: la preseleccionada (la principal o la activa);
    # un agente en varias empresas la puede cambiar en el select "Empresa"
    visit_company = resolve_visit_company(request)
    agents_context = _visit_agents_context(request, db, property_item, company=visit_company)
    current_agent = agents_context["current_agent"]

    # La ficha de la propiedad solo se abre si es de una empresa del usuario;
    # si no, "Volver" lleva al selector de propiedad
    property_in_scope = property_item.company_id in company_ids

    # Propiedad captada por otro agente: se avisa, pero no se bloquea
    is_foreign_property = (
        not agents_context["is_admin"]
        and current_agent is not None
        and property_item.agent_id != current_agent.id
    )

    return templates.TemplateResponse(
        request=request,
        name="properties/visit_form.html",
        context={
            "request": request,
            "property": property_item,
            "current_user": request.state.user,
            "is_foreign_property": is_foreign_property,
            "visit_company": visit_company,
            "property_in_scope": property_in_scope,
            "street_visible": _street_visible(request, property_item),
            "visit_company_choices": [(c.id, c.name) for c in visit_company_options(request)],
            "visit_company_field": VISIT_COMPANY_FIELD,
            **agents_context
        }
    )


@router.post("/visits/create/{property_id}")
async def create_visit(
    property_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    from app.services.visit_audit_service import log_visit_event

    company_ids = get_company_ids(request)
    property_item = get_visitable_property(db, property_id, company_ids)

    if not property_item:
        response = RedirectResponse(url="/visits/select-property", status_code=302)
        set_flash(response, "error", "Propiedad no encontrada")
        return response

    if not property_item.is_available:
        response = RedirectResponse(url=_property_back_url(property_item, company_ids), status_code=302)
        set_flash(response, "error", "No se pueden registrar visitas en una propiedad No disponible")
        return response

    form = await request.form()

    interest_level_raw = form.get("interest_level")
    interest_level = None
    if interest_level_raw not in (None, ""):
        try:
            interest_level = int(interest_level_raw)
        except (TypeError, ValueError):
            interest_level = None

    generate_sheet = form.get("generate_sheet") == "true"

    try:
        phone = visit_phone_from_form(form)
    except PhoneValidationError as error:
        response = RedirectResponse(url=f"/visits/new/{property_id}", status_code=302)
        set_flash(response, "error", str(error))
        return response

    visitor_name = (form.get("visitor_name") or "").strip()
    purchase_fees = purchase_fees_from_form(form)
    notes = (form.get("notes") or "").strip()

    if not visitor_name or not phone or not purchase_fees or not notes:
        response = RedirectResponse(url=f"/visits/new/{property_id}", status_code=302)
        set_flash(response, "error", "Nombre, teléfono, honorarios y observaciones son obligatorios")
        return response

    fees_error = purchase_fees_error(purchase_fees)
    if fees_error:
        response = RedirectResponse(url=f"/visits/new/{property_id}", status_code=302)
        set_flash(response, "error", fees_error)
        return response
    purchase_fees = PropertyVisit.normalize_purchase_fees(purchase_fees)

    try:
        # La visita es de la empresa desde la que se registra; el principal
        # se valida contra ella, no contra la de la propiedad
        visit_company = resolve_visit_company(request, form)
        agent_id, companion_agent_id = parse_visit_agents(
            form, request, db, property_item, company=visit_company
        )
    except VisitAgentsError as e:
        response = RedirectResponse(url=f"/visits/new/{property_id}", status_code=302)
        set_flash(response, "error", str(e))
        return response

    try:
        # Crear visita en estado 'draft' para seguir el nuevo flujo legal
        visit = PropertyVisit(
            property_id=property_id,
            company_id=visit_company.id,
            visitor_name=visitor_name,
            dni=form.get("dni"),
            phone=phone,
            email=form.get("email"),
            purchase_fees=purchase_fees,
            interest_level=interest_level,
            price_feedback=form.get("price_feedback"),
            location_feedback=form.get("location_feedback"),
            condition_feedback=form.get("condition_feedback"),
            lighting_feedback=form.get("lighting_feedback"),
            elevator_feedback=form.get("elevator_feedback"),
            garage_feedback=form.get("garage_feedback"),
            notes=notes,
            created_by=request.state.user.id,
            agent_id=agent_id,
            companion_agent_id=companion_agent_id,
            visit_status='draft'  # Nuevo flujo: inicia en draft
        )

        db.add(visit)
        db.commit()
        db.refresh(visit)

        # Registrar evento de auditoría
        log_visit_event(
            visit=visit,
            event_type='draft_created',
            db=db,
            request=request,
            event_data={
                'property_id': property_id,
                'visitor_name': visit.visitor_name,
                'generate_sheet': generate_sheet,
                'agent_id': visit.agent_id,
                'companion_agent_id': visit.companion_agent_id
            }
        )

        # Aviso in-app al captador (si no participó) y al acompañante.
        # Nunca rompe el alta: los errores quedan en el log.
        notify_visit_created(db, visit, actor=request.state.user)

        # Redirigir al preview en vez de generar PDF inmediatamente
        if generate_sheet:
            response = RedirectResponse(url=f"/visits/preview/{visit.id}", status_code=302)
            set_flash(response, "info", "Por favor, revise el documento antes de firmar")
            return response

        # El PDF no se genera aquí. Se generará después de que el cliente
        # revise el documento, acepte términos y firme (nuevo flujo legal)

        # Si no se solicita generar ficha, comportamiento antiguo (para compatibilidad)
        if not generate_sheet:
            visit.visit_status = 'completed'  # Completar directamente sin flujo legal
            db.commit()

            response = RedirectResponse(url=_property_back_url(property_item, company_ids), status_code=302)
            set_flash(response, "success", "Visita registrada")
            return response

    except Exception:
        db.rollback()
        logger.exception("Error registrando visita: property_id=%s", property_id)
        response = RedirectResponse(url=_property_back_url(property_item, company_ids), status_code=302)
        set_flash(response, "error", "Ocurrió un error al registrar la visita")
        return response


@router.get("/visits/{visit_id}/download")
async def download_visit_sheet(
    visit_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    visit = get_visit_in_company(db, visit_id, get_company_ids(request))

    if not visit or not visit.visit_sheet_filepath:
        response = RedirectResponse(url="/properties", status_code=302)
        set_flash(response, "error", "Ficha de visita no encontrada")
        return response

    filepath = Path(visit.visit_sheet_filepath)

    if not filepath.exists():
        response = RedirectResponse(url=f"/properties/{visit.property_id}", status_code=302)
        set_flash(response, "error", "Archivo de ficha de visita no existe")
        return response

    return FileResponse(
        path=str(filepath),
        filename=visit.visit_sheet_filename,
        media_type="application/pdf"
    )


@router.post("/visits/{visit_id}/send-whatsapp")
async def send_visit_sheet_whatsapp(
    visit_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    visit = get_visit_in_company(db, visit_id, get_company_ids(request))

    redirect_url = request.headers.get("referer") or "/visits"

    if not visit:
        response = RedirectResponse(url=redirect_url, status_code=302)
        set_flash(response, "error", "Visita no encontrada")
        return response

    property_item = db.query(Property).filter(Property.id == visit.property_id).first()

    if not property_item:
        response = RedirectResponse(url=redirect_url, status_code=302)
        set_flash(response, "error", "Propiedad no encontrada")
        return response

    if not visit.visit_sheet_filepath:
        response = RedirectResponse(url=redirect_url, status_code=302)
        set_flash(response, "error", "Esta visita no tiene ficha generada")
        return response

    filepath = Path(visit.visit_sheet_filepath)

    if not filepath.exists():
        response = RedirectResponse(url=redirect_url, status_code=302)
        set_flash(response, "error", "Archivo de ficha no existe")
        return response

    file_url = settings.public_url(str(filepath))

    sent_to = []
    send_failed = False

    triggered_by = request.state.user.id if request.state.user else None

    if not settings.VISIT_SHEET_WHATSAPP_ENABLED:
        # Envío desactivado por configuración (ver VISIT_SHEET_WHATSAPP_ENABLED)
        log_whatsapp_attempt(
            db=db,
            visit_id=visit.id,
            property_id=property_item.id,
            recipient_type="comprador",
            recipient_name=visit.visitor_name,
            recipient_phone=visit.phone,
            status="SKIPPED",
            trigger="manual_resend",
            error_message="Envío por WhatsApp desactivado (VISIT_SHEET_WHATSAPP_ENABLED=false)",
            triggered_by=triggered_by
        )
        response = RedirectResponse(url=redirect_url, status_code=302)
        set_flash(response, "info", "El envío de fichas de visita por WhatsApp está desactivado. La ficha sigue disponible para descargar.")
        return response

    if visit.phone:
        started_at = perf_counter()
        try:
            send_report(
                # La API quiere solo dígitos; los guardados con "Otro…" llevan "+"
                phone=canonical_phone(visit.phone) or visit.phone,
                file_url=file_url,
                caption=f"Ficha de visita - {property_item.title}"
            )
            sent_to.append("comprador")
            logger.info("Ficha enviada al comprador: %s", visit.phone)
            log_whatsapp_attempt(
                db=db,
                visit_id=visit.id,
                property_id=property_item.id,
                recipient_type="comprador",
                recipient_name=visit.visitor_name,
                recipient_phone=visit.phone,
                status="SENT",
                trigger="manual_resend",
                file_url=file_url,
                duration_ms=int((perf_counter() - started_at) * 1000),
                triggered_by=triggered_by
            )
        except Exception as e:
            send_failed = True
            logger.exception("Error enviando ficha al comprador: %s", visit.phone)
            log_whatsapp_attempt(
                db=db,
                visit_id=visit.id,
                property_id=property_item.id,
                recipient_type="comprador",
                recipient_name=visit.visitor_name,
                recipient_phone=visit.phone,
                status="ERROR",
                trigger="manual_resend",
                error_message=str(e),
                file_url=file_url,
                duration_ms=int((perf_counter() - started_at) * 1000),
                triggered_by=triggered_by
            )
    else:
        log_whatsapp_attempt(
            db=db,
            visit_id=visit.id,
            property_id=property_item.id,
            recipient_type="comprador",
            recipient_name=visit.visitor_name,
            status="SKIPPED",
            trigger="manual_resend",
            error_message="Visita sin teléfono registrado",
            triggered_by=triggered_by
        )

    # # Envio al numero del agente
    # if property_item.agent and property_item.agent.phone:
    #     try:
    #         send_report(
    #             phone=property_item.agent.phone,
    #             file_url=file_url,
    #             caption=f"Ficha de visita - {property_item.title}"
    #         )
    #         sent_to.append("agente")
    #         logger.info("Ficha enviada al agente: %s", property_item.agent.phone)
    #     except Exception:
    #         logger.exception("Error enviando ficha al agente: %s", property_item.agent.phone)

    # Aviso in-app al agente de la visita si el WhatsApp quedó en ERROR
    if send_failed:
        notify_visit_sheet_failed(db, visit, actor=request.state.user)

    if sent_to:
        response = RedirectResponse(url=redirect_url, status_code=302)
        set_flash(response, "success", f"Ficha enviada a {' y '.join(sent_to)}")
        return response
    else:
        response = RedirectResponse(url=redirect_url, status_code=302)
        set_flash(response, "error", "No se pudo enviar la ficha (verifique números de teléfono)")
        return response


@router.get("/visits/preview/{visit_id}", response_class=HTMLResponse)
async def preview_visit(
    visit_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Muestra la vista previa del documento de visita antes de la firma.
    FASE 2 del nuevo flujo legal.
    """
    from app.services.visit_audit_service import log_visit_event

    visit = get_visit_in_company(db, visit_id, get_company_ids(request))

    if not visit:
        response = RedirectResponse(url="/visits", status_code=302)
        set_flash(response, "error", "Visita no encontrada")
        return response

    property_item = db.query(Property).filter(
        Property.id == visit.property_id
    ).first()

    if not property_item:
        response = RedirectResponse(url="/visits", status_code=302)
        set_flash(response, "error", "Propiedad no encontrada")
        return response

    # Verificar que la visita está en estado draft o preview
    if visit.visit_status not in ['draft', 'preview']:
        response = RedirectResponse(url=f"/properties/{property_item.id}", status_code=302)
        set_flash(response, "warning", "Esta visita ya ha sido procesada")
        return response

    # Actualizar estado a preview si viene de draft
    if visit.visit_status == 'draft':
        visit.visit_status = 'preview'
        db.commit()

        # Registrar evento de auditoría
        log_visit_event(
            visit=visit,
            event_type='preview_viewed',
            db=db,
            request=request,
            event_data={'viewed_at': datetime.utcnow().isoformat()}
        )

    # Identidad de la empresa propietaria del inmueble: el preview debe
    # coincidir exactamente con el PDF que se firmará.
    from app.services.company_service import branding_for
    brand = branding_for(property_item.company)

    # Preparar datos para el template
    # Hora de España, igual que la ficha en PDF (PLAN_CEDER_COMPRADORES.md §4)
    visit_date = fmt_madrid(visit.created_at or datetime.utcnow(), "%d/%m/%Y")
    visit_time = fmt_madrid(visit.created_at or datetime.utcnow(), "%H:%M")
    # Mismo agente que el PDF: el que realizó la visita (o el captador en
    # visitas antiguas sin atribución) y, si lo hay, el acompañante.
    signing_agent = visit.signing_agent
    agent_name = signing_agent.name if signing_agent else f"Agente {brand.name}"
    companion_agent_name = visit.companion_agent.name if visit.companion_agent else None

    logo_exists = brand.logo_fs_path is not None

    return templates.TemplateResponse(
        request=request,
        name="visits/preview.html",
        context={
            "request": request,
            "visit": visit,
            "property": property_item,
            "visit_date": visit_date,
            "visit_time": visit_time,
            "agent_name": agent_name,
            "companion_agent_name": companion_agent_name,
            "logo_exists": logo_exists,
            "brand": brand,
            "current_user": request.state.user
        }
    )


@router.get("/visits/signature/{visit_id}", response_class=HTMLResponse)
async def signature_visit(
    visit_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Muestra el canvas de firma digital.
    FASE 3 del nuevo flujo legal.
    """
    visit = get_visit_in_company(db, visit_id, get_company_ids(request))

    if not visit:
        response = RedirectResponse(url="/visits", status_code=302)
        set_flash(response, "error", "Visita no encontrada")
        return response

    # Verificar que se aceptaron los términos
    if not visit.data_consent_accepted:
        response = RedirectResponse(url=f"/visits/preview/{visit_id}", status_code=302)
        set_flash(response, "warning", "Debe aceptar los términos antes de firmar")
        return response

    # Verificar que no esté ya firmada
    if visit.visit_status == 'signed' or visit.visit_status == 'completed':
        response = RedirectResponse(url=f"/visits/complete/{visit_id}", status_code=302)
        set_flash(response, "info", "Esta visita ya ha sido firmada")
        return response

    return templates.TemplateResponse(
        request=request,
        name="visits/signature.html",
        context={
            "request": request,
            "visit": visit,
            "current_user": request.state.user
        }
    )


@router.get("/visits/complete/{visit_id}", response_class=HTMLResponse)
async def complete_visit_page(
    visit_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Página de confirmación que finaliza el proceso y genera el PDF.
    FASE 4 del nuevo flujo legal.
    """
    visit = get_visit_in_company(db, visit_id, get_company_ids(request))

    if not visit:
        response = RedirectResponse(url="/visits", status_code=302)
        set_flash(response, "error", "Visita no encontrada")
        return response

    property_item = db.query(Property).filter(
        Property.id == visit.property_id
    ).first()

    if not property_item:
        response = RedirectResponse(url="/visits", status_code=302)
        set_flash(response, "error", "Propiedad no encontrada")
        return response

    # Verificar que tiene firma
    if not visit.signature_filepath:
        response = RedirectResponse(url=f"/visits/signature/{visit_id}", status_code=302)
        set_flash(response, "warning", "Debe firmar antes de continuar")
        return response

    # Visita conjunta: los agentes confirman sus firmas antes de finalizar
    if visit.visit_status == 'signed' and not visit.can_finalize_agents:
        response = RedirectResponse(url=f"/visits/agent-signatures/{visit_id}", status_code=302)
        set_flash(response, "warning", "Confirma las firmas de los agentes antes de finalizar la visita")
        return response

    return templates.TemplateResponse(
        request=request,
        name="visits/complete.html",
        context={
            "request": request,
            "visit": visit,
            "property": property_item,
            "current_user": request.state.user
        }
    )


@router.get("/visits/agent-signatures/{visit_id}", response_class=HTMLResponse)
async def agent_signatures_page(
    visit_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Confirmación de las firmas registradas de los dos agentes en una visita
    conjunta, tras la firma del cliente (PLAN_FIRMA_AGENTES_VISITA.md §3.2).
    Las visitas individuales no pasan por aquí.
    """
    company_ids = get_company_ids(request)
    visit = get_visit_in_company(db, visit_id, company_ids)

    if not visit:
        response = RedirectResponse(url="/visits", status_code=302)
        set_flash(response, "error", "Visita no encontrada")
        return response

    if visit.visit_status == 'completed':
        response = RedirectResponse(url=f"/properties/{visit.property_id}", status_code=302)
        set_flash(response, "info", "Esta visita ya está finalizada")
        return response

    if visit.visit_status != 'signed' or not visit.signature_filepath:
        response = RedirectResponse(url=f"/visits/signature/{visit_id}", status_code=302)
        set_flash(response, "warning", "El cliente debe firmar antes de confirmar las firmas de los agentes")
        return response

    if not visit.requires_agent_confirmation:
        return RedirectResponse(url=f"/visits/complete/{visit_id}", status_code=302)

    current_user = request.state.user
    current_agent = get_agent_from_user(current_user, db)
    admin = bool(is_admin(current_user))

    def agent_card(agent, role_label):
        return {
            "agent": agent,
            "role_label": role_label,
            "has_signature": agent.has_signature_file,
            # El agente registra su propia firma; el admin, la de cualquiera
            # (upload_agent_signature), desde Agentes de su empresa activa
            "can_register": admin or (current_agent is not None and current_agent.id == agent.id),
            "in_active_company": any(c.id in company_ids for c in agent.companies),
            "companies": ", ".join(c.name for c in agent.companies),
        }

    cards = [
        agent_card(agent, role_label)
        for agent, role_label in (
            (visit.signing_agent, "Agente inmobiliario"),
            (visit.companion_agent, "Agente acompañante"),
        )
        if agent is not None
    ]

    return templates.TemplateResponse(
        request=request,
        name="visits/agent_signatures.html",
        context={
            "request": request,
            "visit": visit,
            "property": visit.property,
            "cards": cards,
            "missing_agents": visit.agents_missing_signature,
            "is_admin": admin,
            "current_user": current_user
        }
    )


@router.post("/visits/{visit_id}/remove-companion")
async def remove_companion(
    visit_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Quita al acompañante antes de confirmar las firmas de los agentes: la
    visita pasa a individual (decisión 4 de PLAN_FIRMA_AGENTES_VISITA.md).
    """
    from app.services.visit_audit_service import log_visit_event

    visit = get_visit_in_company(db, visit_id, get_company_ids(request))

    if not visit:
        response = RedirectResponse(url="/visits", status_code=302)
        set_flash(response, "error", "Visita no encontrada")
        return response

    step_url = f"/visits/agent-signatures/{visit_id}"

    if visit.visit_status != 'signed' or not visit.requires_agent_confirmation:
        response = RedirectResponse(url=step_url, status_code=302)
        set_flash(response, "error", "Solo se puede quitar al acompañante tras la firma del cliente y antes de finalizar")
        return response

    if visit.agent_signatures_confirmed:
        response = RedirectResponse(url=step_url, status_code=302)
        set_flash(response, "error", "Las firmas de los agentes ya están confirmadas: no se puede quitar al acompañante")
        return response

    removed_id = visit.companion_agent_id
    removed_name = visit.companion_agent.name if visit.companion_agent else "El acompañante"

    try:
        visit.companion_agent_id = None
        db.commit()

        log_visit_event(
            visit=visit,
            event_type='companion_removed_before_confirmation',
            db=db,
            request=request,
            event_data={
                'agent_id': visit.agent_id,
                'companion_agent_id': removed_id,
            }
        )
    except Exception:
        db.rollback()
        logger.exception("Error quitando el acompañante de la visita: visit_id=%s", visit_id)
        response = RedirectResponse(url=step_url, status_code=302)
        set_flash(response, "error", "No se pudo quitar al acompañante. Inténtalo de nuevo")
        return response

    response = RedirectResponse(url=f"/visits/complete/{visit_id}", status_code=302)
    set_flash(response, "success", f"{removed_name} ya no figura en la visita. La ficha se emite como visita individual")
    return response


@router.get("/visits/edit/{visit_id}", response_class=HTMLResponse)
async def edit_visit(
    visit_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    visit = get_visit_in_company(db, visit_id, get_company_ids(request))

    if not visit:
        response = RedirectResponse(url="/visits", status_code=302)
        set_flash(response, "error", "Visita no encontrada")
        return response

    # Con "+41…" guardado el selector sale en "Otro…" con el 41 escrito
    phone_country_code, phone_local_number = split_phone(visit.phone)

    return templates.TemplateResponse(
        request=request,
        name="visits/edit_form.html",
        context={
            "request": request,
            "visit": visit,
            "current_user": request.state.user,
            "phone_country_code": phone_country_code,
            "phone_local_number": phone_local_number,
            "agents_locked": visit_agents_locked(visit),
            **_visit_agents_context(request, db, visit.property, visit=visit)
        }
    )


@router.post("/visits/update/{visit_id}")
async def update_visit(
    visit_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    visit = get_visit_in_company(db, visit_id, get_company_ids(request))

    if not visit:
        response = RedirectResponse(url="/visits", status_code=302)
        set_flash(response, "error", "Visita no encontrada")
        return response

    form = await request.form()

    interest_level_raw = form.get("interest_level")
    interest_level = None
    if interest_level_raw not in (None, ""):
        try:
            interest_level = int(interest_level_raw)
        except (TypeError, ValueError):
            interest_level = None

    # Guardar si tenía PDF antes de actualizar
    had_pdf = visit.visit_sheet_filepath is not None

    try:
        phone = visit_phone_from_form(form)
    except PhoneValidationError as error:
        response = RedirectResponse(url=f"/visits/edit/{visit_id}", status_code=302)
        set_flash(response, "error", str(error))
        return response

    visitor_name = (form.get("visitor_name") or "").strip()
    purchase_fees = purchase_fees_from_form(form)
    notes = (form.get("notes") or "").strip()

    if not visitor_name or not phone or not purchase_fees or not notes:
        response = RedirectResponse(url=f"/visits/edit/{visit_id}", status_code=302)
        set_flash(response, "error", "Nombre, teléfono, honorarios y observaciones son obligatorios")
        return response

    fees_error = purchase_fees_error(purchase_fees)
    if fees_error:
        response = RedirectResponse(url=f"/visits/edit/{visit_id}", status_code=302)
        set_flash(response, "error", fees_error)
        return response
    purchase_fees = PropertyVisit.normalize_purchase_fees(purchase_fees)

    # Agentes: fijos si la visita ya está firmada/completada (decisión 9)
    try:
        agent_id, companion_agent_id = parse_visit_agents(
            form,
            request,
            db,
            visit.property,
            visit=visit,
            locked=visit_agents_locked(visit)
        )
    except VisitAgentsError as e:
        response = RedirectResponse(url=f"/visits/edit/{visit_id}", status_code=302)
        set_flash(response, "error", str(e))
        return response

    previous_agents = (visit.agent_id, visit.companion_agent_id)

    try:
        visit.agent_id = agent_id
        visit.companion_agent_id = companion_agent_id
        visit.visitor_name = visitor_name
        visit.dni = form.get("dni") or None
        visit.phone = phone
        visit.email = form.get("email") or None
        visit.purchase_fees = purchase_fees
        visit.interest_level = interest_level
        visit.price_feedback = form.get("price_feedback") or None
        visit.location_feedback = form.get("location_feedback") or None
        visit.condition_feedback = form.get("condition_feedback") or None
        visit.lighting_feedback = form.get("lighting_feedback") or None
        visit.elevator_feedback = form.get("elevator_feedback") or None
        visit.garage_feedback = form.get("garage_feedback") or None
        visit.notes = notes

        db.commit()

        if previous_agents != (agent_id, companion_agent_id):
            from app.services.visit_audit_service import log_visit_event

            log_visit_event(
                visit=visit,
                event_type='agents_updated',
                db=db,
                request=request,
                event_data={
                    'previous_agent_id': previous_agents[0],
                    'previous_companion_agent_id': previous_agents[1],
                    'agent_id': agent_id,
                    'companion_agent_id': companion_agent_id
                }
            )

        # Si tenía PDF, regenerarlo automáticamente con los datos actualizados
        if had_pdf:
            try:
                property_item = db.query(Property).filter(Property.id == visit.property_id).first()

                if property_item:
                    visits_dir = Path("storage/visit_sheets")
                    visits_dir.mkdir(parents=True, exist_ok=True)

                    # Eliminar PDF anterior
                    if visit.visit_sheet_filepath:
                        old_path = Path(visit.visit_sheet_filepath)
                        if old_path.exists():
                            old_path.unlink()
                            logger.info("PDF anterior eliminado antes de regenerar: %s", visit.visit_sheet_filepath)

                    # Generar nuevo PDF con datos actualizados
                    filename = f"ficha_visita_{property_item.id}_{visit.id}_{uuid4().hex[:8]}.pdf"
                    output_path = visits_dir / filename

                    generate_visit_sheet(
                        property_item=property_item,
                        visit=visit,
                        agent=visit.signing_agent,
                        companion_agent=visit.companion_agent,
                        output_path=str(output_path)
                    )

                    visit.visit_sheet_filename = filename
                    visit.visit_sheet_filepath = str(output_path)
                    visit.visit_sheet_generated_at = datetime.utcnow()
                    db.commit()

                    logger.info("Ficha de visita regenerada después de edición: %s", output_path)

                    response = RedirectResponse(url="/visits", status_code=302)
                    set_flash(response, "success", "Visita actualizada y ficha PDF regenerada correctamente")
                    return response

            except Exception:
                logger.exception("Error regenerando PDF después de editar visita: visit_id=%s", visit_id)
                response = RedirectResponse(url="/visits", status_code=302)
                set_flash(response, "warning", "Visita actualizada, pero no se pudo regenerar el PDF")
                return response

        # Una visita aún sin firmar se editó desde su vista previa: se vuelve
        # a ella para seguir el flujo (aceptar términos y firmar).
        if visit.visit_status in UNSIGNED_VISIT_STATUSES:
            response = RedirectResponse(url=f"/visits/preview/{visit.id}", status_code=302)
            set_flash(response, "success", "Datos de la visita actualizados. Revisa el documento antes de firmar")
            return response

        response = RedirectResponse(url="/visits", status_code=302)
        set_flash(response, "success", "Visita actualizada correctamente")
        return response

    except Exception:
        db.rollback()
        logger.exception("Error actualizando visita: visit_id=%s", visit_id)
        response = RedirectResponse(url="/visits", status_code=302)
        set_flash(response, "error", "Ocurrió un error al actualizar la visita")
        return response


@router.post("/visits/delete")
async def delete_visit(
    request: Request,
    visit_id: int = Form(...),
    db: Session = Depends(get_db)
):
    import os

    visit = get_visit_in_company(db, visit_id, get_company_ids(request))

    response = RedirectResponse(url="/visits", status_code=302)

    if not visit:
        set_flash(response, "error", "Visita no encontrada")
        return response

    try:
        # Eliminar archivo PDF si existe
        if visit.visit_sheet_filepath and os.path.exists(visit.visit_sheet_filepath):
            os.remove(visit.visit_sheet_filepath)
            logger.info("Archivo PDF eliminado: %s", visit.visit_sheet_filepath)

        db.delete(visit)
        db.commit()

        set_flash(response, "success", "Visita eliminada correctamente")
    except Exception:
        db.rollback()
        logger.exception("Error eliminando visita: visit_id=%s", visit_id)
        set_flash(response, "error", "Ocurrió un error al eliminar la visita")

    return response


@router.post("/visits/{visit_id}/generate-pdf")
async def generate_visit_pdf(
    visit_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    visit = get_visit_in_company(db, visit_id, get_company_ids(request))

    redirect_url = request.headers.get("referer") or "/visits"

    if not visit:
        response = RedirectResponse(url=redirect_url, status_code=302)
        set_flash(response, "error", "Visita no encontrada")
        return response

    property_item = db.query(Property).filter(Property.id == visit.property_id).first()

    if not property_item:
        response = RedirectResponse(url=redirect_url, status_code=302)
        set_flash(response, "error", "Propiedad no encontrada")
        return response

    try:
        visits_dir = Path("storage/visit_sheets")
        visits_dir.mkdir(parents=True, exist_ok=True)

        # Si ya existe un PDF, eliminarlo
        if visit.visit_sheet_filepath:
            old_path = Path(visit.visit_sheet_filepath)
            if old_path.exists():
                old_path.unlink()
                logger.info("PDF anterior eliminado: %s", visit.visit_sheet_filepath)

        filename = f"ficha_visita_{property_item.id}_{visit.id}_{uuid4().hex[:8]}.pdf"
        output_path = visits_dir / filename

        generate_visit_sheet(
            property_item=property_item,
            visit=visit,
            agent=visit.signing_agent,
            companion_agent=visit.companion_agent,
            output_path=str(output_path)
        )

        visit.visit_sheet_filename = filename
        visit.visit_sheet_filepath = str(output_path)
        visit.visit_sheet_generated_at = datetime.utcnow()
        db.commit()

        logger.info("Ficha de visita generada: %s", output_path)

        response = RedirectResponse(url=redirect_url, status_code=302)
        set_flash(response, "success", "Ficha de visita generada correctamente")
        return response

    except Exception:
        db.rollback()
        logger.exception("Error generando ficha de visita: visit_id=%s", visit_id)
        response = RedirectResponse(url=redirect_url, status_code=302)
        set_flash(response, "error", "Ocurrió un error al generar la ficha")
        return response
