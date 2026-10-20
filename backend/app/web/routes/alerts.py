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
from app.core.constants import AlertOrigin
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
    find_open_search_alerts,
    serialize_duplicates,
    serialize_search_duplicates,
    serialize_buyer,
    duplicate_note,
    linked_duplicate_note,
    search_duplicate_note,
    new_contact_note,
    append_note,
)
from app.services import buyer_matching
from app.services import alert_assignment_service as assignment
from app.services import alert_view
from app.services import buyer_attention_service
from app.services import notification_service
from app.services.alert_assignment_service import AlertAssignmentError
# Cola secuencial y ventana de asignación (PLAN_ALERTA_COMO_NUEVA.md): viven en
# el servicio para que el Inicio las reutilice; se reexportan con su nombre de
# siempre.
from app.services.alert_view import OPEN_ALERT_STATUSES
from app.services.alert_view import agent_open_alerts_ordered as _get_agent_open_alerts_ordered  # noqa: F401
from app.services.alert_view import get_locked_alert_ids
from app.web.utils.flash import set_flash
from app.web.dependencies.auth import is_admin, get_agent_from_user, require_admin_role
from app.web.dependencies.company import get_active_company


router = APIRouter()
logger = logging.getLogger(__name__)


# Aviso al agente que intenta abrir una alerta bloqueada por la cola
# (PLAN_ALERTA_COMO_NUEVA.md, decisión cerrada: texto exacto)
ALERT_LOCKED_MESSAGE = "Esta alerta está en tu cola. Gestiona primero las anteriores para verla."

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


def _property_filter_values(db: Session, company_id: int,
                            criteria: Optional[BuyerSearchCriteria] = None) -> dict:
    """Opciones del formulario del perfil a partir de las propiedades de la empresa.

    - `location`: cascada País → Provincia → Población → Zona
      (PLAN_PERFIL_UBICACION.md): el árbol de `buyer_matching.geo_options`
      (una consulta; va a la página como JSON para el JS) y el estado inicial
      para `criteria` (`buyer_matching.geo_choices`, lo que pinta el servidor).
    - `property_types` y `business_types`: valores distintos de las propiedades.
    """
    def distinct_values(column):
        query = scope_properties(db.query(column), company_id).filter(column.isnot(None))
        return [r[0] for r in query.distinct().order_by(column.asc()).all()]

    tree = buyer_matching.geo_options(db, company_id)
    return {
        "location": {"tree": tree, **buyer_matching.geo_choices(tree, criteria)},
        "property_types": distinct_values(Property.property_type),
        "business_types": distinct_values(Property.business_type),
    }


def _page_profiles(db: Session, alerts, with_missing: bool = False):
    """Perfiles de los compradores de la página: (resúmenes, alertas sin perfil).

    - Resúmenes: {alert.id: resumen del perfil} para las alertas sin
      propiedad (búsquedas generales), en la columna Propiedad.
    - Sin perfil (solo con `with_missing`, para el admin;
      PLAN_PERFIL_OBLIGATORIO.md): ids de las alertas abiertas con comprador
      cuyo perfil no está completo (`buyer_matching.profile_is_complete`).

    El perfil es uno por comprador; se cargan todos los de la página en una
    sola consulta (sin N+1).
    """
    buyer_ids = {
        a.buyer_id for a in alerts
        if a.buyer_id and (a.property_id is None or (with_missing and a.status in OPEN_ALERT_STATUSES))
    }
    if not buyer_ids:
        return {}, set()
    criteria_by_buyer = {
        c.buyer_id: c
        for c in db.query(BuyerSearchCriteria).filter(BuyerSearchCriteria.buyer_id.in_(buyer_ids))
    }
    summaries = {}
    missing = set()
    for alert in alerts:
        if not alert.buyer_id:
            continue
        criteria = criteria_by_buyer.get(alert.buyer_id)
        if alert.property_id is None and criteria is not None:
            summary = buyer_matching.criteria_summary(criteria)
            if summary:
                summaries[alert.id] = summary
        if (with_missing and alert.status in OPEN_ALERT_STATUSES
                and not buyer_matching.profile_is_complete(criteria)):
            missing.add(alert.id)
    return summaries, missing


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


def _real_follow_ups(db: Session, alert_id: int, since=None):
    """Seguimientos registrados por un agente o admin (sin las notas del sistema).

    La nota automática de reasignación no cuenta como gestión: no desbloquea
    la cola ni permite cerrar la alerta. Con `since` (normalmente
    `alert_view.assignment_start(alert)`), solo los registrados desde entonces.
    """
    return db.query(AlertFollowUp).filter(
        AlertFollowUp.alert_id == alert_id,
        alert_view.real_follow_ups_clause(since),
    )


def is_alert_locked_for_user(alert: PropertyAlert, current_user, db: Session) -> bool:
    """True si la alerta está bloqueada para este usuario.

    El admin nunca está bloqueado. Un agente está bloqueado si alguna alerta
    anterior en su cola no tiene seguimientos reales desde su asignación
    (PLAN_ALERTA_COMO_NUEVA.md). Las alertas cerradas no cuentan.
    """
    if is_admin(current_user):
        return False

    if alert.status not in OPEN_ALERT_STATUSES:
        return False

    agent = get_agent_from_user(current_user, db)
    if not agent:
        return False

    # La cola se evalúa dentro de la empresa de la propia alerta (columna
    # propia: una búsqueda general puede no tener propiedad). Misma regla que
    # el listado: bloqueada si alguna anterior de la cola no tiene seguimiento
    # desde su asignación.
    return alert.id in get_locked_alert_ids(agent.id, db, alert.company_id)


# Asociar o cambiar la propiedad exige el perfil completo (PLAN_PERFIL_OBLIGATORIO.md)
PROFILE_REQUIRED_MESSAGE = "Registra primero el perfil del comprador"


def _search_link_denied(alert: PropertyAlert, current_user, db: Session,
                        require_profile: bool = False) -> Optional[str]:
    """Motivo por el que el usuario NO puede trabajar la búsqueda del comprador, o None.

    Perfil y Propuesta (asociar o cambiar propiedad) de cualquier alerta: solo
    abiertas, solo el agente asignado o el admin, y nunca si la alerta está
    bloqueada por la cola del agente. Desde PLAN_PERFIL_OBLIGATORIO.md el
    origen ya no cuenta (una alerta con referencia también puede cambiar de
    propiedad) y, con `require_profile` (asociar propiedad, buscador de la
    Propuesta), el comprador debe tener el perfil completo.
    """
    if alert.status not in OPEN_ALERT_STATUSES:
        return "La alerta está cerrada"
    if not is_admin(current_user):
        agent = get_agent_from_user(current_user, db)
        if not agent or alert.agent_id != agent.id:
            return "No tienes permisos para esta alerta"
        if is_alert_locked_for_user(alert, current_user, db):
            return ALERT_LOCKED_MESSAGE
    if require_profile and not buyer_matching.profile_is_complete(_alert_criteria(alert)):
        return PROFILE_REQUIRED_MESSAGE
    return None


