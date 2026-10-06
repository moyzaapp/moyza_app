import logging
from datetime import datetime

from fastapi import APIRouter
from fastapi import Request
from fastapi import Depends
from fastapi import Form
from fastapi import Query

from fastapi.responses import HTMLResponse
from fastapi.responses import RedirectResponse

from app.web.template_env import templates

from sqlalchemy import or_, cast, Integer, case, func
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.constants import PropertyInteractionType
from app.core.constants import PropertyStatus
from app.core.constants import ReportType
from app.db.deps import get_db

from app.models.property import Property
from app.models.client import Client
from app.models.agent import Agent
from app.models.property_price_history import PropertyPriceHistory
from app.models.property_interaction import PropertyInteraction
from app.models.property_status_history import PropertyStatusHistory
from app.models.property_change_log import PropertyChangeLog
from app.models.property_visit import PropertyVisit
from app.models.report import Report
from app.services.ai_valuation import AIValuationService

from pathlib import Path

from app.services.company_scope import (
    scope_properties,
    scope_agents,
    scope_clients,
    get_property_in_company,
    get_agent_in_company,
    get_client_in_company,
)
from app.services.property_metrics import PropertyMetricsService
from app.web.dependencies.company import get_active_company
from app.services.report_generator import generate_property_report
from app.web.utils.flash import set_flash
from app.web.utils.property_form import extract_fields
from app.web.dependencies.auth import is_admin, get_agent_from_user, deny_if_not_admin


router = APIRouter()
logger = logging.getLogger(__name__)

# Etiquetas legibles para cada campo de propiedad
_FIELD_LABELS = {
    "title": "Título",
    "price": "Precio",
    "status": "Estado",
    "address": "Dirección",
    "city": "Ciudad",
    "description": "Descripción",
    "client_id": "Cliente",
    "agent_id": "Agente",
    "referencia": "Referencia",
    "codigo": "Código",
    "ref_catastral": "Ref. catastral",
    "property_type": "Tipo de inmueble",
    "business_type": "Operación",
    "estado_inmueble": "Estado del inmueble",
    "situacion": "Situación",
    "pais": "País",
    "zona": "Zona",
    "planta": "Planta",
    "cod_postal": "Código postal",
    "moneda": "Moneda",
    "m2_utiles": "M2 útiles",
    "m2_construidos": "M2 construidos",
    "num_dormitorios": "Dormitorios",
    "num_banos_aseos": "Baños y aseos",
    "num_salones": "Salones",
    "num_terrazas": "Terrazas",
    "num_armarios": "Armarios",
    "num_garaje_aparcam": "Garaje / Aparcamiento",
    "num_ascensores": "Ascensores",
    "num_despachos": "Despachos",
    "num_locales": "Locales",
    "llaves": "Llaves",
    "mandato_acuerdo": "Mandato / Acuerdo",
    "fecha_alta": "Fecha de alta",
    "auto_send_report": "Envío automático",
    "report_frequency": "Frecuencia informe",
    "report_day": "Día informe",
    "report_hour": "Hora informe",
}


def _str(value) -> str:
    """Convierte cualquier valor a string normalizado para comparar."""
    if value is None:
        return ""
    return str(value).strip()


def _build_change_logs(property_obj, new_values: dict, user_id: int, db) -> list:
    """Compara valores actuales del modelo con los nuevos y devuelve logs de cambio."""
    from app.models.client import Client
    from app.models.agent import Agent

    logs = []
    for field, new_val in new_values.items():
        old_val = getattr(property_obj, field, None)

        old_str = _str(old_val)
        new_str = _str(new_val)

        if old_str == new_str:
            continue

        # Para FKs mostramos el nombre en lugar del ID
        if field == "client_id":
            old_client = db.query(Client).filter(Client.id == old_val).first() if old_val else None
            new_client = db.query(Client).filter(Client.id == new_val).first() if new_val else None
            old_str = old_client.name if old_client else old_str
            new_str = new_client.name if new_client else new_str
        elif field == "agent_id":
            old_agent = db.query(Agent).filter(Agent.id == old_val).first() if old_val else None
            new_agent = db.query(Agent).filter(Agent.id == new_val).first() if new_val else None
            old_str = old_agent.name if old_agent else old_str
            new_str = new_agent.name if new_agent else new_str

        logs.append(PropertyChangeLog(
            property_id=property_obj.id,
            field_name=field,
            field_label=_FIELD_LABELS.get(field, field),
            old_value=old_str or None,
            new_value=new_str or None,
            changed_by_id=user_id,
        ))

    return logs


