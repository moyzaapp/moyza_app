import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter
from fastapi import Request
from fastapi import Depends
from fastapi import Form
from fastapi import Query

from fastapi.responses import HTMLResponse
from fastapi.responses import RedirectResponse
from fastapi.responses import JSONResponse

from app.web.template_env import templates

from sqlalchemy.orm import Session, contains_eager, selectinload
from sqlalchemy import func, case, or_

from app.core.constants import AlertType, PropertyStatus
from app.core.constants import BusinessType
from app.core.constants import AlertPriority
from app.core.constants import AlertStatus
from app.core.constants import FollowUpActionType
from app.core.phone import PhoneValidationError, phone_display, phone_from_form, split_phone, valid_country_code
from app.db.deps import get_db

from app.models.property_alert import PropertyAlert
from app.models.alert_follow_up import AlertFollowUp
from app.models.property import Property
from app.models.agent import Agent
from app.models.user import User
from app.models.buyer import Buyer
from app.models.buyer_search_criteria import BuyerSearchCriteria

from app.services.company_scope import (
    scope_alerts,
    scope_agents,
    scope_buyers,
    scope_properties,
    get_alert_in_company,
    get_buyer_in_company,
    get_property_in_company,
)
from app.services.alert_duplicate_service import (
    find_duplicate_alerts,
    find_matching_buyers,
    serialize_duplicates,
    serialize_buyer,
    duplicate_note,
    new_contact_note,
    append_note,
)
from app.services import alert_assignment_service as assignment
from app.services.alert_assignment_service import AlertAssignmentError
from app.web.utils.flash import set_flash
from app.web.dependencies.auth import is_admin, get_agent_from_user, require_admin_role
from app.web.dependencies.company import get_active_company


router = APIRouter()
logger = logging.getLogger(__name__)


# Estados que se consideran "abiertos" para la cola secuencial del agente
OPEN_ALERT_STATUSES = [AlertStatus.PENDING, AlertStatus.IN_PROGRESS]

# Máximo de sugerencias devueltas por el autocompletado de propiedades
PROPERTY_SEARCH_LIMIT = 15

# Paginación de /alerts (PLAN_PAGINACION_ALERTAS.md): un solo tamaño de página
# para la tabla de alertas y la de compradores, recordado en una cookie.
PAGE_SIZES = (50, 100, 200, 300)
DEFAULT_PAGE_SIZE = 100
PER_PAGE_COOKIE = "alerts_per_page"
PER_PAGE_COOKIE_MAX_AGE = 365 * 24 * 60 * 60  # 1 año


def normalize_per_page(value) -> int:
    """Tamaño de página válido: uno de PAGE_SIZES; cualquier otra cosa → 100."""
    try:
        per_page = int(str(value).strip())
    except (TypeError, ValueError):
        return DEFAULT_PAGE_SIZE
    return per_page if per_page in PAGE_SIZES else DEFAULT_PAGE_SIZE