def _alert_criteria(alert: PropertyAlert) -> Optional[BuyerSearchCriteria]:
    """Perfil de búsqueda del comprador de la alerta (uno por comprador), o None."""
    return alert.buyer.search_criteria if alert.buyer is not None else None


def _profile_applies(alert: PropertyAlert) -> bool:
    """¿Se le exige perfil a esta alerta? Solo si tiene comprador.

    El perfil se guarda en el comprador; una alerta antigua sin comprador
    (anterior a la tabla de compradores) no tiene dónde guardarlo y queda
    fuera del requisito para no dejarla sin poder avanzar ni cerrarse.
    """
    return alert.buyer is not None


# Campos del formulario del perfil (components/search_profile_form.html), sin
# las listas de poblaciones y zonas ni los imprescindibles, que van aparte.
# País, provincia y operación (PLAN_PERFIL_UBICACION.md) se leen del formulario.
PROFILE_TEXT_FIELDS = ("property_type", "min_price", "max_price", "min_bedrooms", "max_bedrooms", "min_bathrooms")
PROFILE_LOCATION_FIELDS = ("country", "province")


def _profile_values(form_data, notes_field: str = "notes", **overrides) -> dict:
    """Valores crudos del perfil enviados en un formulario.

    `notes_field`: en el modal de seguimiento los imprescindibles llegan como
    `profile_notes` (allí `notes` es la nota del seguimiento). `overrides`
    permite pasar los que FastAPI ya leyó como `Form(...)`. `business_type`
    es la operación elegida en el perfil (en la alerta, puede cambiarla).
    """
    values = {name: form_data.get(name) for name in (*PROFILE_TEXT_FIELDS, *PROFILE_LOCATION_FIELDS)}
    values["notes"] = form_data.get(notes_field)
    values["business_type"] = form_data.get("business_type")
    values.update({k: v for k, v in overrides.items() if k in values})
    values["zones"] = [z for z in form_data.getlist("zones") if z]
    values["cities"] = [c for c in form_data.getlist("cities") if c]
    return values


def _profile_values_present(values: dict) -> bool:
    """True si el formulario trae algún dato del perfil.

    País y operación no cuentan: salen preseleccionados aunque el agente no
    toque nada (la provincia sí, es un mínimo de ubicación).
    """
    if values["zones"] or values["cities"]:
        return True
    return any(str(values[name] or "").strip() for name in (*PROFILE_TEXT_FIELDS, "province", "notes"))


def _profile_kwargs(alert: PropertyAlert, values: dict, criteria: Optional[BuyerSearchCriteria]) -> dict:
    """Argumentos de `buyer_matching.apply_profile` para guardar el perfil desde la alerta.

    La operación es la de la alerta (si el perfil la cambia, la ruta cambia
    antes la de la alerta: `_operation_change`) y el agente responsable del
    perfil, el de la alerta.
    """
    return dict(
        country=values.get("country"),
        province=values.get("province"),
        zones=values["zones"],
        cities=values["cities"],
        property_type=values["property_type"],
        business_type=alert.business_type or (criteria.business_type if criteria is not None else None),
        min_price=values["min_price"],
        max_price=values["max_price"],
        min_bedrooms=values["min_bedrooms"],
        max_bedrooms=values["max_bedrooms"],
        min_bathrooms=values["min_bathrooms"],
        notes=values["notes"],
        agent_id=alert.agent_id,
    )


def _operation_change(alert: PropertyAlert, values: dict) -> tuple:
    """Operación pedida en el perfil de la alerta: (nueva operación o None, error o None).

    PLAN_PERFIL_UBICACION.md (decisión 2): la operación se puede cambiar desde
    el perfil y cambia la de la alerta. Sin valor, o igual a la actual, no
    cambia nada. Solo Venta o Alquiler, y solo con la alerta abierta.
    """
    requested = (values.get("business_type") or "").strip()
    if not requested or requested == (alert.business_type or ""):
        return None, None
    if not BusinessType.is_valid(requested):
        return None, "Selecciona la operación del comprador: Venta o Alquiler"
    if alert.status not in OPEN_ALERT_STATUSES:
        return None, "La alerta está cerrada: no se puede cambiar la operación"
    return requested, None


def _apply_operation_change(alert: PropertyAlert, new_operation: Optional[str]) -> Optional[str]:
    """Cambia la operación de la alerta; devuelve la línea para la nota ("Operación: Venta → Alquiler")."""
    if not new_operation:
        return None
    previous = alert.business_type or "sin definir"
    alert.business_type = new_operation
    return f"Operación: {previous} → {new_operation}"


def _join_note(*lines) -> Optional[str]:
    """Nota del seguimiento: las líneas no vacías, una por línea (None si no hay ninguna)."""
    text = "\n".join(line.strip() for line in lines if line and line.strip())
    return text or None


def _missing_in_profile_form(alert: PropertyAlert, values: dict) -> list:
    """Mínimos que faltan en el perfil enviado, sin tocar el perfil guardado.

    Se evalúa sobre un perfil temporal (fuera de la sesión) con el mismo
    parseo que se usará al guardar, así la validación y lo guardado coinciden.
    """
    preview = buyer_matching.apply_profile(
        BuyerSearchCriteria(), **_profile_kwargs(alert, values, _alert_criteria(alert))
    )
    return buyer_matching.missing_profile_fields(preview)