@router.get("/properties", response_class=HTMLResponse)
async def properties_page(
    request: Request,
    tab: str = Query(default="mine"),
    filtro: str = Query(default="activas"),
    db: Session = Depends(get_db)
):

    current_user = request.state.user
    company = get_active_company(request)

    # Filtro por tarjeta: 'activas' (por defecto) | 'no_disponible'.
    # Por ahora no se ofrece una vista con todas las propiedades.
    filtro = filtro if filtro in ("activas", "no_disponible") else "activas"

    # Solo el admin puede crear o eliminar propiedades
    can_create = is_admin(current_user)
    can_delete = can_create

    admin_view = is_admin(current_user)
    agent = None if admin_view else get_agent_from_user(current_user, db)

    # La pestaña "Resto de propiedades" solo aplica a agentes: el admin ya ve
    # el inventario completo en "Mis propiedades".
    show_others_tab = not admin_view and agent is not None
    tab = "others" if (tab == "others" and show_others_tab) else "mine"

    # Si es admin, mostrar todas las propiedades de la empresa activa
    # Si es agente, mostrar solo sus propiedades
    base_query = scope_properties(
        db.query(Property).filter(Property.status != PropertyStatus.ARCHIVED),
        company.id
    )

    if not admin_view:
        if agent:
            base_query = base_query.filter(Property.agent_id == agent.id)
        else:
            # Si no es admin y no tiene agente asociado, no mostrar nada
            base_query = base_query.filter(Property.id == -1)

    # Selectores del formulario: solo clientes y agentes de la empresa activa
    clients = scope_clients(db.query(Client), company.id).order_by(Client.name).all()

    agents = scope_agents(db.query(Agent), company.id).order_by(Agent.name).all()

    # Una propiedad No disponible no cuenta como Activa aunque su status sea Activa.
    is_not_available = Property.not_available_clause()
    is_active = (Property.status == PropertyStatus.ACTIVE) & Property.available_clause()

    # Los contadores reflejan el total del usuario, no el resultado de la búsqueda
    active_count = base_query.filter(is_active).count()
    not_available_count = base_query.filter(is_not_available).count()

    search = (request.query_params.get("search") or "").strip()

    filtered_query = base_query

    if filtro == "activas":
        filtered_query = filtered_query.filter(is_active)
    elif filtro == "no_disponible":
        filtered_query = filtered_query.filter(is_not_available)

    if search:
        pattern = f"%{search}%"

        filtered_query = (
            filtered_query
            .outerjoin(Client, Property.client_id == Client.id)
            .outerjoin(Agent, Property.agent_id == Agent.id)
            .filter(
                or_(
                    Property.title.ilike(pattern),
                    Property.address.ilike(pattern),
                    Property.city.ilike(pattern),
                    Client.name.ilike(pattern),
                    Agent.name.ilike(pattern)
                )
            )
        )

    numeric_title = case(
        (Property.title.op("~")(r"^\d+$"), cast(Property.title, Integer)),
        else_=None
    )
    properties = filtered_query.order_by(
        Property.price.desc().nullslast(),
        numeric_title.desc().nullslast()
    ).all()

    # "Resto de propiedades": inventario activo de la empresa que NO está
    # asociado al agente logueado. Se construye con `with_entities` sobre
    # columnas explícitas (sin `Property.client`/`client_id`) para que el
    # objeto de propietario ni siquiera se cargue desde el backend, en vez de
    # depender de que la plantilla simplemente no lo muestre.
    other_properties = []
    other_count = 0

    if show_others_tab:
        others_base = scope_properties(
            db.query(Property).filter(
                Property.status == PropertyStatus.ACTIVE,
                Property.available_clause(),
                or_(Property.agent_id != agent.id, Property.agent_id.is_(None)),
            ),
            company.id
        )
        other_count = others_base.count()

        if tab == "others":
            others_query = others_base.outerjoin(Agent, Agent.id == Property.agent_id)

            if search:
                pattern = f"%{search}%"
                others_query = others_query.filter(
                    or_(
                        Property.title.ilike(pattern),
                        Property.address.ilike(pattern),
                        Property.city.ilike(pattern),
                        Property.referencia.ilike(pattern),
                    )
                )

            rows = (
                others_query
                .with_entities(
                    Property.id,
                    Property.title,
                    Property.address,
                    Property.city,
                    Property.zona,
                    Property.property_type,
                    Property.business_type,
                    Property.price,
                    Property.moneda,
                    Property.status,
                    Property.m2_utiles,
                    Property.m2_construidos,
                    Property.num_dormitorios,
                    Property.num_banos_aseos,
                    Agent.name.label("agent_name"),
                )
                .order_by(Property.price.desc().nullslast(), Property.title.asc())
                .all()
            )
            other_properties = [dict(row._mapping) for row in rows]

    return templates.TemplateResponse(
        request=request,
        name="properties/home.html",
        context={
            "request": request,
            "properties": properties,
            "clients": clients,
            "agents": agents,
            "current_user": current_user,
            "active_count": active_count,
            "not_available_count": not_available_count,
            "filtro": filtro,
            "search": search,
            "can_create": can_create,
            "can_delete": can_delete,
            "tab": tab,
            "show_others_tab": show_others_tab,
            "other_properties": other_properties,
            "other_count": other_count,
        }
    )