def paginate_params(page, per_page, total) -> dict:
    """Aritmética de paginación, sin base de datos.

    `page` puede llegar como texto de la query string: si no es numérico o es
    menor que 1 se usa la 1, y si pasa de la última se usa la última (nunca
    error). `start`/`end` son posiciones 1-based para "Mostrando start–end de
    total" (0–0 cuando no hay resultados).
    """
    per_page = normalize_per_page(per_page)
    try:
        page = int(str(page).strip())
    except (TypeError, ValueError):
        page = 1
    total = max(int(total or 0), 0)

    pages = max((total + per_page - 1) // per_page, 1)
    page = min(max(page, 1), pages)
    offset = (page - 1) * per_page

    return {
        "page": page,
        "per_page": per_page,
        "total": total,
        "pages": pages,
        "offset": offset,
        "start": offset + 1 if total else 0,
        "end": min(offset + per_page, total),
        "has_prev": page > 1,
        "has_next": page < pages,
    }


def effective_alert_statuses(status_filter, q) -> Optional[list]:
    """Estados que filtra realmente el listado de alertas.

    - Con estados marcados: esos (solo los válidos, sin repetir).
    - Sin estados y sin texto (vista por defecto): Pendiente y En proceso.
    - Sin estados y con texto: None (busca en todos los estados, para que un
      comprador con la alerta ya completada también aparezca).
    """
    valid = []
    for status in status_filter or []:
        if AlertStatus.is_valid(status) and status not in valid:
            valid.append(status)
    if valid:
        return valid
    if q and q.strip():
        return None
    return list(OPEN_ALERT_STATUSES)


def _property_filter_values(db: Session, company_id: int) -> dict:
    """Valores distintos (zona, ciudad, tipo, operación) de las propiedades de la empresa."""
    def distinct_values(column, exclude_empty: bool = False):
        query = scope_properties(db.query(column), company_id).filter(column.isnot(None))
        if exclude_empty:
            query = query.filter(column != "")
        return [r[0] for r in query.distinct().order_by(column.asc()).all()]

    return {
        "zones": distinct_values(Property.zona, exclude_empty=True),
        "cities": distinct_values(Property.city, exclude_empty=True),
        "property_types": distinct_values(Property.property_type),
        "business_types": distinct_values(Property.business_type),
    }


def _get_agent_open_alerts_ordered(agent_id: int, db: Session, company_id: int):
    """Devuelve las alertas abiertas del agente en la empresa, ordenadas FIFO
    por fecha de asignación.

    La cola secuencial es por empresa: una alerta pendiente en MOYZA no
    bloquea el trabajo del mismo agente en MOES (y viceversa).
    """
    return (
        scope_alerts(db.query(PropertyAlert), company_id)
        .filter(
            PropertyAlert.agent_id == agent_id,
            PropertyAlert.status.in_(OPEN_ALERT_STATUSES),
        )
        # Una alerta reasignada entra en la cola del nuevo agente por la fecha
        # de asignación (PLAN_ASIGNACION_ALERTAS.md §2.5); las no reasignadas
        # tienen assigned_at = created_at, así que su orden no cambia.
        .order_by(
            func.coalesce(PropertyAlert.assigned_at, PropertyAlert.created_at).asc(),
            PropertyAlert.id.asc(),
        )
        .all()
    )


def can_access_buyer(buyer: Buyer, current_user, db: Session) -> bool:
    """El admin accede a todos los compradores. El agente, a los que registró
    él, a los que tienen su ficha asignada como agente responsable del perfil
    de búsqueda, o a los que tienen alguna alerta suya."""
    if is_admin(current_user):
        return True

    if current_user and buyer.created_by == current_user.id:
        return True

    agent = get_agent_from_user(current_user, db)
    if not agent:
        return False

    if buyer.search_criteria and buyer.search_criteria.agent_id == agent.id:
        return True

    return (
        db.query(PropertyAlert.id)
        .filter(PropertyAlert.buyer_id == buyer.id, PropertyAlert.agent_id == agent.id)
        .first()
        is not None
    )


def visible_buyers_query(db: Session, current_user, company_id: int):
    """Compradores de la empresa que el usuario puede ver en listados y buscadores.

    El admin ve todos. El agente ve los que registró él, los que tienen su
    ficha como agente responsable del perfil de búsqueda, y aquellos cuyas
    alertas suyas ya iniciaron seguimiento (status distinto de PENDING), así
    la lista se va llenando a medida que gestiona alertas.
    """
    query = scope_buyers(db.query(Buyer), company_id)

    if is_admin(current_user):
        return query

    conditions = [Buyer.created_by == current_user.id]

    agent = get_agent_from_user(current_user, db)
    if agent:
        started_buyer_ids = (
            scope_alerts(db.query(PropertyAlert.buyer_id), company_id)
            .filter(
                PropertyAlert.buyer_id.isnot(None),
                PropertyAlert.status != AlertStatus.PENDING,
                PropertyAlert.agent_id == agent.id,
            )
            .subquery()
        )
        assigned_buyer_ids = (
            db.query(BuyerSearchCriteria.buyer_id)
            .filter(BuyerSearchCriteria.agent_id == agent.id)
            .subquery()
        )
        conditions += [
            Buyer.id.in_(started_buyer_ids),
            Buyer.id.in_(assigned_buyer_ids),
        ]

    return query.filter(or_(*conditions))


def _real_follow_ups(db: Session, alert_id: int):
    """Seguimientos registrados por un agente o admin (sin las notas del sistema).

    La nota automática de reasignación no cuenta como gestión: no desbloquea
    la cola ni permite cerrar la alerta.
    """
    return db.query(AlertFollowUp).filter(
        AlertFollowUp.alert_id == alert_id,
        AlertFollowUp.action_type.notin_(FollowUpActionType.SYSTEM_ACTIONS),
    )


def get_locked_alert_ids(agent_id: int, db: Session, company_id: int) -> set:
    """Devuelve el conjunto de IDs de alertas bloqueadas para un agente en la empresa.

    Una alerta en la cola está bloqueada si alguna alerta anterior (más antigua)
    aún no tiene ningún seguimiento registrado. En cuanto el agente registra
    cualquier seguimiento en la alerta actual, la siguiente se desbloquea.
    """
    open_alerts = _get_agent_open_alerts_ordered(agent_id, db, company_id)
    if not open_alerts:
        return set()

    # Una sola consulta para saber qué alertas de la cola ya tienen seguimiento
    # (antes era una consulta por alerta)
    started_ids = {
        row[0]
        for row in db.query(AlertFollowUp.alert_id)
        .filter(
            AlertFollowUp.alert_id.in_([a.id for a in open_alerts]),
            AlertFollowUp.action_type.notin_(FollowUpActionType.SYSTEM_ACTIONS),
        )
        .distinct()
    }

    locked = set()
    all_preceding_started = True
    for alert in open_alerts:
        if not all_preceding_started:
            locked.add(alert.id)
        elif alert.id not in started_ids:
            all_preceding_started = False
    return locked


def is_alert_locked_for_user(alert: PropertyAlert, current_user, db: Session) -> bool:
    """True si la alerta está bloqueada para este usuario.

    El admin nunca está bloqueado. Un agente está bloqueado si alguna alerta
    anterior en su cola no tiene seguimientos. Las alertas cerradas no cuentan.
    """
    if is_admin(current_user):
        return False

    if alert.status not in OPEN_ALERT_STATUSES:
        return False

    agent = get_agent_from_user(current_user, db)
    if not agent:
        return False

    # La cola se evalúa dentro de la empresa de la propia alerta. Misma regla
    # que el listado: bloqueada si alguna anterior de la cola no tiene seguimiento.
    return alert.id in get_locked_alert_ids(agent.id, db, alert.property.company_id)


@router.get("/alerts", response_class=HTMLResponse)
async def alerts_page(
    request: Request,
    q: str = Query(default=""),
    status_filter: List[str] = Query(default=[]),
    agent_id: Optional[str] = Query(default=None),
    # Paginación: se reciben como texto para que un valor no numérico vaya a
    # la página 1 / tamaño por defecto en vez de devolver un 422
    page: Optional[str] = Query(default=None),
    per_page: Optional[str] = Query(default=None),
    b_q: str = Query(default=""),
    b_page: Optional[str] = Query(default=None),
    db: Session = Depends(get_db)
):
    """Lista de alertas - Admin ve todas, agentes solo las suyas.

    Las dos tablas (alertas y compradores) se paginan en servidor: los
    filtros se aplican sobre todo el conjunto y luego se corta la página.
    """

    current_user = request.state.user
    company = get_active_company(request)
    admin_view = is_admin(current_user)
    agent = None if admin_view else get_agent_from_user(current_user, db)

    # Base query: solo alertas de propiedades de la empresa activa. El JOIN con
    # agentes va por el agente de la ALERTA (no el captador de la propiedad):
    # property_alerts tiene dos FK a agents y la propiedad puede no tener captador.
    base_query = scope_alerts(
        db.query(PropertyAlert)
        .join(Property, Property.id == PropertyAlert.property_id)
        .join(Agent, Agent.id == PropertyAlert.agent_id),
        company.id,
    )

    # Si es agente, filtrar solo sus alertas
    if not admin_view:
        if agent:
            base_query = base_query.filter(PropertyAlert.agent_id == agent.id)
        else:
            # Si no es admin y no tiene agente asociado, no mostrar nada
            base_query = base_query.filter(PropertyAlert.id == -1)

    # Filtro por texto: nombre del comprador, teléfono o título de propiedad
    if q and q.strip():
        like = f"%{q.strip()}%"
        base_query = base_query.filter(
            or_(
                PropertyAlert.lead_name.ilike(like),
                PropertyAlert.lead_phone.ilike(like),
                Property.title.ilike(like),
            )
        )

    # Filtro por agente (solo admin; agentes ya están filtrados por su propio id)
    agent_id_int = int(agent_id) if agent_id and agent_id.strip() else None
    if agent_id_int and admin_view:
        base_query = base_query.filter(PropertyAlert.agent_id == agent_id_int)

    # Contar alertas por estado (una sola consulta agrupada) ANTES del filtro
    # de estado y sin paginar: las tarjetas muestran los totales reales bajo
    # los filtros de texto y agente, marque el usuario los estados que marque.
    status_counts = dict(
        base_query
        .with_entities(PropertyAlert.status, func.count(PropertyAlert.id))
        .group_by(PropertyAlert.status)
        .all()
    )
    pending_count = status_counts.get(AlertStatus.PENDING, 0)
    in_progress_count = status_counts.get(AlertStatus.IN_PROGRESS, 0)
    completed_count = status_counts.get(AlertStatus.COMPLETED, 0)

    # Filtro por estado (multi-select). Sin estados marcados y sin texto se
    # muestran solo las abiertas; sin estados y con texto, todas.
    valid_status_filters = [s for s in status_filter if AlertStatus.is_valid(s)]
    effective_statuses = effective_alert_statuses(status_filter, q)
    default_status_view = not valid_status_filters and not (q and q.strip())
    filtered_query = base_query
    if effective_statuses:
        filtered_query = filtered_query.filter(PropertyAlert.status.in_(effective_statuses))

    # Tamaño de página: el explícito de la URL manda (y se recuerda en una
    # cookie); si no llega, el de la cookie; si tampoco, 100.
    per_page_explicit = per_page is not None and per_page.strip() != ""
    per_page_value = normalize_per_page(
        per_page if per_page_explicit else request.cookies.get(PER_PAGE_COOKIE)
    )

    # Total filtrado. Los JOIN a Property y Agent son N:1 (una fila por alerta),
    # así que contar PropertyAlert.id no se multiplica.
    total_alerts = filtered_query.with_entities(func.count(PropertyAlert.id)).scalar() or 0
    alert_pagination = paginate_params(page, per_page_value, total_alerts)

    # Ordenar por prioridad y fecha (el id solo desempata para que la
    # paginación sea estable). Propiedad y agente se rellenan con el JOIN
    # que ya hace la consulta, y los seguimientos de la página se cargan en
    # una segunda consulta: sin esto se hacía una consulta por alerta al
    # pintar la tabla (N+1).
    alerts = (
        filtered_query
        .options(
            contains_eager(PropertyAlert.property),
            contains_eager(PropertyAlert.agent),
            selectinload(PropertyAlert.follow_ups),
        )
        .order_by(
            case(
                (PropertyAlert.priority == AlertPriority.ALTA, 1),
                (PropertyAlert.priority == AlertPriority.NORMAL, 2),
                (PropertyAlert.priority == AlertPriority.BAJA, 3),
                else_=4
            ),
            PropertyAlert.created_at.desc(),
            PropertyAlert.id.desc(),
        )
        .offset(alert_pagination["offset"])
        .limit(alert_pagination["per_page"])
        .all()
    )

    # Agentes para el formulario de creación (solo admin). Las propiedades no se
    # precargan: el formulario las busca por /alerts/search-properties.
    agents = []
    assignable_groups = []
    if admin_view:
        agents = scope_agents(db.query(Agent), company.id).order_by(Agent.name.asc()).all()
        # "Agente asignado" del alta y de la reasignación: todas las empresas (§4-1 B)
        assignable_groups = assignment.assignable_agents(db, company.id)

    # Compradores visibles: el título "Compradores (N)" y el desglose por
    # operación usan el total; la tabla, la página pedida tras el buscador
    # propio de la sección (b_q).
    visible_buyers = visible_buyers_query(db, current_user, company.id)
    total_visible_buyers = visible_buyers.count()

    buyers_filtered = visible_buyers
    b_q_term = (b_q or "").strip()
    if b_q_term:
        b_like = f"%{b_q_term}%"
        buyers_filtered = buyers_filtered.filter(
            or_(
                Buyer.name.ilike(b_like),
                Buyer.phone.ilike(b_like),
                Buyer.email.ilike(b_like),
            )
        )
    total_buyers = buyers_filtered.count() if b_q_term else total_visible_buyers
    buyer_pagination = paginate_params(b_page, per_page_value, total_buyers)

    buyers = (
        buyers_filtered
        .order_by(Buyer.name.asc(), Buyer.id.asc())
        .offset(buyer_pagination["offset"])
        .limit(buyer_pagination["per_page"])
        .all()
    )

    # Número de alertas de cada comprador de la página (columna "Alertas"), en
    # una consulta agrupada en vez de cargar `buyer.alerts` comprador por comprador.
    buyer_ids = [b.id for b in buyers]
    buyer_alert_counts = {}
    buyer_operation_counts = {}

    if buyer_ids:
        buyer_alert_counts = dict(
            db.query(PropertyAlert.buyer_id, func.count(PropertyAlert.id))
            .filter(PropertyAlert.buyer_id.in_(buyer_ids))
            .group_by(PropertyAlert.buyer_id)
            .all()
        )

    if total_visible_buyers:
        # Conteo por tipo de operación de TODOS los compradores visibles (no
        # solo los de la página ni del total de alertas del sistema), para que
        # el desglose "N Alquiler, N Venta" cuadre con "Compradores (N)". Para
        # el admin cuentan todas sus alertas; para el agente, solo las que ya
        # iniciaron seguimiento y son suyas.
        operation_query = db.query(
            PropertyAlert.business_type, func.count(PropertyAlert.id)
        ).filter(
            PropertyAlert.buyer_id.in_(visible_buyers.with_entities(Buyer.id)),
            PropertyAlert.business_type.isnot(None),
            PropertyAlert.business_type != "",
        )
        if not admin_view:
            operation_query = operation_query.filter(
                PropertyAlert.status != AlertStatus.PENDING,
                PropertyAlert.agent_id == (agent.id if agent else -1),
            )
        buyer_operation_counts = dict(
            operation_query
            .group_by(PropertyAlert.business_type)
            .order_by(PropertyAlert.business_type)
            .all()
        )

    # Valores para selectores del modal de criteria
    filter_values = _property_filter_values(db, company.id)
    zones = filter_values["zones"]
    cities = filter_values["cities"]
    property_types = filter_values["property_types"]
    business_types = filter_values["business_types"]

    # Alertas abiertas del agente en sus OTRAS empresas (PLAN_ASIGNACION_ALERTAS.md
    # §2.6): una alerta asignada en otra empresa no aparece aquí, así que se
    # avisa con un banner para que cambie de empresa.
    other_company_alerts = []
    if not admin_view and agent:
        for other in getattr(request.state, "allowed_companies", None) or []:
            if other.id == company.id:
                continue
            count = (
                scope_alerts(db.query(PropertyAlert.id), other.id)
                .filter(
                    PropertyAlert.agent_id == agent.id,
                    PropertyAlert.status.in_(OPEN_ALERT_STATUSES),
                )
                .count()
            )
            if count:
                other_company_alerts.append({"company": other, "count": count})

    # Calcular alertas bloqueadas y etapa actual de cada alerta
    locked_alert_ids = set()
    if agent:
        locked_alert_ids = get_locked_alert_ids(agent.id, db, company.id)

    # Etapa actual de cada alerta: último seguimiento de progresión (ignora
    # SIN_RESPUESTA para no retroceder la etapa visible; si solo hay sin-respuesta,
    # lo muestra igualmente).
    alert_stages = {}
    labels = FollowUpActionType.labels()
    for alert in alerts:
        # Las notas del sistema (reasignación) no son una etapa
        real = [f for f in alert.follow_ups if f.action_type not in FollowUpActionType.SYSTEM_ACTIONS]
        if real:
            progression = [
                f for f in real
                if f.action_type not in FollowUpActionType.REPEATABLE_ACTIONS
            ]
            latest = max(
                progression if progression else real,
                key=lambda f: f.created_at,
            )
            alert_stages[alert.id] = {
                "value": latest.action_type,
                "label": labels.get(latest.action_type, latest.action_type),
                "color": FollowUpActionType.stage_badge_color(latest.action_type),
            }

    response = templates.TemplateResponse(
        request=request,
        name="alerts/list.html",
        context={
            "request": request,
            "alerts": alerts,
            "total_alerts": total_alerts,
            "alert_pagination": alert_pagination,
            "buyers": buyers,
            "total_visible_buyers": total_visible_buyers,
            "buyer_pagination": buyer_pagination,
            "b_q": b_q_term,
            "per_page": per_page_value,
            "page_sizes": PAGE_SIZES,
            "effective_statuses": effective_statuses or [],
            "default_status_view": default_status_view,
            "buyer_alert_counts": buyer_alert_counts,
            "buyer_operation_counts": buyer_operation_counts,
            "current_user": current_user,
            "pending_count": pending_count,
            "in_progress_count": in_progress_count,
            "completed_count": completed_count,
            "agents": agents,
            "assignable_groups": assignable_groups,
            "other_company_alerts": other_company_alerts,
            "locked_alert_ids": locked_alert_ids,
            "alert_stages": alert_stages,
            "is_admin": is_admin(current_user),
            "zones": zones,
            "cities": cities,
            "property_types": property_types,
            "business_types": business_types,
            "AlertType": AlertType,
            "AlertPriority": AlertPriority,
            "AlertStatus": AlertStatus,
            "q": q,
            "status_filter": valid_status_filters,
            "selected_agent_id": agent_id_int,
        }
    )

    # Preferencia de tamaño de página: solo se guarda cuando el usuario la elige
    if per_page_explicit:
        response.set_cookie(
            key=PER_PAGE_COOKIE,
            value=str(per_page_value),
            max_age=PER_PAGE_COOKIE_MAX_AGE,
            httponly=True,
            samesite="lax",
            path="/",
        )

    return response


@router.get("/alerts/search-buyers")
async def search_buyers(
    request: Request,
    q: str = "",
    db: Session = Depends(get_db)
):
    """Autocompletado de compradores para el formulario de nueva alerta.

    El agente solo encuentra los compradores que puede ver."""

    current_user = request.state.user

    term = (q or "").strip()

    if len(term) < 2:
        return JSONResponse(content={"results": []})

    like = f"%{term}%"

    buyers = (
        visible_buyers_query(db, current_user, get_active_company(request).id)
        .filter(
            or_(
                Buyer.name.ilike(like),
                Buyer.phone.ilike(like),
                Buyer.email.ilike(like),
            )
        )
        .order_by(Buyer.name.asc())
        .limit(15)
        .all()
    )

    results = [
        {
            "id": b.id,
            "name": b.name,
            "phone": b.phone or "",
            "phone_display": phone_display(b.phone),
            "email": b.email or "",
        }
        for b in buyers
    ]

    return JSONResponse(content={"results": results})


@router.post("/buyers/create")
async def create_buyer(
    request: Request,
    name: str = Form(...),
    phone_country_code: str = Form(None),
    phone_number: str = Form(None),
    phone: str = Form(None),
    email: str = Form(None),
    notes: str = Form(None),
    db: Session = Depends(get_db)
):
    """Crear nuevo comprador sin alerta asociada (admin y agentes).

    El comprador queda registrado a nombre del usuario (`created_by`), que es
    lo que le da acceso al agente que lo creó.

    Teléfono: indicativo + número (PLAN_TELEFONO_COMPRADOR.md); `phone` es el
    campo antiguo de texto libre, aceptado si llega solo."""

    current_user = request.state.user

    name = (name or "").strip()
    if not name:
        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "error", "El nombre del comprador es obligatorio")
        return response

    try:
        buyer_phone = phone_from_form(phone_country_code, phone_number, phone)
    except PhoneValidationError as error:
        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "error", str(error))
        return response

    try:
        buyer = Buyer(
            name=name,
            phone=buyer_phone,
            email=(email or "").strip() or None,
            notes=notes,
            created_by=current_user.id,
            company_id=get_active_company(request).id
        )
        db.add(buyer)
        db.commit()

        response = RedirectResponse(url="/alerts?tab=buyers", status_code=302)
        set_flash(response, "success", f"Comprador {name} creado correctamente")
        return response

    except Exception:
        db.rollback()
        logger.exception("Error creando comprador")
        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "error", "Ocurrió un error al crear el comprador")
        return response


