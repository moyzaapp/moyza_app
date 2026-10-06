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

from sqlalchemy.orm import Session
from sqlalchemy import func, case, or_

from app.core.constants import AlertType, PropertyStatus
from app.core.constants import AlertPriority
from app.core.constants import AlertStatus
from app.core.constants import FollowUpActionType
from app.db.deps import get_db

from app.models.property_alert import PropertyAlert
from app.models.alert_follow_up import AlertFollowUp
from app.models.property import Property
from app.models.agent import Agent
from app.models.user import User
from app.models.buyer import Buyer
from app.models.buyer_search_criteria import BuyerSearchCriteria

from app.web.utils.flash import set_flash
from app.web.dependencies.auth import is_admin, get_agent_from_user, require_admin_role


router = APIRouter()
logger = logging.getLogger(__name__)


# Estados que se consideran "abiertos" para la cola secuencial del agente
OPEN_ALERT_STATUSES = [AlertStatus.PENDING, AlertStatus.IN_PROGRESS]

# Máximo de sugerencias devueltas por el autocompletado de propiedades
PROPERTY_SEARCH_LIMIT = 15


def _get_agent_open_alerts_ordered(agent_id: int, db: Session):
    """Devuelve las alertas abiertas del agente ordenadas FIFO."""
    return (
        db.query(PropertyAlert)
        .filter(
            PropertyAlert.agent_id == agent_id,
            PropertyAlert.status.in_(OPEN_ALERT_STATUSES),
        )
        .order_by(PropertyAlert.created_at.asc(), PropertyAlert.id.asc())
        .all()
    )


def _alert_has_followup(alert_id: int, db: Session) -> bool:
    return (
        db.query(AlertFollowUp)
        .filter(AlertFollowUp.alert_id == alert_id)
        .count()
    ) > 0


def get_locked_alert_ids(agent_id: int, db: Session) -> set:
    """Devuelve el conjunto de IDs de alertas bloqueadas para un agente.

    Una alerta en la cola está bloqueada si alguna alerta anterior (más antigua)
    aún no tiene ningún seguimiento registrado. En cuanto el agente registra
    cualquier seguimiento en la alerta actual, la siguiente se desbloquea.
    """
    open_alerts = _get_agent_open_alerts_ordered(agent_id, db)
    locked = set()
    all_preceding_started = True
    for alert in open_alerts:
        if not all_preceding_started:
            locked.add(alert.id)
        else:
            if not _alert_has_followup(alert.id, db):
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

    open_alerts = _get_agent_open_alerts_ordered(agent.id, db)
    for oa in open_alerts:
        if oa.id == alert.id:
            return False  # Todas las anteriores tienen seguimiento → accesible
        if not _alert_has_followup(oa.id, db):
            return True  # Alerta anterior sin seguimiento → esta está bloqueada
    return False