@router.post("/properties/create")
async def create_property(
    request: Request,
    title: str = Form(...),
    address: str = Form(...),
    city: str = Form(...),
    price: float = Form(...),
    description: str = Form(...),
    client_id: int = Form(...),
    agent_id: int = Form(...),
    db: Session = Depends(get_db)
):

    # Solo el admin puede crear propiedades
    denied = deny_if_not_admin(request, "/properties")

    if denied:
        return denied

    company = get_active_company(request)

    # Campos replicados de la tabla externa de propiedades
    form = await request.form()
    external_fields, field_errors = extract_fields(form)

    if field_errors:
        response = RedirectResponse(url="/properties", status_code=302)
        set_flash(response, "error", field_errors[0])
        return response

    # El cliente y el agente deben pertenecer a la empresa activa
    if not get_client_in_company(db, client_id, company.id):
        response = RedirectResponse(url="/properties", status_code=302)
        set_flash(response, "error", f"El cliente seleccionado no pertenece a {company.name}")
        return response

    if not get_agent_in_company(db, agent_id, company.id):
        response = RedirectResponse(url="/properties", status_code=302)
        set_flash(response, "error", f"El agente seleccionado no pertenece a {company.name}")
        return response

    try:
        property_item = Property(
            title=title,
            address=address,
            city=city,
            price=price,
            description=description,
            client_id=client_id,
            agent_id=agent_id,
            status=PropertyStatus.ACTIVE,
            company_id=company.id,
            **external_fields
        )

        db.add(property_item)
        db.commit()

        response = RedirectResponse(url="/properties", status_code=302)
        set_flash(response, "success", f"Propiedad '{title}' creada correctamente")
        return response

    except Exception:
        db.rollback()
        logger.exception("Error creando propiedad: title=%s", title)
        response = RedirectResponse(url="/properties", status_code=302)
        set_flash(response, "error", "Ocurrió un error al crear la propiedad")
        return response