@router.post("/buyers/create-with-criteria")
async def create_buyer_with_criteria(
    request: Request,
    buyer_id: int = Form(None),
    buyer_name: str = Form(None),
    buyer_phone_country_code: str = Form(None),
    buyer_phone_number: str = Form(None),
    buyer_phone: str = Form(None),
    buyer_email: str = Form(None),
    agent_id: int = Form(None),
    property_type: str = Form(None),
    business_type: str = Form(None),
    min_price: str = Form(None),
    max_price: str = Form(None),
    min_bedrooms: str = Form(None),
    max_bedrooms: str = Form(None),
    min_bathrooms: str = Form(None),
    min_m2: str = Form(None),
    max_m2: str = Form(None),
    notes: str = Form(None),
    db: Session = Depends(get_db)
):
    """Crea o selecciona un comprador, guarda sus criterios y va a los matches.

    Admin y agentes. El agente queda siempre como agente responsable del
    perfil (no puede asignárselo a otro) y solo puede elegir compradores a
    los que ya tiene acceso."""

    current_user = request.state.user
    admin_view = is_admin(current_user)

    if not admin_view:
        own_agent = get_agent_from_user(current_user, db)
        if not own_agent:
            response = RedirectResponse(url="/alerts", status_code=302)
            set_flash(response, "error", "Tu usuario no tiene ficha de agente asociada")
            return response
        agent_id = own_agent.id

    # Operación obligatoria: solo Venta o Alquiler (no se guarda nada si falta)
    business_type = (business_type or "").strip()
    if not BusinessType.is_valid(business_type):
        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "error", "Selecciona la operación del comprador: Venta o Alquiler")
        return response

    form_data = await request.form()
    zones = form_data.getlist("zones")
    cities_sel = form_data.getlist("cities")

    def to_int(v):
        try:
            return int(v) if v and str(v).strip() else None
        except (ValueError, TypeError):
            return None

    def to_decimal(v):
        try:
            return float(v) if v and str(v).strip() else None
        except (ValueError, TypeError):
            return None

    try:
        # Resolver comprador
        if buyer_id:
            buyer = get_buyer_in_company(db, buyer_id, get_active_company(request).id)
            if not buyer or not can_access_buyer(buyer, current_user, db):
                response = RedirectResponse(url="/alerts", status_code=302)
                set_flash(response, "error", "Comprador no encontrado")
                return response
        else:
            buyer_name = (buyer_name or "").strip()
            if not buyer_name:
                response = RedirectResponse(url="/alerts", status_code=302)
                set_flash(response, "error", "El nombre del comprador es obligatorio")
                return response
            try:
                new_phone = phone_from_form(buyer_phone_country_code, buyer_phone_number, buyer_phone)
            except PhoneValidationError as error:
                response = RedirectResponse(url="/alerts", status_code=302)
                set_flash(response, "error", str(error))
                return response
            buyer = Buyer(
                name=buyer_name,
                phone=new_phone,
                email=(buyer_email or "").strip() or None,
                created_by=current_user.id,
                company_id=get_active_company(request).id
            )
            db.add(buyer)
            db.flush()

        # Crear o actualizar criterios
        criteria = buyer.search_criteria
        if criteria is None:
            criteria = BuyerSearchCriteria(buyer_id=buyer.id)
            db.add(criteria)

        criteria.agent_id = agent_id or None
        criteria.zones = zones or None
        criteria.cities = cities_sel or None
        criteria.property_type = property_type or None
        criteria.business_type = business_type or None
        criteria.min_price = to_decimal(min_price)
        criteria.max_price = to_decimal(max_price)
        criteria.min_bedrooms = to_int(min_bedrooms)
        criteria.max_bedrooms = to_int(max_bedrooms)
        criteria.min_bathrooms = to_int(min_bathrooms)
        criteria.min_m2 = to_decimal(min_m2)
        criteria.max_m2 = to_decimal(max_m2)
        criteria.notes = (notes or "").strip() or None
        criteria.updated_at = datetime.utcnow()

        db.commit()

        response = RedirectResponse(url=f"/buyers/{buyer.id}?tab=matches", status_code=302)
        set_flash(response, "success", f"Perfil de {buyer.name} guardado — propiedades compatibles:")
        return response

    except Exception:
        db.rollback()
        logger.exception("Error en create-with-criteria")
        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "error", "Ocurrió un error al guardar")
        return response