def _store_alert_profile(db: Session, alert: PropertyAlert, values: dict, now: datetime) -> BuyerSearchCriteria:
    """Upsert del perfil del comprador de la alerta (sin commit)."""
    buyer = alert.buyer
    criteria = buyer.search_criteria
    if criteria is None:
        criteria = BuyerSearchCriteria(buyer_id=buyer.id)
        db.add(criteria)
        buyer.search_criteria = criteria
    buyer_matching.apply_profile(criteria, **_profile_kwargs(alert, values, criteria), now=now)
    return criteria


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

    # Base query: alertas de la empresa activa (empresa propia de la alerta).
    # OUTER JOIN con la propiedad: una búsqueda general (PLAN_ALERTA_SIN_REFERENCIA.md)
    # puede no tenerla todavía y debe seguir apareciendo. El JOIN con agentes
    # va por el agente de la ALERTA (no el captador de la propiedad):
    # property_alerts tiene dos FK a agents y la propiedad puede no tener captador.
    base_query = scope_alerts(
        db.query(PropertyAlert)
        .outerjoin(Property, Property.id == PropertyAlert.property_id)
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
    # (sin propiedad, el título es NULL y el OR sigue funcionando con los otros)
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

    # Total filtrado. Los JOIN a Property (outer) y Agent son N:1 (una fila por
    # alerta), así que contar PropertyAlert.id no se multiplica.
    total_alerts = filtered_query.with_entities(func.count(PropertyAlert.id)).scalar() or 0
    alert_pagination = paginate_params(page, per_page_value, total_alerts)

    # Ordenar por prioridad y fecha (el id solo desempata para que la
    # paginación sea estable). Propiedad y agente se rellenan con el JOIN
    # que ya hace la consulta, y los seguimientos de la página se cargan en
    # una segunda consulta: sin esto se hacía una consulta por alerta al
    # pintar la tabla (N+1). La fecha es la que ve cada rol
    # (PLAN_ALERTA_COMO_NUEVA.md): creación para el admin, asignación para el
    # agente, así una alerta reasignada se ordena como nueva para él.
    date_order = PropertyAlert.created_at if admin_view else alert_view.assignment_start_expr()
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
            date_order.desc(),
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

    # Búsquedas generales sin propiedad: resumen del perfil del comprador en la
    # columna Propiedad ("Piso · Jaén · 2-3 dorm"). Para el admin, además, las
    # alertas abiertas sin perfil completo (chip "Sin perfil" junto a la etapa,
    # PLAN_PERFIL_OBLIGATORIO.md). Una consulta para la página.
    search_summaries, profile_missing_ids = _page_profiles(db, alerts, with_missing=admin_view)

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
    # lo muestra igualmente). Las notas del sistema (reasignación) no son una
    # etapa. Para el agente solo cuenta lo registrado desde su asignación: una
    # alerta reasignada sale "Sin iniciar" hasta que él registre un seguimiento
    # (PLAN_ALERTA_COMO_NUEVA.md); el admin ve la etapa con todo el historial.
    # `follow_ups` ya viene cargado con selectinload: se filtra en Python.
    alert_stages = {}
    labels = FollowUpActionType.labels()
    for alert in alerts:
        since = None if admin_view else alert_view.assignment_start(alert)
        real = alert_view.real_follow_ups_since(alert.follow_ups, since)
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

    # Compradores que requieren atención (PLAN_RECORDATORIO_SIN_RESPUESTA.md):
    # badge «Volver a llamar · intento N de 3» o «Sin gestión» en horas hábiles.
    # Se calcula sobre los seguimientos ya cargados de la página, sin consultas nuevas.
    alert_attention = buyer_attention_service.evaluate_alerts(alerts)

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
            "alert_attention": alert_attention,
            # Columna "Fecha": creación (admin) o asignación (agente)
            "display_dates": {a.id: alert_view.display_date(a, admin_view) for a in alerts},
            "is_admin": is_admin(current_user),
            "search_summaries": search_summaries,
            "profile_missing_ids": profile_missing_ids,
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
    alert_id: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Autocompletado de propiedades para el formulario de nueva alerta.

    Devuelve como máximo PROPERTY_SEARCH_LIMIT coincidencias por título,
    dirección o ciudad. Admin y agentes: solo expone título, dirección,
    ciudad y agente (nombre e id, para preseleccionarlo en "Agente asignado"),
    nunca el propietario. Las propiedades sin captador solo las ve el admin.

    Con `alert_id` de una alerta abierta que el usuario puede trabajar y cuyo
    comprador tiene el perfil completo (paso "Propuesta",
    PLAN_ALERTA_SIN_REFERENCIA.md y PLAN_PERFIL_OBLIGATORIO.md; con o sin
    referencia): todas las disponibles de la empresa, de cualquier agente
    (decisión cerrada 3), para asociarlas a esa alerta. En cualquier otro
    caso, la regla de siempre.

    NOTA: debe declararse antes de /alerts/{alert_id}, o FastAPI intentaría
    resolver "search-properties" como un id y devolvería 422.
    """

    term = (q or "").strip()

    if len(term) < 2:
        return JSONResponse(content={"results": []})

    like = f"%{term}%"
    company_id = get_active_company(request).id

    # ¿Búsqueda para asociar una propiedad a una alerta (paso Propuesta)?
    link_alert = None
    link_alert_id = assignment._to_int(alert_id)
    if link_alert_id is not None:
        candidate = get_alert_in_company(db, link_alert_id, company_id)
        if candidate is not None and _search_link_denied(
            candidate, request.state.user, db, require_profile=True
        ) is None:
            link_alert = candidate

    query = scope_properties(db.query(Property), company_id).filter(
        Property.status != PropertyStatus.ARCHIVED,
        Property.available_clause(),
        or_(
            Property.title.ilike(like),
            Property.address.ilike(like),
            Property.city.ilike(like),
        ),
    )
    # El agente solo puede crear alertas sobre sus propiedades asignadas, así
    # que el buscador solo le ofrece esas (esto también excluye las que no
    # tienen captador, que son solo para el admin, §4-7). Asociar una
    # propiedad ajena a su búsqueda sí está permitido (decisión cerrada 2).
    if link_alert is None and not is_admin(request.state.user):
        own_agent = get_agent_from_user(request.state.user, db)
        if not own_agent:
            return JSONResponse(content={"results": []})
        query = query.filter(Property.agent_id == own_agent.id)

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


@router.get("/alerts/check-search-duplicate")
async def check_search_duplicate(
    request: Request,
    buyer_id: int = Query(...),
    business_type: str = Query(""),
    db: Session = Depends(get_db)
):
    """Búsquedas generales abiertas del comprador con esa operación.

    Lo consulta el modal de nueva alerta en modo "Sin referencia" en cuanto
    conoce comprador y operación (PLAN_ALERTA_SIN_REFERENCIA.md). Mismo
    formato que /alerts/check-duplicate. Admin, y agentes sobre compradores a
    los que tienen acceso.

    NOTA: debe declararse antes de /alerts/{alert_id}.
    """
    company_id = get_active_company(request).id
    business_type = (business_type or "").strip()

    buyer = get_buyer_in_company(db, buyer_id, company_id)
    if not buyer or not can_access_buyer(buyer, request.state.user, db) or not BusinessType.is_valid(business_type):
        return JSONResponse(content={"open": [], "recent_closed": []})

    alerts = find_open_search_alerts(db, company_id, buyer_id, business_type)
    return JSONResponse(content=serialize_search_duplicates(db, alerts))


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


# Pasos del detalle de una alerta (PLAN_ALERTA_SIN_REFERENCIA.md; desde
# PLAN_PERFIL_OBLIGATORIO.md en todas las alertas, con o sin referencia)
SEARCH_STEPS = (
    ("contact", "1. Contactar"),
    ("profile", "2. Perfil"),
    ("proposal", "3. Propuesta"),
)
SEARCH_STEP_KEYS = tuple(key for key, _ in SEARCH_STEPS)

# Tarjetas de propiedades sugeridas en el paso "Propuesta"
SEARCH_SUGGESTION_LIMIT = 30


def _search_context(db: Session, alert: PropertyAlert, current_user, admin_view: bool,
                    step: Optional[str], confirm_property: Optional[str], follow_ups, company_id: int) -> dict:
    """Contexto de los pasos Contactar → Perfil → Propuesta del detalle de una alerta.

    PLAN_PERFIL_OBLIGATORIO.md: en TODAS las alertas (el origen solo es una
    etiqueta), siempre que el usuario pueda trabajarlas (abierta, con
    comprador, agente asignado o admin). Paso por defecto: Contactar si aún no
    hay gestión desde la asignación; Perfil si el perfil del comprador no está
    completo; si no, Propuesta. Sin perfil completo la Propuesta no sugiere ni
    deja asociar ("Perfil pendiente").

    Para el modal de seguimiento (Contactado lleva el perfil dentro) entrega
    también `profile_complete`, `profile_missing` y las opciones del
    formulario precargado (`location`: cascada de ubicación; `property_types`).

    PLAN_PERFIL_UBICACION.md: `operation_mismatch` avisa en la Propuesta de
    que la propiedad asociada es de otra operación que la que busca el
    comprador (la propiedad se mantiene).
    """
    criteria = _alert_criteria(alert)
    profile_complete = buyer_matching.profile_is_complete(criteria)
    ctx = {
        "is_search": alert.is_search,
        "can_manage_search": False,
        "show_steps": False,
        "search_steps": SEARCH_STEPS,
        "step": None,
        "criteria": criteria,
        "criteria_parts": buyer_matching.criteria_parts(criteria),
        "profile_applies": _profile_applies(alert),
        "profile_complete": profile_complete,
        "profile_missing": buyer_matching.missing_profile_fields(criteria),
        "suggestions": [],
        "suggestions_total": 0,
        "suggestion_limit": SEARCH_SUGGESTION_LIMIT,
        "current_in_suggestions": False,
        "link_duplicate": None,
        "own_agent_id": None,
        "property_link_allowed": True,
        "current_stage_label": None,
        "location": {},
        "property_types": [],
        "operation_mismatch": None,
    }

    own_agent = None if admin_view else get_agent_from_user(current_user, db)
    ctx["own_agent_id"] = own_agent.id if own_agent else None

    # La ficha de una propiedad de otro agente no se enlaza al agente (tiene
    # datos del propietario), igual que en la ficha del comprador. Cualquier
    # alerta puede tener asociada una propiedad ajena (decisión 2 de
    # PLAN_ALERTA_SIN_REFERENCIA.md, en todas las alertas desde
    # PLAN_PERFIL_OBLIGATORIO.md), o ser una alerta reasignada.
    prop = alert.property
    if prop is not None and not admin_view:
        ctx["property_link_allowed"] = own_agent is not None and prop.agent_id == own_agent.id

    # Formulario del perfil (paso Perfil y «Contactado» del modal de
    # seguimiento): valores de las propiedades de la empresa, solo si se va a pintar
    ctx["follow_up_profile"] = ctx["profile_applies"] and alert.status in OPEN_ALERT_STATUSES
    if ctx["follow_up_profile"]:
        ctx.update(_property_filter_values(db, company_id, criteria))

    # Propiedad asociada de otra operación que la que busca el comprador
    # (p. ej. tras cambiar la operación en el perfil): se avisa en la Propuesta
    wanted = (criteria.business_type if criteria is not None else None) or alert.business_type
    if prop is not None and wanted and prop.business_type and prop.business_type != wanted:
        ctx["operation_mismatch"] = {"property": prop.business_type, "wanted": wanted}

    # Etapa actual (último seguimiento real visible), para el paso Contactar
    real = alert_view.real_follow_ups_since(follow_ups, None)
    if real:
        latest = max(real, key=lambda f: f.created_at or datetime.min)
        ctx["current_stage_label"] = FollowUpActionType.labels().get(latest.action_type, latest.action_type)

    can_manage = (
        alert.status in OPEN_ALERT_STATUSES
        and alert.buyer is not None
        and (admin_view or (own_agent is not None and alert.agent_id == own_agent.id))
    )
    ctx["can_manage_search"] = can_manage
    if not can_manage:
        return ctx

    # Pasos en todas las alertas; una con referencia y sin gestión abre en
    # Contactar con su propiedad visible encima
    if step not in SEARCH_STEP_KEYS:
        if not alert_view.has_follow_up_since_assignment(follow_ups, alert):
            step = "contact"
        elif not profile_complete:
            step = "profile"
        else:
            step = "proposal"
    ctx["show_steps"] = True
    ctx["step"] = step

    # Propuesta: sin perfil completo no hay sugerencias (estado vacío con el
    # aviso "Perfil pendiente" y enlace al paso Perfil)
    if step == "proposal" and profile_complete:
        query = buyer_matching.matching_properties_query(db, criteria, company_id)
        ctx["suggestions_total"] = query.order_by(None).count()
        ctx["suggestions"] = query.limit(SEARCH_SUGGESTION_LIMIT).all()
        # La propiedad actual se marca "Asociada ahora"; si no encaja con el
        # perfil (o no está entre las primeras), se pinta aparte encima
        ctx["current_in_suggestions"] = any(p.id == alert.property_id for p in ctx["suggestions"])

    # Aviso de duplicado al asociar: el comprador ya tiene otra alerta abierta
    # sobre esa propiedad (lo pide /link-property antes de confirmar)
    confirm_id = assignment._to_int(confirm_property)
    if step == "proposal" and profile_complete and confirm_id is not None and alert.buyer_id:
        target = get_property_in_company(db, confirm_id, company_id)
        if target is not None:
            others = [
                a for a in find_duplicate_alerts(db, company_id, alert.buyer_id, target.id)["open"]
                if a.id != alert.id
            ]
            if others:
                ctx["link_duplicate"] = {"property": target, "alerts": others}

    return ctx


@router.get("/alerts/{alert_id}", response_class=HTMLResponse)
async def alert_detail(
    alert_id: int,
    request: Request,
    step: Optional[str] = Query(default=None),
    confirm_property: Optional[str] = Query(default=None),
    db: Session = Depends(get_db)
):
    """Detalle de una alerta con historial de seguimientos.

    PLAN_ALERTA_COMO_NUEVA.md: para el agente una alerta reasignada es nueva
    (solo ve lo ocurrido desde su asignación, sin el rastro de la
    reasignación) y una alerta bloqueada por la cola no se puede abrir; el
    admin lo ve todo.

    PLAN_ALERTA_SIN_REFERENCIA.md y PLAN_PERFIL_OBLIGATORIO.md: cualquier
    alerta (con o sin referencia) se trabaja en tres pasos (`step`):
    Contactar, Perfil y Propuesta. `confirm_property` pinta el aviso de
    duplicado al asociar.
    """

    current_user = request.state.user
    admin_view = is_admin(current_user)

    alert = get_alert_in_company(db, alert_id, get_active_company(request).id)

    if not alert:
        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "error", "Alerta no encontrada")
        return response

    # Verificar permisos: admin puede ver todo, agente solo sus alertas
    if not admin_view:
        agent = get_agent_from_user(current_user, db)
        if not agent or alert.agent_id != agent.id:
            response = RedirectResponse(url="/alerts", status_code=302)
            set_flash(response, "error", "No tienes permisos para ver esta alerta")
            return response

    # Cola secuencial: una alerta bloqueada no se abre por ningún camino
    # (listado, notificación, Inicio, ficha del comprador). Se comprueba ANTES
    # de cualquier escritura para no marcarla leída ni pasarla a En proceso.
    if is_alert_locked_for_user(alert, current_user, db):
        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "warning", ALERT_LOCKED_MESSAGE)
        return response

    # Auto-marcar como leída al abrir: solo el agente asignado, solo si está abierta
    if not admin_view and not alert.read_at and alert.status in OPEN_ALERT_STATUSES:
        agent = get_agent_from_user(current_user, db)
        if agent and alert.agent_id == agent.id:
            alert.read_at = datetime.utcnow()
            if alert.status == AlertStatus.PENDING:
                alert.status = AlertStatus.IN_PROGRESS
            db.commit()

    # Seguimientos ordenados por fecha (más reciente primero). El admin los ve
    # todos; el agente, solo los reales desde su asignación.
    all_follow_ups = db.query(AlertFollowUp).filter(
        AlertFollowUp.alert_id == alert_id
    ).order_by(AlertFollowUp.created_at.desc()).all()
    follow_ups = alert_view.visible_follow_ups(all_follow_ups, alert, admin_view)

    # Cargar nombres de usuarios que registraron cada seguimiento
    user_ids = {f.created_by for f in follow_ups if f.created_by}
    follow_up_users = {}
    if user_ids:
        users = db.query(User).filter(User.id.in_(user_ids)).all()
        follow_up_users = {u.id: u.full_name for u in users}

    # Ya no puede estar bloqueada para quien llega aquí (el agente bloqueado
    # se redirige arriba); se mantiene por seguridad para la plantilla.
    alert_locked = False

    can_reassign = admin_view and alert.status in assignment.REASSIGNABLE_STATUSES

    company_id = get_active_company(request).id
    search_ctx = _search_context(db, alert, current_user, admin_view, step, confirm_property,
                                 follow_ups, company_id)

    # Plazo en horas hábiles (PLAN_RECORDATORIO_SIN_RESPUESTA.md §3.1): la regla
    # que gobierna la alerta, vencida (banner "Venció el …") o aún no ("Vence el …").
    clock = buyer_attention_service.alert_clock(alert)
    attention = clock if clock is not None and clock.overdue else None
    upcoming_clocks = [clock] if clock is not None and not clock.overdue else []

    return templates.TemplateResponse(
        request=request,
        name="alerts/detail.html",
        context={
            **search_ctx,
            "request": request,
            "alert": alert,
            "follow_ups": follow_ups,
            "current_user": current_user,
            "alert_locked": alert_locked,
            "is_admin": admin_view,
            # Bloque "Agente asignado" (quién, antes, motivo, historial): solo admin
            "show_assignment": admin_view,
            # Fecha de la caja de estado: creación (admin) o asignación (agente)
            "display_date": alert_view.display_date(alert, admin_view),
            "assignment_start": alert_view.assignment_start(alert),
            # Cerrar exige un seguimiento real desde la asignación (la nota de
            # reasignación y los del agente anterior no cuentan), para ambos roles
            "can_complete": alert_view.has_follow_up_since_assignment(all_follow_ups, alert),
            "can_reassign": can_reassign,
            "attention": attention,
            "upcoming_clocks": upcoming_clocks,
            "RULE_CALLBACK": buyer_attention_service.RULE_CALLBACK,
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
    property_id: Optional[int] = Form(None),
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
    agente solo puede crear alertas sobre sus propiedades asignadas y solo
    puede usar compradores a los que tiene acceso.

    Validación de duplicados:
    - Comprador existente: si ya hay una alerta abierta para ese comprador y
      esa propiedad, no se crea salvo que llegue ``confirm_duplicate``. Al
      confirmar, se deja constancia en el mensaje.
    - Comprador nuevo: si ya hay un comprador con el mismo teléfono o correo,
      no se crea salvo que llegue ``confirm_new_buyer``.
    El formulario avisa antes de enviar; esto es la red de seguridad.

    Sin propiedad (PLAN_ALERTA_SIN_REFERENCIA.md): alerta "sin referencia"
    (búsqueda general, `origin='search'`) en la empresa activa. El admin
    elige el agente (obligatorio: no hay captador del que deducirlo) y el
    agente queda asignado a sí mismo. No se comprueba propiedad ni
    disponibilidad. Duplicado: otra búsqueda abierta del mismo comprador y
    operación, con la misma confirmación ``confirm_duplicate``.
    """

    current_user = request.state.user

    company_id = get_active_company(request).id
    is_search = property_id is None

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

    admin_view = is_admin(current_user)

    if is_search:
        # Alerta sin referencia: agente elegido por el admin o el propio agente
        try:
            assignee = assignment.resolve_search_assignee(
                is_admin_user=admin_view,
                requested_agent_id=agent_id,
                own_agent=None if admin_view else get_agent_from_user(current_user, db),
                lookup_any_agent=assignment.lookup_any_agent(db),
            )
        except AlertAssignmentError as error:
            db.rollback()
            response = RedirectResponse(url="/alerts", status_code=302)
            set_flash(response, "error", str(error))
            return response

        property_item = None

        # Duplicado: otra búsqueda abierta del mismo comprador y operación
        if buyer_id:
            open_searches = find_open_search_alerts(db, company_id, buyer.id, business_type)
            if open_searches:
                existing = open_searches[0]
                if not confirm_duplicate:
                    db.rollback()
                    fecha = existing.created_at.strftime("%d/%m/%Y") if existing.created_at else ""
                    response = RedirectResponse(url="/alerts", status_code=302)
                    set_flash(
                        response,
                        "warning",
                        f"{buyer.name} ya tiene una búsqueda de {business_type} abierta (#{existing.id}, {fecha}). "
                        "No se ha creado otra. Si quieres repetirla, confírmalo en el formulario."
                    )
                    return response
                message = append_note(message, search_duplicate_note(existing))
    else:
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

        # El agente solo puede crear alertas sobre sus propiedades asignadas. El
        # buscador y la ficha del comprador ya no le ofrecen otras; esto es la red
        # de seguridad por si llega un property_id a mano.
        if not admin_view:
            own_agent = get_agent_from_user(current_user, db)
            if not own_agent or property_item.agent_id != own_agent.id:
                db.rollback()
                back_url = f"/buyers/{buyer_id}" if buyer_id else "/alerts"
                response = RedirectResponse(url=back_url, status_code=302)
                set_flash(response, "error", "Solo puedes crear alertas sobre las propiedades que tienes asignadas")
                return response

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
            company_id=company_id,
            origin=AlertOrigin.SEARCH if is_search else AlertOrigin.PROPERTY,
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
        # Un agente solo crea alertas sobre sus propiedades (o búsquedas a su
        # nombre), así que la alerta siempre queda a su nombre y no hace falta
        # avisarle de la asignación.
        what = "Búsqueda general creada" if is_search else "Alerta creada"
        if admin_view:
            message = f"{what} para {buyer.name} y asignada a {assignee.name}"
            if result.granted_company is not None:
                message += f". {assignee.name} ahora tiene acceso a {result.granted_company.name}"
            set_flash(response, "success", message)
        elif is_search:
            set_flash(response, "success", f"{what} para {buyer.name}. Ábrela para tomar su perfil de búsqueda")
        else:
            set_flash(response, "success", f"Alerta de comprador creada para {buyer.name}")
        return response

    except Exception:
        db.rollback()
        logger.exception("Error creando alerta: property_id=%s", property_id)
        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "error", "Ocurrió un error al crear la alerta")
        return response