@router.post("/properties/update")
async def update_property(
    request: Request,
    property_id: int = Form(...),
    title: str = Form(...),
    price: float = Form(...),
    client_id: int = Form(...),
    agent_id: int = Form(...),
    address: str = Form(...),
    city: str = Form(...),
    description: str = Form(""),
    status: str = Form(...),
    auto_send_report: bool = Form(False),
    report_frequency: str = Form(None),
    report_day: int = Form(None),
    report_hour: int = Form(None),
    db: Session = Depends(get_db)
):

    if not PropertyStatus.is_valid(status):
        logger.warning(
            "Estado inválido al actualizar propiedad: property_id=%s status=%s",
            property_id,
            status
        )
        response = RedirectResponse(url="/properties", status_code=302)
        set_flash(response, "error", "Estado de propiedad inválido")
        return response

    # Campos replicados de la tabla externa de propiedades
    form = await request.form()
    external_fields, field_errors = extract_fields(form)

    if field_errors:
        response = RedirectResponse(url="/properties", status_code=302)
        set_flash(response, "error", field_errors[0])
        return response

    company = get_active_company(request)

    property = get_property_in_company(db, property_id, company.id)

    if not property:
        response = RedirectResponse(url="/properties", status_code=302)
        set_flash(response, "error", "Propiedad no encontrada")
        return response

    # El cliente y el agente deben pertenecer a la empresa activa
    if not get_client_in_company(db, client_id, company.id):
        response = RedirectResponse(url=f"/properties/{property_id}", status_code=302)
        set_flash(response, "error", f"El cliente seleccionado no pertenece a {company.name}")
        return response

    if not get_agent_in_company(db, agent_id, company.id):
        response = RedirectResponse(url=f"/properties/{property_id}", status_code=302)
        set_flash(response, "error", f"El agente seleccionado no pertenece a {company.name}")
        return response

    try:
        user_id = request.state.user.id
        old_price = property.price
        old_status = property.status

        # Todos los campos nuevos en un dict para comparar antes de aplicar
        new_core = {
            "title": title,
            "price": price,
            "client_id": client_id,
            "agent_id": agent_id,
            "address": address,
            "city": city,
            "description": description,
            "status": status,
            "auto_send_report": auto_send_report,
            "report_frequency": report_frequency,
            "report_day": report_day,
            "report_hour": report_hour,
        }
        all_new = {**new_core, **external_fields}

        change_logs = _build_change_logs(property, all_new, user_id, db)

        # Aplicar cambios al modelo
        for field, value in all_new.items():
            setattr(property, field, value)

        # Historial de precio (tabla existente, se mantiene)
        if old_price != price:
            db.add(PropertyPriceHistory(
                property_id=property_id,
                old_price=old_price,
                new_price=price,
                reason="Actualización manual"
            ))

        # Historial de estado (tabla existente, se mantiene)
        if old_status != status:
            db.add(PropertyStatusHistory(
                property_id=property_id,
                old_status=old_status,
                new_status=status,
                changed_by=user_id
            ))

        for log in change_logs:
            db.add(log)

        db.commit()

    except Exception:
        db.rollback()
        logger.exception("Error actualizando propiedad: property_id=%s", property_id)
        response = RedirectResponse(url="/properties", status_code=302)
        set_flash(response, "error", "Ocurrió un error al actualizar la propiedad")
        return response

    response = RedirectResponse(url=f"/properties/{property_id}", status_code=302)
    set_flash(response, "success", "Propiedad actualizada correctamente")
    return response

@router.post("/properties/delete/{property_id}")
async def delete_property(
    property_id: int,
    request: Request,
    db: Session = Depends(get_db)
):

    # Solo el admin puede eliminar (archivar) propiedades
    denied = deny_if_not_admin(request, "/properties")

    if denied:
        return denied

    property = get_property_in_company(db, property_id, get_active_company(request).id)

    if not property:
        response = RedirectResponse(url="/properties", status_code=302)
        set_flash(response, "error", "Propiedad no encontrada")
        return response

    try:
        old_status = property.status
        user_id = request.state.user.id
        property.status = PropertyStatus.ARCHIVED

        db.add(PropertyStatusHistory(
            property_id=property_id,
            old_status=old_status,
            new_status=PropertyStatus.ARCHIVED,
            changed_by=user_id
        ))

        db.add(PropertyChangeLog(
            property_id=property_id,
            field_name="status",
            field_label="Estado",
            old_value=old_status,
            new_value=PropertyStatus.ARCHIVED,
            changed_by_id=user_id,
        ))

        db.commit()

    except Exception:
        db.rollback()
        logger.exception("Error archivando propiedad: property_id=%s", property_id)
        response = RedirectResponse(url="/properties", status_code=302)
        set_flash(response, "error", "Ocurrió un error al archivar la propiedad")
        return response

    response = RedirectResponse(url="/properties", status_code=302)
    set_flash(response, "success", "Propiedad archivada")
    return response