@router.post("/buyers/{buyer_id}/delete")
async def delete_buyer(
    buyer_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Eliminar un comprador (solo admin)"""

    current_user = request.state.user

    if not is_admin(current_user):
        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "error", "Solo administradores pueden eliminar compradores")
        return response

    buyer = get_buyer_in_company(db, buyer_id, get_active_company(request).id)

    if not buyer:
        response = RedirectResponse(url="/alerts?tab=buyers", status_code=302)
        set_flash(response, "error", "Comprador no encontrado")
        return response

    try:
        db.delete(buyer)
        db.commit()

        response = RedirectResponse(url="/alerts?tab=buyers", status_code=302)
        set_flash(response, "success", f"Comprador {buyer.name} eliminado correctamente")
        return response

    except Exception:
        db.rollback()
        logger.exception("Error eliminando comprador: buyer_id=%s", buyer_id)
        response = RedirectResponse(url="/alerts?tab=buyers", status_code=302)
        set_flash(response, "error", "Ocurrió un error al eliminar el comprador")
        return response


@router.get("/alerts/search-properties")
async def search_properties(
    request: Request,
    q: str = "",
    db: Session = Depends(get_db)
):
    """Autocompletado de propiedades para el formulario de nueva alerta.

    Devuelve como máximo PROPERTY_SEARCH_LIMIT coincidencias por título,
    dirección o ciudad. Admin y agentes: solo expone título, dirección,
    ciudad y agente (nombre e id, para preseleccionarlo en "Agente asignado"),
    nunca el propietario. Las propiedades sin captador solo las ve el admin.

    NOTA: debe declararse antes de /alerts/{alert_id}, o FastAPI intentaría
    resolver "search-properties" como un id y devolvería 422.
    """

    term = (q or "").strip()

    if len(term) < 2:
        return JSONResponse(content={"results": []})

    like = f"%{term}%"

    query = scope_properties(db.query(Property), get_active_company(request).id).filter(
        Property.status != PropertyStatus.ARCHIVED,
        Property.available_clause(),
        or_(
            Property.title.ilike(like),
            Property.address.ilike(like),
            Property.city.ilike(like),
        ),
    )
    # Propiedad sin captador: solo el admin, que puede elegir el agente (§4-7)
    if not is_admin(request.state.user):
        query = query.filter(Property.agent_id.isnot(None))

    properties = query.order_by(Property.title.asc()).limit(PROPERTY_SEARCH_LIMIT).all()

    results = [
        {
            "id": p.id,
            "title": p.title,
            "address": p.address or "",
            "city": p.city or "",
            "agent": p.agent.name if p.agent else "",
            "agent_id": p.agent_id,
        }
        for p in properties
    ]

    return JSONResponse(content={"results": results})


@router.get("/alerts/check-duplicate")
async def check_duplicate_alert(
    request: Request,
    buyer_id: int = Query(...),
    property_id: int = Query(...),
    db: Session = Depends(get_db)
):
    """Alertas ya registradas para el mismo comprador y propiedad.

    Lo consulta el formulario de nueva alerta en cuanto conoce ambos ids,
    para avisar antes de enviar. Devuelve las abiertas y las cerradas
    recientes por separado. Admin, y agentes sobre compradores a los que
    tienen acceso.

    NOTA: debe declararse antes de /alerts/{alert_id}.
    """

    current_user = request.state.user

    company_id = get_active_company(request).id

    buyer = get_buyer_in_company(db, buyer_id, company_id)
    if not buyer or not can_access_buyer(buyer, current_user, db):
        return JSONResponse(content={"open": [], "recent_closed": []})

    duplicates = find_duplicate_alerts(db, company_id, buyer_id, property_id)

    return JSONResponse(content=serialize_duplicates(db, duplicates))


@router.get("/alerts/check-buyer")
async def check_existing_buyer(
    request: Request,
    phone: str = "",
    email: str = "",
    db: Session = Depends(get_db)
):
    """Compradores ya registrados con el mismo teléfono o correo.

    Lo consulta el modo "Nuevo comprador" del formulario para evitar dar de
    alta dos veces a la misma persona. Al agente solo se le muestran
    coincidencias entre los compradores a los que tiene acceso, para no
    exponer los compradores de otros agentes.

    NOTA: debe declararse antes de /alerts/{alert_id}.
    """

    current_user = request.state.user

    buyers = [
        b for b in find_matching_buyers(db, get_active_company(request).id, phone=phone, email=email)
        if can_access_buyer(b, current_user, db)
    ]

    return JSONResponse(content={"results": [serialize_buyer(b) for b in buyers]})


@router.get("/alerts/{alert_id}", response_class=HTMLResponse)
async def alert_detail(
    alert_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Detalle de una alerta con historial de seguimientos"""

    current_user = request.state.user

    alert = get_alert_in_company(db, alert_id, get_active_company(request).id)

    if not alert:
        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "error", "Alerta no encontrada")
        return response

    # Verificar permisos: admin puede ver todo, agente solo sus alertas
    if not is_admin(current_user):
        agent = get_agent_from_user(current_user, db)
        if not agent or alert.agent_id != agent.id:
            response = RedirectResponse(url="/alerts", status_code=302)
            set_flash(response, "error", "No tienes permisos para ver esta alerta")
            return response

    # Obtener seguimientos ordenados por fecha
    follow_ups = db.query(AlertFollowUp).filter(
        AlertFollowUp.alert_id == alert_id
    ).order_by(AlertFollowUp.created_at.desc()).all()

    # Cargar nombres de usuarios que registraron cada seguimiento
    user_ids = {f.created_by for f in follow_ups if f.created_by}
    follow_up_users = {}
    if user_ids:
        users = db.query(User).filter(User.id.in_(user_ids)).all()
        follow_up_users = {u.id: u.full_name for u in users}

    # Auto-marcar como leída al abrir: solo el agente asignado, solo si está abierta
    if not is_admin(current_user) and not alert.read_at and alert.status in OPEN_ALERT_STATUSES:
        agent = get_agent_from_user(current_user, db)
        if agent and alert.agent_id == agent.id:
            alert.read_at = datetime.utcnow()
            if alert.status == AlertStatus.PENDING:
                alert.status = AlertStatus.IN_PROGRESS
            db.commit()

    # Cola secuencial: si alguna alerta anterior no tiene seguimiento, bloquear acciones
    alert_locked = is_alert_locked_for_user(alert, current_user, db)

    admin_view = is_admin(current_user)
    can_reassign = admin_view and alert.status in assignment.REASSIGNABLE_STATUSES

    return templates.TemplateResponse(
        request=request,
        name="alerts/detail.html",
        context={
            "request": request,
            "alert": alert,
            "follow_ups": follow_ups,
            "current_user": current_user,
            "alert_locked": alert_locked,
            "is_admin": admin_view,
            # Cerrar exige un seguimiento real (la nota de reasignación no cuenta)
            "can_complete": any(
                f.action_type not in FollowUpActionType.SYSTEM_ACTIONS for f in follow_ups
            ),
            "can_reassign": can_reassign,
            "assignable_groups": (
                assignment.assignable_agents(db, get_active_company(request).id) if can_reassign else []
            ),
            "FollowUpActionType": FollowUpActionType,
            "follow_up_labels": FollowUpActionType.labels(),
            "AlertStatus": AlertStatus,
            "stage_badge_color": FollowUpActionType.stage_badge_color,
            "follow_up_users": follow_up_users,
            "alert_type_labels": {
                AlertType.LEAD_INTERES: "Lead Interesado",
                AlertType.VISITA_SOLICITADA: "Visita Solicitada",
                AlertType.CAMBIO_PRECIO: "Cambio de Precio",
                AlertType.OTRO: "Otro",
            },
        }
    )