@router.get("/alerts", response_class=HTMLResponse)
async def alerts_page(
    request: Request,
    q: str = Query(default=""),
    status_filter: List[str] = Query(default=[]),
    agent_id: Optional[str] = Query(default=None),
    db: Session = Depends(get_db)
):
    """Lista de alertas - Admin ve todas, agentes solo las suyas"""

    current_user = request.state.user

    # Base query
    base_query = db.query(PropertyAlert).join(Property).join(Agent)

    # Si es agente, filtrar solo sus alertas
    if not is_admin(current_user):
        agent = get_agent_from_user(current_user, db)
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

    # Filtro por estado (multi-select)
    valid_status_filters = [s for s in status_filter if AlertStatus.is_valid(s)]
    if valid_status_filters:
        base_query = base_query.filter(PropertyAlert.status.in_(valid_status_filters))

    # Filtro por agente (solo admin; agentes ya están filtrados por su propio id)
    agent_id_int = int(agent_id) if agent_id and agent_id.strip() else None
    if agent_id_int and is_admin(current_user):
        base_query = base_query.filter(PropertyAlert.agent_id == agent_id_int)

    # Ordenar por prioridad y fecha
    alerts = base_query.order_by(
        case(
            (PropertyAlert.priority == AlertPriority.ALTA, 1),
            (PropertyAlert.priority == AlertPriority.NORMAL, 2),
            (PropertyAlert.priority == AlertPriority.BAJA, 3),
            else_=4
        ),
        PropertyAlert.created_at.desc()
    ).all()

    # Contar alertas por estado
    pending_count = base_query.filter(PropertyAlert.status == AlertStatus.PENDING).count()
    in_progress_count = base_query.filter(PropertyAlert.status == AlertStatus.IN_PROGRESS).count()
    completed_count = base_query.filter(PropertyAlert.status == AlertStatus.COMPLETED).count()

    # Agentes para el formulario de creación (solo admin). Las propiedades no se
    # precargan: el formulario las busca por /alerts/search-properties.
    agents = []
    if is_admin(current_user):
        agents = db.query(Agent).all()

    # Lista de compradores: el admin ve siempre el listado completo. Para el
    # agente, en cambio, solo aparecen los compradores cuyas alertas ya
    # iniciaron seguimiento (status distinto de PENDING), así la lista se va
    # llenando a medida que va gestionando sus alertas.
    if is_admin(current_user):
        buyers = db.query(Buyer).order_by(Buyer.name.asc()).all()
    else:
        agent = get_agent_from_user(current_user, db)
        if agent:
            started_buyer_ids = (
                db.query(PropertyAlert.buyer_id)
                .filter(
                    PropertyAlert.buyer_id.isnot(None),
                    PropertyAlert.status != AlertStatus.PENDING,
                    PropertyAlert.agent_id == agent.id,
                )
                .subquery()
            )
            buyers = (
                db.query(Buyer)
                .filter(Buyer.id.in_(started_buyer_ids))
                .order_by(Buyer.name.asc())
                .all()
            )
        else:
            buyers = []

    # Conteo por tipo de operación de los compradores que efectivamente
    # aparecen en `buyers` (no del total de alertas del sistema), para que el
    # desglose "N Alquiler, N Venta" cuadre con la lista mostrada. Para el
    # admin cuentan todas sus alertas; para el agente, solo las que ya
    # iniciaron seguimiento y son suyas (mismo criterio con el que se armó
    # `buyers` arriba).
    buyer_operation_counts = {}
    admin_view = is_admin(current_user)
    for buyer in buyers:
        for buyer_alert in buyer.alerts:
            if not buyer_alert.business_type:
                continue
            if admin_view:
                counted = True
            else:
                counted = (
                    buyer_alert.status != AlertStatus.PENDING
                    and agent
                    and buyer_alert.agent_id == agent.id
                )
            if counted:
                buyer_operation_counts[buyer_alert.business_type] = (
                    buyer_operation_counts.get(buyer_alert.business_type, 0) + 1
                )

    # Valores para selectores del modal de criteria
    zones = [
        r[0] for r in
        db.query(Property.zona).filter(Property.zona.isnot(None), Property.zona != "")
        .distinct().order_by(Property.zona.asc()).all()
    ]
    cities = [
        r[0] for r in
        db.query(Property.city).filter(Property.city.isnot(None), Property.city != "")
        .distinct().order_by(Property.city.asc()).all()
    ]
    property_types = [
        r[0] for r in
        db.query(Property.property_type).filter(Property.property_type.isnot(None))
        .distinct().order_by(Property.property_type.asc()).all()
    ]
    business_types = [
        r[0] for r in
        db.query(Property.business_type).filter(Property.business_type.isnot(None))
        .distinct().order_by(Property.business_type.asc()).all()
    ]

    # Calcular alertas bloqueadas y etapa actual de cada alerta
    locked_alert_ids = set()
    if not is_admin(current_user):
        agent = get_agent_from_user(current_user, db)
        if agent:
            locked_alert_ids = get_locked_alert_ids(agent.id, db)

    # Etapa actual de cada alerta: último seguimiento de progresión (ignora
    # SIN_RESPUESTA para no retroceder la etapa visible; si solo hay sin-respuesta,
    # lo muestra igualmente).
    alert_stages = {}
    labels = FollowUpActionType.labels()
    for alert in alerts:
        if alert.follow_ups:
            progression = [
                f for f in alert.follow_ups
                if f.action_type not in FollowUpActionType.REPEATABLE_ACTIONS
            ]
            latest = max(
                progression if progression else alert.follow_ups,
                key=lambda f: f.created_at,
            )
            alert_stages[alert.id] = {
                "value": latest.action_type,
                "label": labels.get(latest.action_type, latest.action_type),
                "color": FollowUpActionType.stage_badge_color(latest.action_type),
            }

    return templates.TemplateResponse(
        request=request,
        name="alerts/list.html",
        context={
            "request": request,
            "alerts": alerts,
            "buyers": buyers,
            "buyer_operation_counts": buyer_operation_counts,
            "current_user": current_user,
            "pending_count": pending_count,
            "in_progress_count": in_progress_count,
            "completed_count": completed_count,
            "agents": agents,
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


@router.get("/alerts/search-buyers")
async def search_buyers(
    request: Request,
    q: str = "",
    db: Session = Depends(get_db)
):
    """Autocompletado de compradores para el formulario de nueva alerta."""

    current_user = request.state.user

    if not is_admin(current_user):
        return JSONResponse(status_code=403, content={"results": []})

    term = (q or "").strip()

    if len(term) < 2:
        return JSONResponse(content={"results": []})

    like = f"%{term}%"

    buyers = (
        db.query(Buyer)
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
            "email": b.email or "",
        }
        for b in buyers
    ]

    return JSONResponse(content={"results": results})


@router.post("/buyers/create")
async def create_buyer(
    request: Request,
    name: str = Form(...),
    phone: str = Form(None),
    email: str = Form(None),
    notes: str = Form(None),
    db: Session = Depends(get_db)
):
    """Crear nuevo comprador sin alerta asociada (solo admin)"""

    current_user = request.state.user

    if not is_admin(current_user):
        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "error", "Solo administradores pueden crear compradores")
        return response

    name = (name or "").strip()
    if not name:
        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "error", "El nombre del comprador es obligatorio")
        return response

    try:
        buyer = Buyer(
            name=name,
            phone=(phone or "").strip() or None,
            email=(email or "").strip() or None,
            notes=notes,
            created_by=current_user.id
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
    """Crea o selecciona un comprador, guarda sus criterios y va a los matches."""

    current_user = request.state.user

    if not is_admin(current_user):
        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "error", "Acceso no autorizado")
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
            buyer = db.query(Buyer).filter(Buyer.id == buyer_id).first()
            if not buyer:
                response = RedirectResponse(url="/alerts", status_code=302)
                set_flash(response, "error", "Comprador no encontrado")
                return response
        else:
            buyer_name = (buyer_name or "").strip()
            if not buyer_name:
                response = RedirectResponse(url="/alerts", status_code=302)
                set_flash(response, "error", "El nombre del comprador es obligatorio")
                return response
            buyer = Buyer(
                name=buyer_name,
                phone=(buyer_phone or "").strip() or None,
                email=(buyer_email or "").strip() or None,
                created_by=current_user.id
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

    buyer = db.query(Buyer).filter(Buyer.id == buyer_id).first()

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
    dirección o ciudad. Solo admin, igual que la creación de alertas.

    NOTA: debe declararse antes de /alerts/{alert_id}, o FastAPI intentaría
    resolver "search-properties" como un id y devolvería 422.
    """

    current_user = request.state.user

    if not is_admin(current_user):
        return JSONResponse(status_code=403, content={"results": []})

    term = (q or "").strip()

    if len(term) < 2:
        return JSONResponse(content={"results": []})

    like = f"%{term}%"

    properties = (
        db.query(Property)
        .filter(
            Property.status != PropertyStatus.ARCHIVED,
            Property.available_clause(),
            Property.agent_id.isnot(None),
            or_(
                Property.title.ilike(like),
                Property.address.ilike(like),
                Property.city.ilike(like),
            ),
        )
        .order_by(Property.title.asc())
        .limit(PROPERTY_SEARCH_LIMIT)
        .all()
    )

    results = [
        {
            "id": p.id,
            "title": p.title,
            "address": p.address or "",
            "city": p.city or "",
            "agent": p.agent.name if p.agent else "",
        }
        for p in properties
    ]

    return JSONResponse(content={"results": results})


@router.get("/alerts/{alert_id}", response_class=HTMLResponse)
async def alert_detail(
    alert_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Detalle de una alerta con historial de seguimientos"""

    current_user = request.state.user

    alert = db.query(PropertyAlert).filter(PropertyAlert.id == alert_id).first()

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

    return templates.TemplateResponse(
        request=request,
        name="alerts/detail.html",
        context={
            "request": request,
            "alert": alert,
            "follow_ups": follow_ups,
            "current_user": current_user,
            "alert_locked": alert_locked,
            "is_admin": is_admin(current_user),
            "can_complete": len(follow_ups) > 0,
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
    buyer_phone: str = Form(None),
    buyer_email: str = Form(None),
    source: str = Form(None),
    alert_type: str = Form(AlertType.LEAD_INTERES),
    message: str = Form(None),
    priority: str = Form(AlertPriority.NORMAL),
    business_type: str = Form(None),
    db: Session = Depends(get_db)
):
    """Crear nueva alerta con comprador existente o nuevo (solo admin)"""

    current_user = request.state.user

    if not is_admin(current_user):
        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "error", "Solo administradores pueden crear alertas")
        return response

    # Resolver comprador: existente o nuevo
    buyer = None

    if buyer_id:
        buyer = db.query(Buyer).filter(Buyer.id == buyer_id).first()
        if not buyer:
            response = RedirectResponse(url="/alerts", status_code=302)
            set_flash(response, "error", "Comprador no encontrado")
            return response
    else:
        buyer_name = (buyer_name or "").strip()
        if not buyer_name:
            response = RedirectResponse(url="/alerts", status_code=302)
            set_flash(response, "error", "El nombre del comprador es obligatorio")
            return response

        buyer = Buyer(
            name=buyer_name,
            phone=(buyer_phone or "").strip() or None,
            email=(buyer_email or "").strip() or None,
            created_by=current_user.id
        )
        db.add(buyer)
        db.flush()  # obtener buyer.id antes del commit

    # Obtener la propiedad y su agente
    property_item = db.query(Property).filter(Property.id == property_id).first()

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

    if not property_item.agent_id:
        db.rollback()
        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "error", "La propiedad no tiene agente asignado")
        return response

    try:
        alert = PropertyAlert(
            property_id=property_id,
            agent_id=property_item.agent_id,
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
            created_by=current_user.id
        )

        db.add(alert)
        db.commit()

        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "success", f"Alerta de comprador creada para {buyer.name}")
        return response

    except Exception:
        db.rollback()
        logger.exception("Error creando alerta: property_id=%s", property_id)
        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "error", "Ocurrió un error al crear la alerta")
        return response