@router.get("/properties/{property_id}")
async def property_detail(
        property_id: int,
        request: Request,
        db: Session = Depends(get_db)
    ):

    # Una propiedad de la otra empresa no existe para esta vista
    property_item = get_property_in_company(db, property_id, get_active_company(request).id)

    if not property_item:
        return RedirectResponse(
            url="/properties",
            status_code=302
        )

    history = (
        db.query(PropertyPriceHistory)
        .filter(
            PropertyPriceHistory.property_id == property_id
        )
        .order_by(
            PropertyPriceHistory.created_at.desc()
        )
        .all()
    )

    metrics_service = PropertyMetricsService(db)
    report_data = metrics_service.report_data(
        property_item,
        reductions_count=len(history)
    )

    interactions = (
        db.query(PropertyInteraction)
        .filter(
            PropertyInteraction.property_id == property_id
        )
        .order_by(
            PropertyInteraction.created_at.desc()
        )
        .all()
    )

    price_gap = metrics_service.price_gap(property_item)

    status_history = (
        db.query(PropertyStatusHistory)
        .filter(
            PropertyStatusHistory.property_id == property_id
        )
        .order_by(
            PropertyStatusHistory.created_at.desc()
        )
        .all()
    )

    from sqlalchemy.orm import joinedload as _jl
    change_log = (
        db.query(PropertyChangeLog)
        .options(_jl(PropertyChangeLog.changed_by))
        .filter(PropertyChangeLog.property_id == property_id)
        .order_by(PropertyChangeLog.created_at.desc())
        .all()
    )

    visits_registered = (
        db.query(PropertyVisit)
        .filter(
            PropertyVisit.property_id == property_id
        )
        .order_by(
            PropertyVisit.created_at.desc()
        )
        .all()
    )

    visit_summary = metrics_service.visit_summary(visits_registered)

    property_reports = (
        db.query(Report)
        .filter(Report.property_id == property_id)
        .order_by(Report.created_at.desc())
        .all()
    )

    latest_report = property_reports[0] if property_reports else None

    return templates.TemplateResponse(
        request=request,
        name="properties/detail.html",
        context={
            "request": request,
            "property": property_item,
            "history": history,
            "reductions": report_data["reductions"],
            "days_on_market": report_data["days_on_market"],
            "interactions": interactions,
            "current_user": request.state.user,
            "price_gap": price_gap,
            "consultas": report_data["consultas"],
            "visitas": report_data["visitas"],
            "interesados": report_data["interesados"],
            "ofertas": report_data["ofertas"],
            "status_history": status_history,
            "change_log": change_log,
            "visits_registered": visits_registered,
            "interest_avg": visit_summary["interest_avg"],
            "price_high_count": visit_summary["price_high_count"],
            "property_reports": property_reports,
            "latest_report": latest_report
        }
    )


@router.post("/properties/{property_id}/interactions/create")
async def create_interaction(
        property_id: int,
        request: Request,
        interaction_type: str = Form(...),
        contact_name: str = Form(""),
        phone: str = Form(""),
        source: str = Form(""),
        notes: str = Form(""),
        db: Session = Depends(get_db)
    ):

    current_user = request.state.user

    if not get_property_in_company(db, property_id, get_active_company(request).id):
        response = RedirectResponse(url="/properties", status_code=302)
        set_flash(response, "error", "Propiedad no encontrada")
        return response

    if not PropertyInteractionType.is_valid(interaction_type):
        logger.warning(
            "Tipo de interacción inválido: property_id=%s interaction_type=%s",
            property_id,
            interaction_type
        )
        response = RedirectResponse(url=f"/properties/{property_id}", status_code=302)
        set_flash(response, "error", "Tipo de actividad inválido")
        return response

    try:
        interaction = PropertyInteraction(
            property_id=property_id,
            interaction_type=interaction_type,
            contact_name=contact_name,
            phone=phone,
            source=source,
            notes=notes,
            created_by=current_user.id
        )

        db.add(interaction)
        db.commit()

        response = RedirectResponse(url=f"/properties/{property_id}", status_code=302)
        set_flash(response, "success", f"Actividad de tipo '{interaction_type}' registrada correctamente")
        return response

    except Exception:
        db.rollback()
        logger.exception(
            "Error registrando interacción: property_id=%s interaction_type=%s",
            property_id,
            interaction_type
        )
        response = RedirectResponse(url=f"/properties/{property_id}", status_code=302)
        set_flash(response, "error", "Ocurrió un error al registrar la actividad")
        return response