@router.post("/alerts/create")
async def create_alert(
    request: Request,
    property_id: int = Form(...),
    buyer_id: int = Form(None),
    buyer_name: str = Form(None),
    buyer_phone_country_code: str = Form(None),
    buyer_phone_number: str = Form(None),
    buyer_phone: str = Form(None),
    buyer_email: str = Form(None),
    source: str = Form(None),
    alert_type: str = Form(AlertType.LEAD_INTERES),
    message: str = Form(None),
    priority: str = Form(AlertPriority.NORMAL),
    business_type: str = Form(None),
    confirm_duplicate: str = Form(None),
    confirm_new_buyer: str = Form(None),
    agent_id: str = Form(None),
    assignment_reason: str = Form(None),
    db: Session = Depends(get_db)
):
    """Crear nueva alerta con comprador existente o nuevo (admin y agentes).

    Agente asignado (PLAN_ASIGNACION_ALERTAS.md §2.1): por defecto el captador
    de la propiedad. Solo el admin puede elegir otro (`agent_id`, de cualquier
    empresa; si no pertenece a la de la propiedad se le da acceso) con un
    motivo opcional; también puede crearla sobre una propiedad sin captador si
    elige agente. Un agente que manda otro `agent_id` recibe un error. El
    agente solo puede usar compradores a los que tiene acceso.

    Validación de duplicados:
    - Comprador existente: si ya hay una alerta abierta para ese comprador y
      esa propiedad, no se crea salvo que llegue ``confirm_duplicate``. Al
      confirmar, se deja constancia en el mensaje.
    - Comprador nuevo: si ya hay un comprador con el mismo teléfono o correo,
      no se crea salvo que llegue ``confirm_new_buyer``.
    El formulario avisa antes de enviar; esto es la red de seguridad.
    """

    current_user = request.state.user

    company_id = get_active_company(request).id

    # Operación obligatoria: solo Venta o Alquiler (no se guarda nada si falta).
    # El formulario rápido de la ficha del comprador vuelve a esa ficha.
    business_type = (business_type or "").strip()
    if not BusinessType.is_valid(business_type):
        back_url = f"/buyers/{buyer_id}" if buyer_id else "/alerts"
        response = RedirectResponse(url=back_url, status_code=302)
        set_flash(response, "error", "Selecciona la operación de la alerta: Venta o Alquiler")
        return response

    # Resolver comprador: existente o nuevo
    buyer = None

    if buyer_id:
        buyer = get_buyer_in_company(db, buyer_id, company_id)
        if not buyer or not can_access_buyer(buyer, current_user, db):
            response = RedirectResponse(url="/alerts", status_code=302)
            set_flash(response, "error", "Comprador no encontrado")
            return response
    else:
        buyer_name = (buyer_name or "").strip()
        if not buyer_name:
            response = RedirectResponse(url="/alerts", status_code=302)
            set_flash(response, "error", "El nombre del comprador es obligatorio")
            return response

        # Teléfono canónico con indicativo (PLAN_TELEFONO_COMPRADOR.md); `buyer_phone`
        # es el campo antiguo de texto libre, aceptado si llega solo
        try:
            new_phone = phone_from_form(buyer_phone_country_code, buyer_phone_number, buyer_phone)
        except PhoneValidationError as error:
            response = RedirectResponse(url="/alerts", status_code=302)
            set_flash(response, "error", str(error))
            return response

        if not confirm_new_buyer:
            # Mismo criterio que /alerts/check-buyer: al agente solo se le
            # avisa de coincidencias con compradores a los que tiene acceso
            matches = [
                b for b in find_matching_buyers(db, company_id, phone=new_phone, email=buyer_email)
                if can_access_buyer(b, current_user, db)
            ]
            if matches:
                existing = matches[0]
                contact = phone_display(existing.phone) or existing.email or ""
                response = RedirectResponse(url="/alerts", status_code=302)
                set_flash(
                    response,
                    "warning",
                    f"Ya existe un comprador con ese teléfono o correo: {existing.name} ({contact}). "
                    "Selecciónalo como comprador existente o confirma que es otra persona."
                )
                return response

        buyer = Buyer(
            name=buyer_name,
            phone=new_phone,
            email=(buyer_email or "").strip() or None,
            created_by=current_user.id,
            company_id=company_id
        )
        db.add(buyer)
        db.flush()  # obtener buyer.id antes del commit

    # Obtener la propiedad y su agente (solo de la empresa activa)
    property_item = get_property_in_company(db, property_id, company_id)

    if not property_item:
        db.rollback()
        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "error", "Propiedad no encontrada")
        return response

    if not property_item.is_available:
        db.rollback()
        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "error", "La propiedad está marcada como No disponible")
        return response

    admin_view = is_admin(current_user)
    try:
        assignee = assignment.resolve_assignee(
            is_admin_user=admin_view,
            requested_agent_id=agent_id,
            owner_agent_id=property_item.agent_id,
            lookup_any_agent=assignment.lookup_any_agent(db),
        )
    except AlertAssignmentError as error:
        db.rollback()
        back_url = f"/buyers/{buyer_id}" if buyer_id else "/alerts"
        response = RedirectResponse(url=back_url, status_code=302)
        set_flash(response, "error", str(error))
        return response

    # Duplicados: solo aplica a compradores existentes (uno nuevo no tiene alertas)
    if buyer_id:
        open_duplicates = find_duplicate_alerts(db, company_id, buyer.id, property_id)["open"]
        if open_duplicates:
            existing = open_duplicates[0]
            if not confirm_duplicate:
                db.rollback()
                fecha = existing.created_at.strftime("%d/%m/%Y") if existing.created_at else ""
                response = RedirectResponse(url="/alerts", status_code=302)
                set_flash(
                    response,
                    "warning",
                    f"Ya existe una alerta abierta (#{existing.id}, {fecha}) para {buyer.name} "
                    "en esta propiedad. No se ha creado otra. Si quieres repetirla, "
                    "confírmalo en el formulario."
                )
                return response
            message = append_note(message, duplicate_note(existing))

    try:
        now = datetime.utcnow()
        alert = PropertyAlert(
            property=property_item,
            buyer_id=buyer.id,
            lead_name=buyer.name,
            lead_phone=buyer.phone,
            lead_email=buyer.email,
            source=source,
            alert_type=alert_type,
            message=message,
            priority=priority,
            business_type=business_type or None,
            status=AlertStatus.PENDING,
            created_at=now,
            created_by=current_user.id
        )

        db.add(alert)
        result = assignment.assign(
            db,
            alert,
            assignee,
            current_user,
            assignment_reason if admin_view else None,
            is_new=True,
            now=now,
        )
        db.commit()

        response = RedirectResponse(url="/alerts", status_code=302)
        own_agent = None if admin_view else get_agent_from_user(current_user, db)
        if own_agent and assignee.id != own_agent.id:
            # La alerta va al agente de la propiedad: no aparecerá en la lista de quien la creó
            set_flash(
                response,
                "success",
                f"Alerta creada para {buyer.name} y asignada a {assignee.name}, "
                "agente de la propiedad"
            )
        elif admin_view:
            message = f"Alerta creada para {buyer.name} y asignada a {assignee.name}"
            if result.granted_company is not None:
                message += f". {assignee.name} ahora tiene acceso a {result.granted_company.name}"
            set_flash(response, "success", message)
        else:
            set_flash(response, "success", f"Alerta de comprador creada para {buyer.name}")
        return response

    except Exception:
        db.rollback()
        logger.exception("Error creando alerta: property_id=%s", property_id)
        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "error", "Ocurrió un error al crear la alerta")
        return response