def _profile_step_url(alert_id: int) -> str:
    """Paso Perfil del detalle (allí se completa el perfil que falta)."""
    return f"/alerts/{alert_id}?step=profile#propuesta"


def _search_denied_response(alert_id: int, reason: str) -> RedirectResponse:
    """Redirección y flash cuando no se puede trabajar la búsqueda."""
    if reason == ALERT_LOCKED_MESSAGE:
        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "warning", reason)
    elif reason == "No tienes permisos para esta alerta":
        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "error", reason)
    elif reason == PROFILE_REQUIRED_MESSAGE:
        # Asociar sin perfil: al paso Perfil, donde se completa
        response = RedirectResponse(url=_profile_step_url(alert_id), status_code=302)
        set_flash(response, "error", reason)
    else:
        response = RedirectResponse(url=f"/alerts/{alert_id}", status_code=302)
        set_flash(response, "error", reason)
    return response


@router.post("/alerts/{alert_id}/search-profile")
async def save_alert_search_profile(
    alert_id: int,
    request: Request,
    property_type: str = Form(None),
    min_price: str = Form(None),
    max_price: str = Form(None),
    min_bedrooms: str = Form(None),
    max_bedrooms: str = Form(None),
    min_bathrooms: str = Form(None),
    notes: str = Form(None),
    db: Session = Depends(get_db)
):
    """Guarda el perfil de búsqueda del comprador desde su alerta (paso Perfil).

    PLAN_ALERTA_SIN_REFERENCIA.md (decisión cerrada 4): upsert del perfil del
    comprador (uno por comprador, sin m²) con la operación y el agente de la
    alerta. Vale para cualquier alerta, con o sin referencia.

    PLAN_PERFIL_OBLIGATORIO.md: el perfil debe traer los mínimos (tipo,
    precio máximo y ubicación; PLAN_PERFIL_UBICACION.md: provincia, o al
    menos una población o una zona); si no, no se guarda nada. Si el perfil del
    comprador aún NO estaba completo, guardarlo registra un seguimiento
    CONTACTADO (perfil = contactado, avanza la etapa); si ya lo estaba, es una
    edición y registra PERFIL_GUARDADO (no mueve la etapa). En ambos casos el
    resumen va como nota y cuenta como gestión (desbloquea la cola y permite
    cerrar). Vuelve al paso "Propuesta". Solo el agente asignado o el admin,
    nunca con la alerta bloqueada.

    PLAN_PERFIL_UBICACION.md: guarda también país y provincia, y la operación
    elegida en el perfil; si cambia, cambia la de la alerta (abierta) y queda
    en la nota del mismo seguimiento ("Operación: Venta → Alquiler").
    """
    current_user = request.state.user
    company_id = get_active_company(request).id

    alert = get_alert_in_company(db, alert_id, company_id)
    if not alert:
        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "error", "Alerta no encontrada")
        return response

    denied = _search_link_denied(alert, current_user, db)
    if denied:
        return _search_denied_response(alert_id, denied)

    buyer = alert.buyer
    if buyer is None:
        response = RedirectResponse(url=f"/alerts/{alert_id}", status_code=302)
        set_flash(response, "error", "La alerta no tiene comprador asociado")
        return response

    form_data = await request.form()
    values = _profile_values(
        form_data, property_type=property_type, min_price=min_price, max_price=max_price,
        min_bedrooms=min_bedrooms, max_bedrooms=max_bedrooms, min_bathrooms=min_bathrooms, notes=notes,
    )

    # Mínimos del perfil (validación en servidor aunque el formulario ya los pida)
    missing = _missing_in_profile_form(alert, values)
    if missing:
        response = RedirectResponse(url=_profile_step_url(alert_id), status_code=302)
        set_flash(response, "error",
                  f"Faltan datos del perfil: {buyer_matching.missing_profile_text(missing)}")
        return response

    # Operación elegida en el perfil (si cambia, cambia la de la alerta)
    new_operation, operation_error = _operation_change(alert, values)
    if operation_error:
        response = RedirectResponse(url=_profile_step_url(alert_id), status_code=302)
        set_flash(response, "error", operation_error)
        return response

    # Primera vez que el perfil queda completo = Contactado (decisión 5)
    first_profile = not buyer_matching.profile_is_complete(buyer.search_criteria)

    try:
        now = datetime.utcnow()
        operation_line = _apply_operation_change(alert, new_operation)
        criteria = _store_alert_profile(db, alert, values, now)

        db.add(AlertFollowUp(
            alert_id=alert.id,
            action_type=FollowUpActionType.CONTACTADO if first_profile else FollowUpActionType.PERFIL_GUARDADO,
            notes=_join_note(operation_line, buyer_matching.profile_note(criteria)),
            created_at=now,
            created_by=current_user.id,
        ))
        if alert.status == AlertStatus.PENDING:
            alert.status = AlertStatus.IN_PROGRESS

        db.commit()
        # Gestión registrada: los avisos de comprador que ya no apliquen se marcan leídos
        notification_service.safe_resolve_buyer_notifications(db, alert.id)
    except Exception:
        db.rollback()
        logger.exception("Error guardando el perfil desde la alerta: alert_id=%s", alert_id)
        response = RedirectResponse(url=f"/alerts/{alert_id}?step=profile", status_code=302)
        set_flash(response, "error", "Ocurrió un error al guardar el perfil")
        return response

    total = buyer_matching.matching_properties_query(db, criteria, company_id).order_by(None).count()
    response = RedirectResponse(url=f"/alerts/{alert_id}?step=proposal", status_code=302)
    set_flash(
        response,
        "success",
        f"Perfil de {buyer.name} guardado"
        + (" y registrado como «Contactado»" if first_profile else "")
        + f": {total} "
        + ("propiedad sugerida" if total == 1 else "propiedades sugeridas")
        + (f". La alerta pasa a {new_operation}" if new_operation else ""),
    )
    return response