@router.post("/properties/{property_id}/generate-report")
async def generate_report(
        property_id: int,
    request: Request,
        db: Session = Depends(get_db)
    ):

    property_item = get_property_in_company(db, property_id, get_active_company(request).id)

    if not property_item:
        response = RedirectResponse(url="/properties", status_code=302)
        set_flash(response, "error", "Propiedad no encontrada")
        return response

    report_data = PropertyMetricsService(db).report_data(property_item)

    try:
        ai_service = AIValuationService(db)
        ai_analysis = ai_service.generate_analysis(property_item, report_data)
        if ai_analysis:
            report_data["ai_valuation"] = ai_analysis.get("valuation")
            report_data["ai_observations"] = ai_analysis.get("observations")
            ai_service.update_property_fair_price(
                property_item,
                ai_analysis.get("valuation")
            )
            logger.info("Análisis de IA generado para propiedad %s", property_item.id)
        else:
            logger.warning(
                "No se pudo generar análisis de IA para propiedad %s",
                property_item.id
            )
    except Exception:
        logger.exception(
            "Error generando análisis de IA para informe manual: property_id=%s",
            property_item.id
        )

    reports_dir = Path("storage/reports")

    reports_dir.mkdir(parents=True, exist_ok=True)

    filename = f"reporte_propiedad_{property_id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.pdf"

    output_path = reports_dir / filename

    try:
        generate_property_report(property_item, report_data, str(output_path))

        report = Report(
            property_id=property_id,
            uploaded_by=None,
            report_type=ReportType.AUTOMATIC,
            filename=filename,
            filepath=str(output_path)
        )

        db.add(report)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Error generando informe manual: property_id=%s", property_id)
        response = RedirectResponse(url=f"/properties/{property_id}", status_code=302)
        set_flash(response, "error", "No se pudo generar el informe")
        return response

    response = RedirectResponse(url=f"/properties/{property_id}", status_code=302)
    set_flash(response, "success", "Informe generado")
    return response


@router.get("/api/properties/last-update")
async def properties_last_update(
    request: Request,
    db: Session = Depends(get_db)
):
    """Última actividad sobre propiedades de la empresa activa: precio, estado o cambio."""
    from app.web.dependencies.company import get_api_user, resolve_company_for_api

    # Las rutas /api no pasan por AuthMiddleware: resolver usuario y empresa aquí
    user = get_api_user(request, db)
    company = resolve_company_for_api(request, user, db) if user else None

    if company is None:
        return JSONResponse({"last_update": None})

    in_company = Property.company_id == company.id

    t1 = (
        db.query(func.max(PropertyPriceHistory.created_at))
        .join(Property, Property.id == PropertyPriceHistory.property_id)
        .filter(in_company).scalar()
    )
    t2 = (
        db.query(func.max(PropertyStatusHistory.created_at))
        .join(Property, Property.id == PropertyStatusHistory.property_id)
        .filter(in_company).scalar()
    )
    t3 = db.query(func.max(Property.market_entry_date)).filter(in_company).scalar()
    t4 = (
        db.query(func.max(PropertyChangeLog.created_at))
        .join(Property, Property.id == PropertyChangeLog.property_id)
        .filter(in_company).scalar()
    )

    candidates = [t for t in [t1, t2, t3, t4] if t is not None]
    result = max(candidates) if candidates else None

    return JSONResponse({
        "last_update": result.isoformat() if result else None
    })