def _safe_back_url(next_url: Optional[str], default: str) -> str:
    """Solo rutas internas de alertas ("/alerts..."), para volver al listado o al detalle."""
    if next_url and next_url.startswith("/alerts") and "//" not in next_url and "\\" not in next_url:
        return next_url
    return default


@router.post("/alerts/{alert_id}/reassign")
async def reassign_alert(
    alert_id: int,
    request: Request,
    agent_id: str = Form(None),
    assignment_reason: str = Form(None),
    next_url: str = Form(None, alias="next"),
    db: Session = Depends(get_db)
):
    """Reasigna una alerta abierta a otro agente (solo admin).

    PLAN_ASIGNACION_ALERTAS.md §2.2: cualquier agente de cualquier empresa (si
    no pertenece a la de la propiedad se le da acceso), motivo opcional. La
    alerta vuelve a pendiente y sin leer, conserva sus seguimientos, queda en
    el historial con una nota automática y el nuevo agente recibe un aviso
    in-app. Vuelve a `next` (listado o detalle).
    """
    current_user = request.state.user
    detail_url = f"/alerts/{alert_id}"

    if not is_admin(current_user):
        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "error", "Solo un administrador puede reasignar alertas")
        return response

    alert = get_alert_in_company(db, alert_id, get_active_company(request).id)
    if not alert:
        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "error", "Alerta no encontrada")
        return response

    back_url = _safe_back_url(next_url, detail_url)

    agent_id_int = assignment._to_int(agent_id)
    agent = assignment.lookup_any_agent(db)(agent_id_int) if agent_id_int is not None else None

    try:
        assignment.validate_reassignment(alert, agent, is_admin_user=True)
    except AlertAssignmentError as error:
        response = RedirectResponse(url=back_url, status_code=302)
        set_flash(response, "error", str(error))
        return response

    try:
        result = assignment.assign(db, alert, agent, current_user, assignment_reason, is_new=False)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Error reasignando alerta: alert_id=%s", alert_id)
        response = RedirectResponse(url=back_url, status_code=302)
        set_flash(response, "error", "Ocurrió un error al reasignar la alerta")
        return response

    previous_name = result.previous_agent.name if result.previous_agent is not None else "sin agente"
    message = f"Alerta de {alert.lead_name} reasignada de {previous_name} a {agent.name}"
    if result.granted_company is not None:
        message += f". {agent.name} ahora tiene acceso a {result.granted_company.name}"
    response = RedirectResponse(url=back_url, status_code=302)
    set_flash(response, "success", message)
    return response


@router.post("/alerts/{alert_id}/mark-read")
async def mark_alert_read(
    alert_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Marcar alerta como leída"""

    current_user = request.state.user

    alert = get_alert_in_company(db, alert_id, get_active_company(request).id)

    if not alert:
        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "error", "Alerta no encontrada")
        return response

    # Verificar permisos
    if not is_admin(current_user):
        agent = get_agent_from_user(current_user, db)
        if not agent or alert.agent_id != agent.id:
            response = RedirectResponse(url="/alerts", status_code=302)
            set_flash(response, "error", "No tienes permisos para esta alerta")
            return response

    # Cola secuencial: la alerta anterior debe tener al menos un seguimiento
    if is_alert_locked_for_user(alert, current_user, db):
        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "error", "Registra un seguimiento en la alerta anterior para desbloquear esta")
        return response

    try:
        if not alert.read_at:
            alert.read_at = datetime.utcnow()

        if alert.status == AlertStatus.PENDING:
            alert.status = AlertStatus.IN_PROGRESS

        db.commit()

        response = RedirectResponse(url=f"/alerts/{alert_id}", status_code=302)
        set_flash(response, "success", "Alerta marcada como leída")
        return response

    except Exception:
        db.rollback()
        logger.exception("Error marcando alerta como leída: alert_id=%s", alert_id)
        response = RedirectResponse(url=f"/alerts/{alert_id}", status_code=302)
        set_flash(response, "error", "Ocurrió un error")
        return response


@router.post("/alerts/{alert_id}/follow-up")
async def add_follow_up(
    alert_id: int,
    request: Request,
    action_type: str = Form(...),
    notes: str = Form(None),
    next_action_date: str = Form(None),
    db: Session = Depends(get_db)
):
    """Agregar seguimiento a una alerta"""

    current_user = request.state.user

    alert = get_alert_in_company(db, alert_id, get_active_company(request).id)

    if not alert:
        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "error", "Alerta no encontrada")
        return response

    # Verificar permisos
    if not is_admin(current_user):
        agent = get_agent_from_user(current_user, db)
        if not agent or alert.agent_id != agent.id:
            response = RedirectResponse(url="/alerts", status_code=302)
            set_flash(response, "error", "No tienes permisos para esta alerta")
            return response

    # Cola secuencial: solo se puede trabajar la alerta activa
    if is_alert_locked_for_user(alert, current_user, db):
        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "error", "Debes completar tu alerta activa antes de atender esta")
        return response

    if not FollowUpActionType.is_valid(action_type):
        response = RedirectResponse(url=f"/alerts/{alert_id}", status_code=302)
        set_flash(response, "error", "Tipo de acción no válido")
        return response

    # Notas obligatorias al cerrar
    if action_type in FollowUpActionType.CLOSING_STAGES and not (notes or "").strip():
        response = RedirectResponse(url=f"/alerts/{alert_id}", status_code=302)
        set_flash(response, "error", "Debes escribir una nota al cerrar la alerta")
        return response

    try:
        # Parsear fecha si existe
        next_action_date_parsed = None
        if next_action_date:
            try:
                next_action_date_parsed = datetime.fromisoformat(next_action_date)
            except ValueError:
                pass

        follow_up = AlertFollowUp(
            alert_id=alert_id,
            action_type=action_type,
            notes=notes,
            next_action_date=next_action_date_parsed,
            created_by=current_user.id
        )

        db.add(follow_up)

        # Actualizar estado de alerta
        if alert.status == AlertStatus.PENDING:
            alert.status = AlertStatus.IN_PROGRESS

        # Etapas de cierre: completan la alerta automáticamente
        if action_type in FollowUpActionType.CLOSING_STAGES:
            alert.status = AlertStatus.COMPLETED
            alert.completed_at = datetime.utcnow()
            db.commit()
            closing_labels = {
                FollowUpActionType.CERRADO: "Alerta cerrada con éxito",
                FollowUpActionType.SIN_INTERES: "Alerta cerrada: comprador sin interés",
                FollowUpActionType.SIN_SOLVENCIA_ECONOMICA: "Alerta cerrada: sin solvencia económica",
                FollowUpActionType.NO_APTO_PROPIETARIO: "Alerta cerrada: no apto para el propietario",
            }
            msg = closing_labels.get(action_type, "Alerta cerrada correctamente")
            response = RedirectResponse(url="/alerts", status_code=302)
            set_flash(response, "success", msg)
            return response

        db.commit()

        response = RedirectResponse(url=f"/alerts/{alert_id}", status_code=302)
        set_flash(response, "success", "Seguimiento agregado correctamente")
        return response

    except Exception:
        db.rollback()
        logger.exception("Error agregando seguimiento: alert_id=%s", alert_id)
        response = RedirectResponse(url=f"/alerts/{alert_id}", status_code=302)
        set_flash(response, "error", "Ocurrió un error al agregar el seguimiento")
        return response


@router.post("/alerts/{alert_id}/register-contact")
async def register_contact_on_alert(
    alert_id: int,
    request: Request,
    source: str = Form(None),
    notes: str = Form(None),
    priority: str = Form(None),
    db: Session = Depends(get_db)
):
    """Registra un nuevo contacto del comprador sobre una alerta ya abierta.

    Es la alternativa a crear una alerta duplicada: deja constancia en el
    mensaje de la alerta (fecha, origen, quién lo registró), la vuelve a
    marcar como no leída para el agente y sube la prioridad si el nuevo
    contacto llega con una más alta. No crea seguimientos, así que no
    altera la cola secuencial ni la etapa del comprador. Solo admin.
    """

    current_user = request.state.user

    if not is_admin(current_user):
        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "error", "Solo administradores pueden registrar contactos")
        return response

    alert = get_alert_in_company(db, alert_id, get_active_company(request).id)

    if not alert:
        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "error", "Alerta no encontrada")
        return response

    if alert.status not in OPEN_ALERT_STATUSES:
        response = RedirectResponse(url=f"/alerts/{alert_id}", status_code=302)
        set_flash(response, "error", "La alerta está cerrada; reactívala o crea una nueva")
        return response

    try:
        alert.message = append_note(
            alert.message,
            new_contact_note(source, current_user.full_name, notes),
        )
        if not alert.source and source and source.strip():
            alert.source = source.strip()
        if priority == AlertPriority.ALTA and alert.priority != AlertPriority.ALTA:
            alert.priority = AlertPriority.ALTA
        alert.read_at = None  # el agente la verá como nueva

        db.commit()

        response = RedirectResponse(url=f"/alerts/{alert_id}", status_code=302)
        set_flash(response, "success", "Nuevo contacto registrado en la alerta existente")
        return response

    except Exception:
        db.rollback()
        logger.exception("Error registrando contacto: alert_id=%s", alert_id)
        response = RedirectResponse(url=f"/alerts/{alert_id}", status_code=302)
        set_flash(response, "error", "Ocurrió un error al registrar el contacto")
        return response


@router.post("/alerts/{alert_id}/complete")
async def complete_alert(
    alert_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Completar/cerrar una alerta"""

    current_user = request.state.user

    alert = get_alert_in_company(db, alert_id, get_active_company(request).id)

    if not alert:
        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "error", "Alerta no encontrada")
        return response

    # Verificar permisos
    if not is_admin(current_user):
        agent = get_agent_from_user(current_user, db)
        if not agent or alert.agent_id != agent.id:
            response = RedirectResponse(url="/alerts", status_code=302)
            set_flash(response, "error", "No tienes permisos para esta alerta")
            return response

    # Cola secuencial: solo se puede completar la alerta activa
    if is_alert_locked_for_user(alert, current_user, db):
        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "error", "Debes completar tu alerta activa antes de atender esta")
        return response

    # No se puede cerrar una alerta sin al menos un seguimiento registrado
    # (la nota automática de reasignación no cuenta)
    follow_ups_count = _real_follow_ups(db, alert_id).count()

    if follow_ups_count == 0:
        response = RedirectResponse(url=f"/alerts/{alert_id}", status_code=302)
        set_flash(
            response,
            "error",
            "Debes registrar al menos un seguimiento antes de cerrar la alerta"
        )
        return response

    try:
        alert.status = AlertStatus.COMPLETED
        alert.completed_at = datetime.utcnow()

        db.commit()

        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "success", "Alerta completada correctamente")
        return response

    except Exception:
        db.rollback()
        logger.exception("Error completando alerta: alert_id=%s", alert_id)
        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "error", "Ocurrió un error al completar la alerta")
        return response