@router.post("/alerts/{alert_id}/mark-read")
async def mark_alert_read(
    alert_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Marcar alerta como leída"""

    current_user = request.state.user

    alert = db.query(PropertyAlert).filter(PropertyAlert.id == alert_id).first()

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

    alert = db.query(PropertyAlert).filter(PropertyAlert.id == alert_id).first()

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


@router.post("/alerts/{alert_id}/complete")
async def complete_alert(
    alert_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Completar/cerrar una alerta"""

    current_user = request.state.user

    alert = db.query(PropertyAlert).filter(PropertyAlert.id == alert_id).first()

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
    follow_ups_count = db.query(AlertFollowUp).filter(
        AlertFollowUp.alert_id == alert_id
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

    alert = db.query(PropertyAlert).filter(PropertyAlert.id == alert_id).first()

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

    # Obtener usuario desde el token (las rutas API no pasan por AuthMiddleware)
    from app.core.security import decode_token

    token = request.cookies.get("access_token")
    if not token:
        return JSONResponse(content={"unread_count": 0})

    payload = decode_token(token)
    if not payload:
        return JSONResponse(content={"unread_count": 0})

    email = payload.get("sub")
    if not email:
        return JSONResponse(content={"unread_count": 0})

    current_user = db.query(User).filter(User.email == email).first()
    if not current_user:
        return JSONResponse(content={"unread_count": 0})

    base_query = db.query(PropertyAlert).filter(
        PropertyAlert.status.in_([AlertStatus.PENDING, AlertStatus.IN_PROGRESS])
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

    alert = db.query(PropertyAlert).filter(PropertyAlert.id == alert_id).first()

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


@router.get("/alerts-dashboard", response_class=HTMLResponse)
async def alerts_dashboard(
    request: Request,
    tab: str = Query(default="general"),
    period_type: str = Query(default="WEEKLY"),
    period_start: str = Query(default=""),
    db: Session = Depends(get_db)
):
    """Dashboard de métricas de alertas (solo admin)"""

    from datetime import timedelta
    from app.services.performance_report_service import PerformanceReportService

    current_user = request.state.user

    if not is_admin(current_user):
        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "error", "Solo administradores pueden acceder al dashboard")
        return response

    # ── Tab General: métricas globales ──────────────────────────────────────
    all_alerts = db.query(PropertyAlert).all()

    total_alerts = len(all_alerts)
    pending_alerts = sum(1 for a in all_alerts if a.status == AlertStatus.PENDING)
    in_progress_alerts = sum(1 for a in all_alerts if a.status == AlertStatus.IN_PROGRESS)
    completed_alerts = sum(1 for a in all_alerts if a.status == AlertStatus.COMPLETED)

    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    abandoned_alerts = [
        a for a in all_alerts
        if a.status == AlertStatus.PENDING and a.created_at < seven_days_ago
    ]

    response_times = []
    for alert in all_alerts:
        if alert.read_at and alert.created_at:
            delta = alert.read_at - alert.created_at
            response_times.append(delta.total_seconds() / 3600)

    avg_response_time = sum(response_times) / len(response_times) if response_times else 0

    agents_data = []
    agents = db.query(Agent).all()

    for agent in agents:
        agent_alerts = [a for a in all_alerts if a.agent_id == agent.id]
        if not agent_alerts:
            continue
        agent_pending = sum(1 for a in agent_alerts if a.status == AlertStatus.PENDING)
        agent_in_progress = sum(1 for a in agent_alerts if a.status == AlertStatus.IN_PROGRESS)
        agent_completed = sum(1 for a in agent_alerts if a.status == AlertStatus.COMPLETED)
        agent_response_times = []
        for alert in agent_alerts:
            if alert.read_at and alert.created_at:
                delta = alert.read_at - alert.created_at
                agent_response_times.append(delta.total_seconds() / 3600)
        agent_avg_response = sum(agent_response_times) / len(agent_response_times) if agent_response_times else 0
        last_activity = None
        if agent_alerts:
            latest_alert = max(agent_alerts, key=lambda a: a.created_at if a.created_at else datetime.min)
            last_activity = latest_alert.created_at
        agents_data.append({
            "agent": agent,
            "total_alerts": len(agent_alerts),
            "pending": agent_pending,
            "in_progress": agent_in_progress,
            "completed": agent_completed,
            "avg_response_time": round(agent_avg_response, 1),
            "last_activity": last_activity,
        })

    agents_data.sort(key=lambda x: x["pending"], reverse=True)

    # ── Tab Rendimiento: métricas por período ───────────────────────────────
    perf_data = None
    if tab == "rendimiento":
        if period_type not in ("WEEKLY", "MONTHLY"):
            period_type = "WEEKLY"

        svc = PerformanceReportService(db)

        if period_type == "MONTHLY":
            if period_start:
                try:
                    ps = datetime.strptime(period_start, "%Y-%m-%d")
                    ps = datetime(ps.year, ps.month, 1)
                except ValueError:
                    ps = svc.current_month_start()
            else:
                ps = svc.current_month_start()
            _, pe = svc.month_bounds(ps)
            prev_start = datetime(ps.year - 1, 12, 1) if ps.month == 1 else datetime(ps.year, ps.month - 1, 1)
            next_start = datetime(ps.year + 1, 1, 1) if ps.month == 12 else datetime(ps.year, ps.month + 1, 1)
            current_start = svc.current_month_start()
        else:
            if period_start:
                try:
                    ps = datetime.strptime(period_start, "%Y-%m-%d")
                    ps = ps - timedelta(days=ps.weekday())
                    ps = datetime(ps.year, ps.month, ps.day)
                except ValueError:
                    ps = svc.current_week_start()
            else:
                ps = svc.current_week_start()
            _, pe = svc.week_bounds(ps)
            prev_start = ps - timedelta(days=7)
            next_start = ps + timedelta(days=7)
            current_start = svc.current_week_start()

        is_current = svc.is_current_period(period_type, ps)
        show_next = next_start <= current_start

        all_perf_agents = db.query(Agent).order_by(Agent.name.asc()).all()
        perf_agents = []
        for agent in all_perf_agents:
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
            perf_agents.append({
                "agent": agent,
                "metrics": metrics,
                "target": target,
                "report": report,
                "admin_notes": report.admin_notes if report else "",
                "is_locked": report.is_locked if report else False,
            })

        perf_data = {
            "period_type": period_type,
            "period_start": ps,
            "period_end": pe,
            "is_current": is_current,
            "prev_start": prev_start,
            "next_start": next_start,
            "show_next": show_next,
            "agents_data": perf_agents,
        }

    return templates.TemplateResponse(
        request=request,
        name="alerts/dashboard.html",
        context={
            "request": request,
            "current_user": current_user,
            "tab": tab,
            "total_alerts": total_alerts,
            "pending_alerts": pending_alerts,
            "in_progress_alerts": in_progress_alerts,
            "completed_alerts": completed_alerts,
            "abandoned_alerts": abandoned_alerts,
            "avg_response_time": round(avg_response_time, 1),
            "agents_data": agents_data,
            "AlertStatus": AlertStatus,
            "perf_data": perf_data,
            "period_type": period_type,
            "period_start_str": period_start,
        }
    )


# ---------------------------------------------------------------------------
# Detalle del comprador y perfil de búsqueda
# ---------------------------------------------------------------------------

def _build_matching_properties(criteria: BuyerSearchCriteria, db: Session):
    """Filtra propiedades activas y disponibles que cumplen todos los criterios definidos."""
    query = db.query(Property).filter(
        Property.status == PropertyStatus.ACTIVE,
        Property.available_clause(),
        Property.agent_id.isnot(None),
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

    buyer = db.query(Buyer).filter(Buyer.id == buyer_id).first()
    if not buyer:
        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "error", "Comprador no encontrado")
        return response

    # Agente solo puede ver compradores relacionados con él
    if not is_admin(current_user):
        agent = get_agent_from_user(current_user, db)
        has_access = False
        if agent:
            via_criteria = (
                db.query(BuyerSearchCriteria)
                .filter(BuyerSearchCriteria.buyer_id == buyer_id,
                        BuyerSearchCriteria.agent_id == agent.id)
                .first()
            )
            via_alert = (
                db.query(PropertyAlert)
                .filter(PropertyAlert.buyer_id == buyer_id,
                        PropertyAlert.agent_id == agent.id)
                .first()
            )
            has_access = bool(via_criteria or via_alert)
        if not has_access:
            response = RedirectResponse(url="/alerts", status_code=302)
            set_flash(response, "error", "No tienes acceso a este comprador")
            return response

    criteria = buyer.search_criteria

    # Propiedades que hacen match (solo si hay criterios definidos)
    matching_properties = []
    if criteria:
        matching_properties = _build_matching_properties(criteria, db)

    # Valores disponibles en la BD para los selectores
    zones = [
        r[0] for r in
        db.query(Property.zona).filter(Property.zona.isnot(None), Property.zona != "")
        .distinct().order_by(Property.zona.asc()).all()
    ]
    cities = [
        r[0] for r in
        db.query(Property.city).filter(Property.city.isnot(None), Property.city != "")
        .distinct().order_by(Property.city.asc()).all()
    ]
    property_types = [
        r[0] for r in
        db.query(Property.property_type).filter(Property.property_type.isnot(None))
        .distinct().order_by(Property.property_type.asc()).all()
    ]
    business_types = [
        r[0] for r in
        db.query(Property.business_type).filter(Property.business_type.isnot(None))
        .distinct().order_by(Property.business_type.asc()).all()
    ]

    agents = db.query(Agent).order_by(Agent.name.asc()).all()
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
            "buyer_alerts": buyer_alerts,
            "agents": agents,
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
    phone: str = Form(None),
    email: str = Form(None),
    db: Session = Depends(get_db)
):
    """Actualiza nombre, teléfono y email del comprador. Accesible para admin y agentes asignados."""
    current_user = request.state.user

    buyer = db.query(Buyer).filter(Buyer.id == buyer_id).first()
    if not buyer:
        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "error", "Comprador no encontrado")
        return response

    if not is_admin(current_user):
        agent = get_agent_from_user(current_user, db)
        has_access = False
        if agent:
            via_criteria = (
                db.query(BuyerSearchCriteria)
                .filter(BuyerSearchCriteria.buyer_id == buyer_id,
                        BuyerSearchCriteria.agent_id == agent.id)
                .first()
            )
            via_alert = (
                db.query(PropertyAlert)
                .filter(PropertyAlert.buyer_id == buyer_id,
                        PropertyAlert.agent_id == agent.id)
                .first()
            )
            has_access = bool(via_criteria or via_alert)
        if not has_access:
            response = RedirectResponse(url="/alerts", status_code=302)
            set_flash(response, "error", "No tienes acceso a este comprador")
            return response

    buyer.name = name.strip()
    buyer.phone = phone.strip() if phone and phone.strip() else None
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
    """Crear o actualizar el perfil de búsqueda de un comprador (solo admin)."""

    current_user = request.state.user

    if not is_admin(current_user):
        response = RedirectResponse(url="/alerts", status_code=302)
        set_flash(response, "error", "Acceso no autorizado")
        return response

    buyer = db.query(Buyer).filter(Buyer.id == buyer_id).first()
    if not buyer:
        response = RedirectResponse(url="/alerts?tab=buyers", status_code=302)
        set_flash(response, "error", "Comprador no encontrado")
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