@router.post("/alerts/{alert_id}/link-property")
async def link_property_to_alert(
    alert_id: int,
    request: Request,
    property_id: Optional[int] = Form(None),
    confirm_duplicate: str = Form(None),
    db: Session = Depends(get_db)
):
    """Asocia (o cambia) la propiedad de una alerta.

    PLAN_PERFIL_OBLIGATORIO.md: cualquier alerta, con o sin referencia (el
    origen ya no cuenta), y solo si el comprador tiene el perfil completo
    ("Registra primero el perfil del comprador" → paso Perfil).

    PLAN_ALERTA_SIN_REFERENCIA.md: una sola alerta (decisión 1); el agente
    que atiende la conserva aunque la propiedad sea de otro agente (decisión
    2: no se toca `agent_id`). La propiedad debe ser de la empresa y estar
    disponible. Si el comprador ya tiene otra alerta abierta sobre esa
    propiedad, se pide confirmación (``confirm_duplicate``) y se deja nota.
    Registra un seguimiento PROPIEDAD_ASOCIADA ("Propiedad asociada: X" o
    "Cambio de propiedad: de A a B"), que cuenta como gestión pero no avanza
    la etapa.
    """
    current_user = request.state.user
    company_id = get_active_company(request).id
    detail_url = f"/alerts/{alert_id}"

    alert = get_alert_in_company(db, alert_id, company_id)
    if not alert:
        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "error", "Alerta no encontrada")
        return response

    denied = _search_link_denied(alert, current_user, db, require_profile=True)
    if denied:
        return _search_denied_response(alert_id, denied)

    property_item = get_property_in_company(db, property_id, company_id) if property_id else None
    if property_item is None:
        response = RedirectResponse(url=f"{detail_url}?step=proposal", status_code=302)
        set_flash(response, "error", "Propiedad no encontrada")
        return response

    if not property_item.is_available or property_item.status == PropertyStatus.ARCHIVED:
        response = RedirectResponse(url=f"{detail_url}?step=proposal", status_code=302)
        set_flash(response, "error", f"{property_item.title} no está disponible")
        return response

    if alert.property_id == property_item.id:
        response = RedirectResponse(url=detail_url, status_code=302)
        set_flash(response, "info", f"{property_item.title} ya está asociada a esta alerta")
        return response

    # Otra alerta abierta del mismo comprador sobre esa propiedad (de cualquier agente)
    duplicate = None
    if alert.buyer_id:
        others = [
            a for a in find_duplicate_alerts(db, company_id, alert.buyer_id, property_item.id)["open"]
            if a.id != alert.id
        ]
        if others:
            duplicate = others[0]
            if not confirm_duplicate:
                fecha = duplicate.created_at.strftime("%d/%m/%Y") if duplicate.created_at else ""
                response = RedirectResponse(
                    url=f"{detail_url}?step=proposal&confirm_property={property_item.id}#propuesta",
                    status_code=302,
                )
                set_flash(
                    response,
                    "warning",
                    f"{alert.lead_name} ya tiene una alerta abierta sobre {property_item.title} "
                    f"(#{duplicate.id}, {fecha}). No se ha asociado: confírmalo si quieres asociarla igualmente."
                )
                return response

    previous = alert.property
    try:
        now = datetime.utcnow()
        if duplicate is not None:
            alert.message = append_note(alert.message, linked_duplicate_note(duplicate))

        alert.property = property_item
        alert.property_linked_at = now

        if previous is not None:
            note = f"Cambio de propiedad: de {previous.title} a {property_item.title}"
        else:
            note = f"Propiedad asociada: {property_item.title}"
        db.add(AlertFollowUp(
            alert_id=alert.id,
            action_type=FollowUpActionType.PROPIEDAD_ASOCIADA,
            notes=note,
            created_at=now,
            created_by=current_user.id,
        ))
        if alert.status == AlertStatus.PENDING:
            alert.status = AlertStatus.IN_PROGRESS

        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Error asociando propiedad: alert_id=%s property_id=%s", alert_id, property_id)
        response = RedirectResponse(url=f"{detail_url}?step=proposal", status_code=302)
        set_flash(response, "error", "Ocurrió un error al asociar la propiedad")
        return response

    # Asociar la propiedad es una gestión real: el aviso "sin gestión" ya no aplica
    notification_service.safe_resolve_buyer_notifications(db, alert.id)

    response = RedirectResponse(url=detail_url, status_code=302)
    if previous is not None:
        set_flash(response, "success", f"Propiedad cambiada: {alert.lead_name} ahora tiene asociada {property_item.title}")
    else:
        set_flash(response, "success", f"{property_item.title} asociada a la búsqueda de {alert.lead_name}")
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

    # El reloj arranca de cero con el nuevo agente: los avisos del anterior ya no aplican
    notification_service.safe_resolve_buyer_notifications(db, alert.id)

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
    """Agregar seguimiento a una alerta.

    PLAN_PERFIL_OBLIGATORIO.md (validación en servidor aunque el modal ya lo
    impida):

    - Visita programada, Oferta y Cerrado (éxito) exigen el perfil del
      comprador completo; sin él, error y al paso Perfil sin guardar nada.
    - Contactado lleva dentro el perfil (campos del formulario del perfil;
      los imprescindibles llegan como `profile_notes`). Si el perfil no
      estaba completo, los mínimos son obligatorios; si ya lo estaba, son
      opcionales (si llegan, se editan; si no llega ninguno, el perfil no se
      toca). Se guarda el perfil y UN solo seguimiento CONTACTADO con la nota
      del agente más el resumen del perfil (no además un PERFIL_GUARDADO).
      PLAN_PERFIL_UBICACION.md: si la operación del perfil cambia, cambia la
      de la alerta y va en la nota de ese mismo seguimiento.
    - Sin respuesta y los cierres negativos se registran sin perfil.

    Una alerta sin comprador no tiene dónde guardar el perfil y queda fuera
    del requisito (ver `_profile_applies`).
    """

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
        if action_type in FollowUpActionType.LEGACY_STAGES:
            # Etapas retiradas del formulario (PLAN_RECORDATORIO_SIN_RESPUESTA.md §3.3)
            label = FollowUpActionType.labels()[action_type]
            set_flash(response, "error", f"«{label}» ya no se registra como seguimiento. Elige otra etapa.")
        else:
            set_flash(response, "error", "Tipo de acción no válido")
        return response

    # Notas obligatorias al cerrar
    if action_type in FollowUpActionType.CLOSING_STAGES and not (notes or "").strip():
        response = RedirectResponse(url=f"/alerts/{alert_id}", status_code=302)
        set_flash(response, "error", "Debes escribir una nota al cerrar la alerta")
        return response

    # Perfil del comprador (PLAN_PERFIL_OBLIGATORIO.md)
    profile_applies = _profile_applies(alert)
    profile_complete = buyer_matching.profile_is_complete(_alert_criteria(alert))

    # Etapas avanzadas: exigen el perfil completo
    if (profile_applies and action_type in FollowUpActionType.PROFILE_REQUIRED_STAGES
            and not profile_complete):
        stage_label = dict(FollowUpActionType.ordered_stages()).get(action_type, action_type)
        response = RedirectResponse(url=_profile_step_url(alert_id), status_code=302)
        set_flash(
            response,
            "error",
            f"Registra primero el perfil del comprador (seguimiento Contactado) para poder marcar «{stage_label}»",
        )
        return response

    # Contactado: el perfil viaja en el mismo formulario
    profile_values = None
    if profile_applies and action_type == FollowUpActionType.CONTACTADO:
        values = _profile_values(await request.form(), notes_field="profile_notes")
        if _profile_values_present(values):
            missing = _missing_in_profile_form(alert, values)
        else:
            # Sin campos: vale solo si el perfil ya estaba completo (no se toca)
            missing = [] if profile_complete else buyer_matching.missing_profile_fields(_alert_criteria(alert))
            values = None
        if missing:
            response = RedirectResponse(url=_profile_step_url(alert_id), status_code=302)
            set_flash(
                response,
                "error",
                "Para registrar «Contactado» completa el perfil del comprador. Falta: "
                + buyer_matching.missing_profile_text(missing),
            )
            return response
        profile_values = values

    # Operación elegida en el perfil de «Contactado» (si cambia, cambia la de la alerta)
    new_operation = None
    if profile_values is not None:
        new_operation, operation_error = _operation_change(alert, profile_values)
        if operation_error:
            response = RedirectResponse(url=_profile_step_url(alert_id), status_code=302)
            set_flash(response, "error", operation_error)
            return response

    try:
        # Parsear fecha si existe
        next_action_date_parsed = None
        if next_action_date:
            try:
                next_action_date_parsed = datetime.fromisoformat(next_action_date)
            except ValueError:
                pass

        # Contactado con perfil: se guarda el perfil y su resumen va en la
        # nota del mismo seguimiento (uno solo, sin PERFIL_GUARDADO aparte)
        if profile_values is not None:
            operation_line = _apply_operation_change(alert, new_operation)
            criteria = _store_alert_profile(db, alert, profile_values, datetime.utcnow())
            notes = _join_note(notes, operation_line, buyer_matching.profile_note(criteria))

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
            notification_service.safe_resolve_buyer_notifications(db, alert_id)
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
        # Gestión registrada: los avisos de comprador que ya no apliquen se marcan leídos
        notification_service.safe_resolve_buyer_notifications(db, alert_id)

        response = RedirectResponse(url=f"/alerts/{alert_id}", status_code=302)
        if profile_values is not None:
            set_flash(response, "success", f"«Contactado» registrado con el perfil de {alert.buyer.name}")
        else:
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
    # desde su asignación (la nota automática de reasignación y los
    # seguimientos del agente anterior no cuentan; PLAN_ALERTA_COMO_NUEVA.md)
    follow_ups_count = _real_follow_ups(
        db, alert_id, since=alert_view.assignment_start(alert)
    ).count()

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
        notification_service.safe_resolve_buyer_notifications(db, alert_id)

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
        lead_name = alert.lead_name
        db.delete(alert)
        db.commit()
        notification_service.safe_resolve_buyer_notifications(db, alert_id)

        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "success", f"Alerta de {lead_name} eliminada correctamente")
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

    # Propiedades compatibles (solo si hay perfil). Servicio compartido con el
    # paso "Propuesta" de las alertas sin referencia; sin filtros de m².
    matching_properties = []
    if criteria:
        matching_properties = buyer_matching.matching_properties(db, criteria, company.id)

    # Valores disponibles en la BD para los selectores (cascada de ubicación,
    # PLAN_PERFIL_UBICACION.md, con el estado inicial del perfil guardado)
    filter_values = _property_filter_values(db, company.id, criteria)
    property_types = filter_values["property_types"]
    business_types = filter_values["business_types"]

    agents = scope_agents(db.query(Agent), company.id).order_by(Agent.name.asc()).all()

    # "Agente asignado" del formulario rápido: solo el admin elige (§4-2)
    assignable_groups = assignment.assignable_agents(db, company.id) if is_admin(current_user) else []

    # Para el agente: su propia ficha (las propiedades de otros agentes se
    # muestran como recomendadas pero sin enlace al detalle, que incluye
    # datos del propietario).
    own_agent = None if is_admin(current_user) else get_agent_from_user(current_user, db)

    # Pestaña Alertas (PLAN_ALERTA_COMO_NUEVA.md). El admin ve todas las del
    # comprador con su fecha de creación. El agente solo las suyas (las de
    # otros agentes no puede abrirlas), con la fecha de su asignación, y las
    # bloqueadas por su cola salen como "En cola" sin datos ni enlace.
    admin_view = is_admin(current_user)
    buyer_alerts_query = db.query(PropertyAlert).filter(PropertyAlert.buyer_id == buyer_id)
    locked_alert_ids = set()
    if admin_view:
        date_order = PropertyAlert.created_at
    else:
        buyer_alerts_query = buyer_alerts_query.filter(
            PropertyAlert.agent_id == (own_agent.id if own_agent else -1)
        )
        date_order = alert_view.assignment_start_expr()
        if own_agent:
            locked_alert_ids = get_locked_alert_ids(own_agent.id, db, company.id)
    buyer_alerts = (
        buyer_alerts_query
        # La propiedad se pinta en cada fila: en la misma consulta (puede faltar)
        .options(selectinload(PropertyAlert.property))
        .order_by(date_order.desc(), PropertyAlert.id.desc())
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
            # Resumen del perfil para las búsquedas sin propiedad de la pestaña Alertas
            "criteria_summary": buyer_matching.criteria_summary(criteria),
            "criteria_parts": buyer_matching.criteria_parts(criteria),
            "own_agent": own_agent,
            "buyer_alerts": buyer_alerts,
            "locked_alert_ids": locked_alert_ids,
            "display_dates": {a.id: alert_view.display_date(a, admin_view) for a in buyer_alerts},
            "agents": agents,
            "assignable_groups": assignable_groups,
            "location": filter_values["location"],
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
    notes: str = Form(None),
    db: Session = Depends(get_db)
):
    """Crear o actualizar el perfil de búsqueda de un comprador.

    Admin y agentes con acceso al comprador. Para el agente, el agente
    responsable del perfil es siempre su propia ficha. Sin m²
    (PLAN_ALERTA_SIN_REFERENCIA.md, decisión cerrada 5): los valores antiguos
    se conservan en la base de datos, pero ya no se editan ni filtran.

    PLAN_PERFIL_UBICACION.md: mismos mínimos que el perfil de la alerta (tipo,
    precio máximo y ubicación; `buyer_matching.missing_profile_fields`), con
    país y provincia de la cascada. Aquí no hay alerta: la operación se edita
    como siempre y no se registra ningún seguimiento."""

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

    # Poblaciones y zonas vienen como lista de casillas; país y provincia, de la cascada
    form_data = await request.form()
    profile = dict(
        country=form_data.get("country"),
        province=form_data.get("province"),
        zones=form_data.getlist("zones"),
        cities=form_data.getlist("cities"),
        property_type=property_type,
        business_type=business_type,
        min_price=min_price,
        max_price=max_price,
        min_bedrooms=min_bedrooms,
        max_bedrooms=max_bedrooms,
        min_bathrooms=min_bathrooms,
        notes=notes,
        agent_id=agent_id,
    )

    # Mínimos del perfil, evaluados sobre un perfil temporal con el mismo parseo
    missing = buyer_matching.missing_profile_fields(buyer_matching.apply_profile(BuyerSearchCriteria(), **profile))
    if missing:
        response = RedirectResponse(url=f"/buyers/{buyer_id}?tab=criteria", status_code=302)
        set_flash(response, "error",
                  f"Faltan datos del perfil: {buyer_matching.missing_profile_text(missing)}")
        return response

    try:
        criteria = buyer.search_criteria
        if criteria is None:
            criteria = BuyerSearchCriteria(buyer_id=buyer_id)
            db.add(criteria)

        buyer_matching.apply_profile(criteria, **profile)

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