@router.post("/alerts/{alert_id}/reactivate")
async def reactivate_alert(
    alert_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Reactivar una alerta cerrada o cancelada (solo admin)"""

    current_user = request.state.user

    if not is_admin(current_user):
        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "error", "Solo administradores pueden reactivar alertas")
        return response

    alert = get_alert_in_company(db, alert_id, get_active_company(request).id)

    if not alert:
        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "error", "Alerta no encontrada")
        return response

    if alert.status in OPEN_ALERT_STATUSES:
        response = RedirectResponse(url=f"/alerts/{alert_id}", status_code=302)
        set_flash(response, "error", "La alerta ya está activa")
        return response

    try:
        # Vuelve a la cola del agente como "en proceso" si ya fue leída
        alert.status = (
            AlertStatus.IN_PROGRESS if alert.read_at else AlertStatus.PENDING
        )
        alert.completed_at = None

        db.commit()

        response = RedirectResponse(url=f"/alerts/{alert_id}", status_code=302)
        set_flash(response, "success", "Alerta reactivada correctamente")
        return response

    except Exception:
        db.rollback()
        logger.exception("Error reactivando alerta: alert_id=%s", alert_id)
        response = RedirectResponse(url=f"/alerts/{alert_id}", status_code=302)
        set_flash(response, "error", "Ocurrió un error al reactivar la alerta")
        return response


@router.get("/api/alerts/unread-count")
async def get_unread_count(
    request: Request,
    db: Session = Depends(get_db)
):
    """API endpoint para obtener contador de alertas no leídas (para badge)"""

    # Obtener usuario y empresa desde las cookies (las rutas API no pasan por AuthMiddleware)
    from app.web.dependencies.company import get_api_user, resolve_company_for_api

    current_user = get_api_user(request, db)
    if not current_user:
        return JSONResponse(content={"unread_count": 0})

    company = resolve_company_for_api(request, current_user, db)
    if company is None:
        return JSONResponse(content={"unread_count": 0})

    base_query = scope_alerts(
        db.query(PropertyAlert).filter(
            PropertyAlert.status.in_([AlertStatus.PENDING, AlertStatus.IN_PROGRESS])
        ),
        company.id
    )

    # Si es agente, filtrar solo sus alertas
    if not is_admin(current_user):
        agent = get_agent_from_user(current_user, db)
        if agent:
            base_query = base_query.filter(PropertyAlert.agent_id == agent.id)
        else:
            return JSONResponse(content={"unread_count": 0})

    unread_count = base_query.count()

    return JSONResponse(content={"unread_count": unread_count})


@router.post("/alerts/{alert_id}/delete")
async def delete_alert(
    alert_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Eliminar una alerta (solo admin)"""

    current_user = request.state.user

    if not is_admin(current_user):
        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "error", "Solo administradores pueden eliminar alertas")
        return response

    alert = get_alert_in_company(db, alert_id, get_active_company(request).id)

    if not alert:
        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "error", "Alerta no encontrada")
        return response

    try:
        # Los seguimientos se eliminan automáticamente por cascade
        db.delete(alert)
        db.commit()

        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "success", f"Alerta de {alert.lead_name} eliminada correctamente")
        return response

    except Exception:
        db.rollback()
        logger.exception("Error eliminando alerta: alert_id=%s", alert_id)
        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "error", "Ocurrió un error al eliminar la alerta")
        return response


# ---------------------------------------------------------------------------
# Detalle del comprador y perfil de búsqueda
# ---------------------------------------------------------------------------

def _build_matching_properties(criteria: BuyerSearchCriteria, db: Session, company_id: int):
    """Filtra propiedades activas y disponibles de la empresa que cumplen los criterios."""
    query = scope_properties(
        db.query(Property).filter(
            Property.status == PropertyStatus.ACTIVE,
            Property.available_clause(),
            Property.agent_id.isnot(None),
        ),
        company_id
    )

    if criteria.zones:
        query = query.filter(Property.zona.in_(criteria.zones))
    if criteria.cities:
        query = query.filter(Property.city.in_(criteria.cities))
    if criteria.property_type:
        query = query.filter(Property.property_type == criteria.property_type)
    if criteria.business_type:
        query = query.filter(Property.business_type == criteria.business_type)
    if criteria.min_price is not None:
        query = query.filter(Property.price >= criteria.min_price)
    if criteria.max_price is not None:
        query = query.filter(Property.price <= criteria.max_price)
    if criteria.min_bedrooms is not None:
        query = query.filter(Property.num_dormitorios >= criteria.min_bedrooms)
    if criteria.max_bedrooms is not None:
        query = query.filter(Property.num_dormitorios <= criteria.max_bedrooms)
    if criteria.min_bathrooms is not None:
        query = query.filter(Property.num_banos_aseos >= criteria.min_bathrooms)
    if criteria.min_m2 is not None:
        query = query.filter(Property.m2_utiles >= criteria.min_m2)
    if criteria.max_m2 is not None:
        query = query.filter(Property.m2_utiles <= criteria.max_m2)

    return query.order_by(Property.price.asc()).all()


@router.get("/buyers/{buyer_id}", response_class=HTMLResponse)
async def buyer_detail(
    buyer_id: int,
    request: Request,
    tab: str = "criteria",
    db: Session = Depends(get_db)
):
    """Detalle del comprador: perfil de búsqueda, matches y alertas."""

    current_user = request.state.user

    buyer = get_buyer_in_company(db, buyer_id, get_active_company(request).id)
    if not buyer:
        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "error", "Comprador no encontrado")
        return response

    # Agente solo puede ver compradores relacionados con él
    if not can_access_buyer(buyer, current_user, db):
        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "error", "No tienes acceso a este comprador")
        return response

    company = get_active_company(request)

    criteria = buyer.search_criteria

    # Propiedades que hacen match (solo si hay criterios definidos)
    matching_properties = []
    if criteria:
        matching_properties = _build_matching_properties(criteria, db, company.id)

    # Valores disponibles en la BD para los selectores
    filter_values = _property_filter_values(db, company.id)
    zones = filter_values["zones"]
    cities = filter_values["cities"]
    property_types = filter_values["property_types"]
    business_types = filter_values["business_types"]

    agents = scope_agents(db.query(Agent), company.id).order_by(Agent.name.asc()).all()

    # "Agente asignado" del formulario rápido: solo el admin elige (§4-2)
    assignable_groups = assignment.assignable_agents(db, company.id) if is_admin(current_user) else []

    # Para el agente: su propia ficha (las propiedades de otros agentes se
    # muestran como recomendadas pero sin enlace al detalle, que incluye
    # datos del propietario).
    own_agent = None if is_admin(current_user) else get_agent_from_user(current_user, db)

    buyer_alerts = (
        db.query(PropertyAlert)
        .filter(PropertyAlert.buyer_id == buyer_id)
        .order_by(PropertyAlert.created_at.desc())
        .all()
    )

    return templates.TemplateResponse(
        request=request,
        name="buyers/detail.html",
        context={
            "request": request,
            "current_user": current_user,
            "is_admin": is_admin(current_user),
            "buyer": buyer,
            "criteria": criteria,
            "matching_properties": matching_properties,
            "own_agent": own_agent,
            "buyer_alerts": buyer_alerts,
            "agents": agents,
            "assignable_groups": assignable_groups,
            "zones": zones,
            "cities": cities,
            "property_types": property_types,
            "business_types": business_types,
            "tab": tab,
            "AlertStatus": AlertStatus,
            "AlertPriority": AlertPriority,
        }
    )


@router.post("/buyers/{buyer_id}/update-contact")
async def update_buyer_contact(
    buyer_id: int,
    request: Request,
    name: str = Form(...),
    phone_country_code: str = Form(None),
    phone_number: str = Form(None),
    phone: str = Form(None),
    email: str = Form(None),
    db: Session = Depends(get_db)
):
    """Actualiza nombre, teléfono y email del comprador. Accesible para admin y agentes asignados.

    Teléfono: indicativo + número (PLAN_TELEFONO_COMPRADOR.md). Si llega igual
    que lo que pintó el formulario (`split_phone` del guardado), se conserva el
    valor guardado tal cual: editar solo el correo no reescribe un teléfono
    antiguo. `phone` es el campo antiguo, aceptado si llega solo."""
    current_user = request.state.user

    buyer = get_buyer_in_company(db, buyer_id, get_active_company(request).id)
    if not buyer:
        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "error", "Comprador no encontrado")
        return response

    if not can_access_buyer(buyer, current_user, db):
        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "error", "No tienes acceso a este comprador")
        return response

    unchanged = (
        buyer.phone
        and phone_number is not None
        and (valid_country_code(phone_country_code), phone_number.strip()) == split_phone(buyer.phone)
    )
    if not unchanged:
        try:
            new_phone = phone_from_form(phone_country_code, phone_number, phone)
        except PhoneValidationError as error:
            response = RedirectResponse(url=f"/buyers/{buyer_id}", status_code=303)
            set_flash(response, "error", str(error))
            return response
        buyer.phone = new_phone

    buyer.name = name.strip()
    buyer.email = email.strip() if email and email.strip() else None
    db.commit()

    response = RedirectResponse(url=f"/buyers/{buyer_id}", status_code=303)
    set_flash(response, "success", "Datos del comprador actualizados correctamente")
    return response


@router.post("/buyers/{buyer_id}/search-criteria")
async def save_search_criteria(
    buyer_id: int,
    request: Request,
    agent_id: int = Form(None),
    property_type: str = Form(None),
    business_type: str = Form(None),
    min_price: str = Form(None),
    max_price: str = Form(None),
    min_bedrooms: str = Form(None),
    max_bedrooms: str = Form(None),
    min_bathrooms: str = Form(None),
    min_m2: str = Form(None),
    max_m2: str = Form(None),
    notes: str = Form(None),
    db: Session = Depends(get_db)
):
    """Crear o actualizar el perfil de búsqueda de un comprador.

    Admin y agentes con acceso al comprador. Para el agente, el agente
    responsable del perfil es siempre su propia ficha."""

    current_user = request.state.user

    buyer = get_buyer_in_company(db, buyer_id, get_active_company(request).id)
    if not buyer:
        response = RedirectResponse(url="/alerts?tab=buyers", status_code=302)
        set_flash(response, "error", "Comprador no encontrado")
        return response

    if not can_access_buyer(buyer, current_user, db):
        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "error", "No tienes acceso a este comprador")
        return response

    if not is_admin(current_user):
        own_agent = get_agent_from_user(current_user, db)
        if not own_agent:
            response = RedirectResponse(url=f"/buyers/{buyer_id}", status_code=302)
            set_flash(response, "error", "Tu usuario no tiene ficha de agente asociada")
            return response
        agent_id = own_agent.id

    # Operación obligatoria: solo Venta o Alquiler (no se guarda nada si falta)
    business_type = (business_type or "").strip()
    if not BusinessType.is_valid(business_type):
        response = RedirectResponse(url=f"/buyers/{buyer_id}?tab=criteria", status_code=302)
        set_flash(response, "error", "Selecciona la operación del comprador: Venta o Alquiler")
        return response

    # Zonas y ciudades vienen como lista de checkboxes
    form_data = await request.form()
    zones = form_data.getlist("zones")
    cities_sel = form_data.getlist("cities")

    def to_int(v):
        try:
            return int(v) if v and str(v).strip() else None
        except (ValueError, TypeError):
            return None

    def to_decimal(v):
        try:
            return float(v) if v and str(v).strip() else None
        except (ValueError, TypeError):
            return None

    try:
        criteria = buyer.search_criteria
        if criteria is None:
            criteria = BuyerSearchCriteria(buyer_id=buyer_id)
            db.add(criteria)

        criteria.agent_id = agent_id or None
        criteria.zones = zones or None
        criteria.cities = cities_sel or None
        criteria.property_type = property_type or None
        criteria.business_type = business_type or None
        criteria.min_price = to_decimal(min_price)
        criteria.max_price = to_decimal(max_price)
        criteria.min_bedrooms = to_int(min_bedrooms)
        criteria.max_bedrooms = to_int(max_bedrooms)
        criteria.min_bathrooms = to_int(min_bathrooms)
        criteria.min_m2 = to_decimal(min_m2)
        criteria.max_m2 = to_decimal(max_m2)
        criteria.notes = (notes or "").strip() or None
        criteria.updated_at = datetime.utcnow()

        db.commit()

        response = RedirectResponse(url=f"/buyers/{buyer_id}?tab=matches", status_code=302)
        set_flash(response, "success", "Perfil de búsqueda guardado")
        return response

    except Exception:
        db.rollback()
        logger.exception("Error guardando criterios: buyer_id=%s", buyer_id)
        response = RedirectResponse(url=f"/buyers/{buyer_id}", status_code=302)
        set_flash(response, "error", "Ocurrió un error al guardar el perfil")
        return response
