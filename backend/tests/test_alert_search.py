"""
Alertas de comprador sin referencia (búsqueda general) y asociación posterior
de propiedad (PLAN_ALERTA_SIN_REFERENCIA.md).

Rutas y servicios en proceso contra una SQLite en memoria con los modelos
reales (patrón de test_alerts_pagination.py / test_alert_view.py): no
necesitan la app levantada ni PostgreSQL. Cada test parte de una base nueva.

    cd backend && python -m pytest tests/test_alert_search.py -q
"""
import asyncio
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from app.core.constants import AlertOrigin, AlertStatus, FollowUpActionType
from app.web.utils.flash import FLASH_COOKIE_NAME, decode_flash


BACKEND = Path(__file__).resolve().parent.parent
T0 = datetime(2026, 10, 1, 9, 0)
LOCKED_TEXT = "Esta alerta está en tu cola. Gestiona primero las anteriores para verla."


# ---------------------------------------------------------------------------
# SQLite en memoria
# ---------------------------------------------------------------------------

@pytest.fixture
def env():
    """MOYZA y MOES; admin; Ana y Bea (agentes de MOYZA con usuario); comprador Juan (de Ana).

    Propiedades de MOYZA: Piso Centro (Ana, 120.000 €, 2 dorm, 50 m²), Piso Bea
    (Bea, 140.000 €, 3 dorm, 200 m²), Casa Cara (Bea, 500.000 €). En MOES:
    Piso MOES (120.000 €).
    """
    import app.db.base as db_base
    from app.models.agent import Agent
    from app.models.buyer import Buyer
    from app.models.company import Company
    from app.models.property import Property
    from app.models.role import Role
    from app.models.user import User

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    db_base.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autoflush=False)()

    moyza = Company(code="MOYZA", name="MOYZA", primary_color="#000000")
    moes = Company(code="MOES", name="MOES PREMIUM", primary_color="#8A6D1F")
    admin_role, agent_role = Role(name="admin"), Role(name="agent")
    admin = User(email="admin@example.com", full_name="Admin Uno", hashed_password="x", role=admin_role)
    users = {
        key: User(email=f"{key}@example.com", full_name=key.title(), hashed_password="x", role=agent_role)
        for key in ("ana", "bea")
    }
    agents = {key: Agent(name=f"Agente {key.title()}", email=f"{key}@example.com") for key in ("ana", "bea")}
    for obj in [admin, *users.values(), *agents.values()]:
        obj.companies.append(moyza)
    admin.companies.append(moes)
    db.add_all([moyza, moes, admin, *users.values(), *agents.values()])
    db.flush()

    def prop(title, company, agent, price, bedrooms=None, bathrooms=None, m2=None):
        return Property(title=title, address=f"Calle {title} 1", city="Jaen", zona="Centro",
                        property_type="Piso", business_type="Venta", price=price, status="Activa",
                        num_dormitorios=bedrooms, num_banos_aseos=bathrooms, m2_utiles=m2,
                        company_id=company.id, agent_id=agent.id)

    props = {
        "ana": prop("Piso Centro", moyza, agents["ana"], 120000, 2, 1, 50),
        "bea": prop("Piso Bea", moyza, agents["bea"], 140000, 3, 2, 200),
        "cara": prop("Casa Cara", moyza, agents["bea"], 500000, 5, 3, 400),
        "moes": prop("Piso MOES", moes, agents["ana"], 120000, 2, 1, 60),
    }
    db.add_all(props.values())
    # Registrado por Ana: así Ana (agente) tiene acceso al comprador
    buyer = Buyer(name="Juan Comprador", phone="34600111222", company_id=moyza.id, created_by=users["ana"].id)
    db.add(buyer)
    db.commit()

    yield SimpleNamespace(db=db, moyza=moyza, moes=moes, admin=admin, users=users, agents=agents,
                          props=props, buyer=buyer)

    db.close()
    engine.dispose()


def _request(env, user, path, method="GET", form=None, company=None, query=""):
    company = company or env.moyza
    body = urlencode(form or {}, doseq=True).encode()
    headers = [(b"host", b"testserver")]
    if form is not None:
        headers.append((b"content-type", b"application/x-www-form-urlencoded"))

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request({
        "type": "http", "method": method, "scheme": "http", "server": ("testserver", 80),
        "path": path, "root_path": "", "query_string": query.encode(), "headers": headers,
        "state": {"user": user, "company": company, "allowed_companies": [company]},
    }, receive)


def _flash(response):
    cookie = response.headers.get("set-cookie", "")
    raw = cookie.split(f"{FLASH_COOKIE_NAME}=", 1)[1].split(";", 1)[0].strip('"')
    return decode_flash(raw)[0]


def _create(env, user, **form):
    """POST /alerts/create con todos los campos (la ruta se llama en proceso)."""
    from app.web.routes.alerts import create_alert
    data = dict(
        property_id=None, buyer_id=env.buyer.id, buyer_name=None, buyer_phone_country_code=None,
        buyer_phone_number=None, buyer_phone=None, buyer_email=None, source="Llamada",
        alert_type="LEAD_INTERES", message=None, priority="NORMAL", business_type="Venta",
        confirm_duplicate=None, confirm_new_buyer=None, agent_id=None, assignment_reason=None,
    )
    data.update(form)
    return asyncio.run(create_alert(_request(env, user, "/alerts/create", "POST"), db=env.db, **data))


def _search_alert(env, agent_key="ana", created_at=T0, business_type="Venta", buyer=None):
    """Búsqueda general como la crea create_alert (sin propiedad)."""
    from app.models.property_alert import PropertyAlert
    from app.services import alert_assignment_service as svc
    buyer = buyer or env.buyer
    alert = PropertyAlert(property=None, company_id=env.moyza.id, origin=AlertOrigin.SEARCH,
                          buyer_id=buyer.id, lead_name=buyer.name, lead_phone=buyer.phone,
                          business_type=business_type, status=AlertStatus.PENDING, priority="NORMAL",
                          created_by=env.admin.id, created_at=created_at)
    env.db.add(alert)
    svc.assign(env.db, alert, env.agents[agent_key], env.admin, None, is_new=True, now=created_at)
    env.db.commit()
    return alert


def _property_alert(env, prop_key, agent_key, created_at=T0, buyer=None):
    from app.models.property_alert import PropertyAlert
    from app.services import alert_assignment_service as svc
    buyer = buyer or env.buyer
    alert = PropertyAlert(property=env.props[prop_key], buyer_id=buyer.id, lead_name=buyer.name,
                          business_type="Venta", status=AlertStatus.PENDING, priority="NORMAL",
                          created_by=env.admin.id, created_at=created_at)
    env.db.add(alert)
    svc.assign(env.db, alert, env.agents[agent_key], env.admin, None, is_new=True, now=created_at)
    env.db.commit()
    return alert


PROFILE = {
    "zones": ["Centro"], "cities": ["Jaen"], "property_type": "Piso",
    "min_price": "100000", "max_price": "150000", "min_bedrooms": "2", "max_bedrooms": "3",
    "min_bathrooms": "1", "notes": "Con terraza",
}


def _complete_profile(env, buyer=None, **fields):
    """Perfil mínimo completo ya guardado (p. ej. desde la ficha del comprador).

    PLAN_PERFIL_OBLIGATORIO.md: asociar o cambiar propiedad exige el perfil
    completo. Por defecto cumple la regla nueva de PLAN_PERFIL_ZONAS.md (tipo,
    precio máximo, población concreta), que incluye la antigua (tipo + precio
    máximo + ubicación): vale con cualquier `created_at` respecto al corte
    `PROFILE_MINIMUMS_SINCE`.
    """
    from app.models.buyer_search_criteria import BuyerSearchCriteria
    buyer = buyer or env.buyer
    data = dict(property_type="Piso", max_price=200000, cities=["Jaen"], zones=["Centro"], business_type="Venta")
    data.update(fields)
    criteria = BuyerSearchCriteria(buyer_id=buyer.id, **data)
    env.db.add(criteria)
    env.db.commit()
    return criteria


def _save_profile(env, user, alert, form=None):
    from app.web.routes.alerts import save_alert_search_profile
    form = dict(PROFILE if form is None else form)
    fields = {k: form.get(k) for k in ("property_type", "min_price", "max_price", "min_bedrooms",
                                       "max_bedrooms", "min_bathrooms", "notes")}
    request = _request(env, user, f"/alerts/{alert.id}/search-profile", "POST", form=form)
    return asyncio.run(save_alert_search_profile(alert.id, request, db=env.db, **fields))


def _link(env, user, alert, prop_key, confirm=None):
    from app.web.routes.alerts import link_property_to_alert
    request = _request(env, user, f"/alerts/{alert.id}/link-property", "POST", form={})
    return asyncio.run(link_property_to_alert(alert.id, request, property_id=env.props[prop_key].id,
                                              confirm_duplicate=confirm, db=env.db))


def _detail(env, user, alert, step=None, confirm_property=None):
    from app.web.routes.alerts import alert_detail
    query = urlencode({k: v for k, v in (("step", step), ("confirm_property", confirm_property)) if v})
    request = _request(env, user, f"/alerts/{alert.id}", query=query)
    response = asyncio.run(alert_detail(alert.id, request, step=step, confirm_property=confirm_property, db=env.db))
    return response, (response.body.decode("utf-8") if response.status_code == 200 else "")


def _reload(env, alert):
    from app.models.property_alert import PropertyAlert
    env.db.expire_all()
    return env.db.get(PropertyAlert, alert.id)


# ---------------------------------------------------------------------------
# Constantes y servicios puros
# ---------------------------------------------------------------------------

def test_propiedad_asociada_es_gestion_que_no_avanza_etapa():
    action = FollowUpActionType.PROPIEDAD_ASOCIADA
    assert action in FollowUpActionType.REPEATABLE_ACTIONS
    assert action not in FollowUpActionType.SYSTEM_ACTIONS
    assert FollowUpActionType.labels()[action] == "Propiedad asociada"
    assert FollowUpActionType.stage_badge_color(action) == "bg-blue-100 text-blue-700"
    # Solo lo escribe /link-property: el formulario de seguimiento no lo admite
    assert not FollowUpActionType.is_valid(action)


def test_perfil_guardado_es_gestion_que_no_avanza_etapa():
    action = FollowUpActionType.PERFIL_GUARDADO
    assert action in FollowUpActionType.REPEATABLE_ACTIONS
    assert action not in FollowUpActionType.SYSTEM_ACTIONS
    assert FollowUpActionType.labels()[action] == "Perfil guardado"
    assert FollowUpActionType.stage_badge_color(action) == "bg-blue-100 text-blue-700"
    # Solo lo escribe el guardado del perfil: el formulario no lo ofrece ni lo admite
    assert not FollowUpActionType.is_valid(action)
    assert action not in dict(FollowUpActionType.ordered_stages())
    # Gestión real para la cola y el cierre (alert_view)
    from app.services import alert_view
    follow_up = SimpleNamespace(action_type=action, created_at=T0 + timedelta(hours=1))
    assert alert_view.is_real_follow_up(follow_up)
    alert = SimpleNamespace(assigned_at=T0, created_at=T0)
    assert alert_view.has_follow_up_since_assignment([follow_up], alert)


def test_etapas_heredadas_fuera_del_formulario_pero_con_etiqueta_y_orden():
    """PLAN_RECORDATORIO_SIN_RESPUESTA.md §3.3: Primera llamada y Calificado."""
    order = FollowUpActionType.STAGE_ORDER
    form = dict(FollowUpActionType.ordered_stages())
    for legacy in ("PRIMERA_LLAMADA", "CALIFICADO"):
        assert legacy in FollowUpActionType.LEGACY_STAGES
        assert legacy not in form
        assert not FollowUpActionType.is_valid(legacy)
    assert FollowUpActionType.labels()["PRIMERA_LLAMADA"] == "Primera Llamada"
    assert FollowUpActionType.labels()["CALIFICADO"] == "Calificado"
    assert FollowUpActionType.stage_badge_color("CALIFICADO") == "bg-indigo-100 text-indigo-700"
    assert [v for v, _ in FollowUpActionType.progression_stages()] == [
        "SIN_RESPUESTA", "CONTACTADO", "VISITA_PROGRAMADA", "OFERTA"]
    # Orden coherente para los historiales antiguos
    assert order["SIN_RESPUESTA"] < order["PRIMERA_LLAMADA"] < order["CONTACTADO"] == order["CALIFICADO"]
    assert order["CONTACTADO"] < order["VISITA_PROGRAMADA"] < order["OFERTA"] < order["CERRADO"]
    for value in ("SIN_RESPUESTA", "CONTACTADO", "VISITA_PROGRAMADA", "OFERTA", "CERRADO", "SIN_INTERES"):
        assert FollowUpActionType.is_valid(value)


def test_resumen_del_perfil():
    from app.models.buyer_search_criteria import BuyerSearchCriteria
    from app.services.buyer_matching import criteria_summary, profile_note

    c = BuyerSearchCriteria(property_type="Piso", zones=["Centro"], cities=["Jaén", "Úbeda"],
                            min_bedrooms=2, max_bedrooms=3, max_price=150000, min_m2=300)
    assert criteria_summary(c) == "Piso · Centro, Jaén +1 · 2-3 dorm · ≤ 150.000 €"
    c.min_price, c.min_bathrooms, c.notes = 100000, 1, "Terraza"
    assert criteria_summary(c).endswith("≥ 1 baño · 100.000 € - 150.000 €")
    assert "m²" not in criteria_summary(c)
    assert profile_note(c).endswith("Imprescindibles: Terraza")
    assert criteria_summary(None) == "" and criteria_summary(BuyerSearchCriteria()) == ""


# ---------------------------------------------------------------------------
# Alcance por empresa
# ---------------------------------------------------------------------------

def test_scope_alerts_por_company_id(env):
    from app.models.property_alert import PropertyAlert
    from app.services.company_scope import get_alert_in_company, scope_alerts

    moes_buyer_alert = PropertyAlert(company_id=env.moes.id, origin=AlertOrigin.SEARCH, lead_name="MOES",
                                     agent_id=env.agents["ana"].id, created_by=env.admin.id,
                                     status=AlertStatus.PENDING, created_at=T0)
    env.db.add(moes_buyer_alert)
    env.db.commit()
    moyza_alert = _property_alert(env, "ana", "ana")

    assert moyza_alert.company_id == env.moyza.id  # heredada de la propiedad al crear
    in_moyza = {a.id for a in scope_alerts(env.db.query(PropertyAlert), env.moyza.id)}
    in_moes = {a.id for a in scope_alerts(env.db.query(PropertyAlert), env.moes.id)}
    assert moes_buyer_alert.id not in in_moyza and moes_buyer_alert.id in in_moes
    assert moyza_alert.id in in_moyza and moyza_alert.id not in in_moes
    assert get_alert_in_company(env.db, moes_buyer_alert.id, env.moyza.id) is None


def test_alta_solo_con_property_id_rellena_la_empresa(env):
    from app.models.property_alert import PropertyAlert
    alert = PropertyAlert(property_id=env.props["moes"].id, agent_id=env.agents["ana"].id, lead_name="X",
                          created_by=env.admin.id, status=AlertStatus.PENDING)
    env.db.add(alert)
    env.db.commit()
    assert alert.company_id == env.moes.id and alert.origin == AlertOrigin.PROPERTY


# ---------------------------------------------------------------------------
# Crear sin referencia
# ---------------------------------------------------------------------------

def test_admin_sin_agente_recibe_error(env):
    from app.models.property_alert import PropertyAlert
    response = _create(env, env.admin)
    assert response.status_code == 302 and response.headers["location"] == "/alerts"
    flash = _flash(response)
    assert flash["category"] == "error" and "elige el agente" in flash["message"]
    assert env.db.query(PropertyAlert).count() == 0


def test_admin_con_agente_crea_busqueda(env):
    from app.models.property_alert import PropertyAlert
    response = _create(env, env.admin, agent_id=str(env.agents["bea"].id))
    assert _flash(response) == {
        "category": "success",
        "message": "Búsqueda general creada para Juan Comprador y asignada a Agente Bea",
    }
    alert = env.db.query(PropertyAlert).one()
    assert alert.origin == AlertOrigin.SEARCH and alert.is_search
    assert alert.property_id is None and alert.company_id == env.moyza.id
    assert alert.agent_id == env.agents["bea"].id and alert.business_type == "Venta"

    # Aviso in-app al agente elegido: sin propiedad, "Búsqueda general · {operación}"
    from app.models.notification import Notification
    notice = env.db.query(Notification).filter_by(user_id=env.users["bea"].id, kind="alert_assigned").one()
    assert notice.body == "Búsqueda general · Venta" and notice.url == f"/alerts/{alert.id}"


def test_agente_queda_asignado_a_si_mismo(env):
    from app.models.property_alert import PropertyAlert
    response = _create(env, env.users["ana"])
    assert _flash(response)["category"] == "success"
    alert = env.db.query(PropertyAlert).one()
    assert alert.agent_id == env.agents["ana"].id and alert.origin == AlertOrigin.SEARCH

    # No puede asignarla a otro
    response = _create(env, env.users["ana"], agent_id=str(env.agents["bea"].id), business_type="Alquiler")
    assert _flash(response)["category"] == "error"
    assert env.db.query(PropertyAlert).count() == 1


def test_busqueda_duplicada_pide_confirmacion(env):
    from app.models.property_alert import PropertyAlert
    from app.web.routes.alerts import check_search_duplicate

    first = _search_alert(env, "ana")
    response = _create(env, env.users["ana"])
    flash = _flash(response)
    assert flash["category"] == "warning"
    assert f"ya tiene una búsqueda de Venta abierta (#{first.id}" in flash["message"]
    assert env.db.query(PropertyAlert).count() == 1

    # El modal consulta antes de enviar
    data = asyncio.run(check_search_duplicate(_request(env, env.users["ana"], "/alerts/check-search-duplicate"),
                                              buyer_id=env.buyer.id, business_type="Venta", db=env.db))
    import json
    payload = json.loads(data.body)
    assert [a["id"] for a in payload["open"]] == [first.id]

    # Otra operación no es duplicado
    _create(env, env.users["ana"], business_type="Alquiler")
    assert env.db.query(PropertyAlert).count() == 2

    # Confirmando, se crea y queda anotado
    response = _create(env, env.users["ana"], confirm_duplicate="1")
    assert _flash(response)["category"] == "success"
    newest = env.db.query(PropertyAlert).order_by(PropertyAlert.id.desc()).first()
    assert f"Búsqueda duplicada confirmada de la alerta #{first.id}" in newest.message


def test_con_referencia_sigue_igual(env):
    from app.models.property_alert import PropertyAlert
    _create(env, env.users["ana"], property_id=env.props["ana"].id)
    alert = env.db.query(PropertyAlert).one()
    assert alert.origin == AlertOrigin.PROPERTY and alert.company_id == env.moyza.id

    # El agente sigue sin poder crear alertas con referencia sobre propiedades ajenas
    response = _create(env, env.users["ana"], property_id=env.props["bea"].id, business_type="Alquiler")
    assert "Solo puedes crear alertas sobre las propiedades que tienes asignadas" in _flash(response)["message"]


# ---------------------------------------------------------------------------
# Perfil desde la alerta
# ---------------------------------------------------------------------------

def test_guardar_perfil_desde_la_alerta(env):
    from app.models.buyer_search_criteria import BuyerSearchCriteria
    from app.services import alert_view

    alert = _search_alert(env, "ana")
    later = _property_alert(env, "ana", "ana", created_at=T0 + timedelta(hours=1))
    assert alert_view.get_locked_alert_ids(env.agents["ana"].id, env.db, env.moyza.id) == {later.id}

    # Perfil antiguo con m²: se conserva, pero ya no se edita ni filtra
    env.db.add(BuyerSearchCriteria(buyer_id=env.buyer.id, min_m2=300, business_type="Alquiler"))
    env.db.commit()

    response = _save_profile(env, env.users["ana"], alert)
    assert response.status_code == 302
    assert response.headers["location"] == f"/alerts/{alert.id}?step=proposal"
    # Piso Centro (120.000, 2 dorm), Piso Bea (140.000, 3 dorm, de Bea) y Piso MOES
    # (de la otra empresa: PLAN_SUGERENCIAS_MULTIEMPRESA.md) encajan.
    # El perfil antiguo no estaba completo: primera vez = Contactado (PLAN_PERFIL_OBLIGATORIO.md)
    assert _flash(response) == {
        "category": "success",
        "message": "Perfil de Juan Comprador guardado y registrado como «Contactado»: 3 propiedades sugeridas",
    }

    stored = _reload(env, alert)
    criteria = env.db.query(BuyerSearchCriteria).filter_by(buyer_id=env.buyer.id).one()
    assert criteria.business_type == "Venta"  # la de la alerta
    assert criteria.agent_id == env.agents["ana"].id
    assert criteria.zones == ["Centro"] and criteria.cities == ["Jaen"]
    assert (criteria.min_bedrooms, criteria.max_bedrooms, criteria.min_bathrooms) == (2, 3, 1)
    assert float(criteria.max_price) == 150000 and criteria.notes == "Con terraza"
    assert float(criteria.min_m2) == 300

    # Ya no CALIFICADO (PLAN_RECORDATORIO_SIN_RESPUESTA.md §3.3). La primera vez que
    # el perfil queda completo es «Contactado»; las ediciones, «Perfil guardado»
    # (PLAN_PERFIL_OBLIGATORIO.md, decisión 5). Un solo seguimiento.
    assert not [f for f in stored.follow_ups if f.action_type == FollowUpActionType.CALIFICADO]
    assert [f.action_type for f in stored.follow_ups] == [FollowUpActionType.CONTACTADO]
    note = stored.follow_ups[0].notes
    assert note.startswith("Perfil de búsqueda: Piso · Centro, Jaen · 2-3 dorm")
    assert "Imprescindibles: Con terraza" in note
    assert stored.status == AlertStatus.IN_PROGRESS

    # Cuenta como gestión: desbloquea la cola
    assert alert_view.get_locked_alert_ids(env.agents["ana"].id, env.db, env.moyza.id) == set()


def test_perfil_rechazado_a_otro_agente_y_con_alerta_bloqueada(env):
    from app.models.buyer_search_criteria import BuyerSearchCriteria

    alert = _search_alert(env, "ana", created_at=T0 + timedelta(hours=1))

    response = _save_profile(env, env.users["bea"], alert)
    assert response.headers["location"] == "/alerts"
    assert _flash(response) == {"category": "error", "message": "No tienes permisos para esta alerta"}

    # Una alerta anterior de Ana sin gestión bloquea la búsqueda
    _property_alert(env, "ana", "ana", created_at=T0)
    response = _save_profile(env, env.users["ana"], alert)
    assert _flash(response) == {"category": "warning", "message": LOCKED_TEXT}
    assert env.db.query(BuyerSearchCriteria).count() == 0
    assert _reload(env, alert).follow_ups == []


def _add_follow_up(env, user, alert, action_type, notes=None, form=None):
    """POST /alerts/{id}/follow-up; `form`: campos del perfil (Contactado)."""
    from app.web.routes.alerts import add_follow_up
    body = dict(form or {})
    body.update(action_type=action_type, notes=notes or "")
    request = _request(env, user, f"/alerts/{alert.id}/follow-up", "POST", form=body)
    return asyncio.run(add_follow_up(alert.id, request, action_type=action_type, notes=notes,
                                     next_action_date=None, db=env.db))


# Perfil mínimo tal como lo envía el modal de seguimiento al elegir «Contactado»
# Mínimos del perfil (PLAN_PERFIL_ZONAS.md): población concreta y, como Jaen
# tiene la zona Centro, también la zona
CONTACT_PROFILE = {"cities": ["Jaen"], "zones": ["Centro"], "property_type": "Piso", "max_price": "150000"}


def test_formulario_rechaza_etapas_heredadas(env):
    alert = _property_alert(env, "ana", "ana")
    for legacy, label in (("PRIMERA_LLAMADA", "Primera Llamada"), ("CALIFICADO", "Calificado")):
        response = _add_follow_up(env, env.users["ana"], alert, legacy)
        assert response.headers["location"] == f"/alerts/{alert.id}"
        assert _flash(response) == {"category": "error",
                                    "message": f"«{label}» ya no se registra como seguimiento. Elige otra etapa."}
    assert _reload(env, alert).follow_ups == []
    # Las propias del sistema tampoco se admiten por el formulario
    response = _add_follow_up(env, env.users["ana"], alert, FollowUpActionType.PERFIL_GUARDADO)
    assert _flash(response) == {"category": "error", "message": "Tipo de acción no válido"}

    # Contactado lleva el perfil dentro (PLAN_PERFIL_OBLIGATORIO.md)
    response = _add_follow_up(env, env.users["ana"], alert, "CONTACTADO", form=CONTACT_PROFILE)
    assert _flash(response)["category"] == "success"
    assert [f.action_type for f in _reload(env, alert).follow_ups] == ["CONTACTADO"]


def test_historial_antiguo_se_pinta_y_el_select_no_ofrece_heredadas(env):
    from app.models.alert_follow_up import AlertFollowUp

    alert = _property_alert(env, "ana", "ana")
    for i, action in enumerate(("PRIMERA_LLAMADA", "CALIFICADO", "PERFIL_GUARDADO")):
        env.db.add(AlertFollowUp(alert_id=alert.id, action_type=action, created_by=env.users["ana"].id,
                                 created_at=T0 + timedelta(hours=i + 1)))
    env.db.commit()

    response, html = _detail(env, env.admin, alert)
    assert response.status_code == 200
    assert "Primera Llamada" in html and "Calificado" in html and "Perfil guardado" in html
    assert "bg-indigo-100 text-indigo-700" in html
    assert 'value="PRIMERA_LLAMADA"' not in html and 'value="CALIFICADO"' not in html
    assert 'value="PERFIL_GUARDADO"' not in html
    assert '<option value="SIN_RESPUESTA">' in html and '<option value="CONTACTADO">' in html
    # El JS de notas obligatorias conoce los cuatro cierres
    assert '"NO_APTO_PROPIETARIO"' in html


def test_perfil_guardado_no_avanza_la_etapa_del_listado(env):
    from app.models.alert_follow_up import AlertFollowUp
    from app.web.routes.alerts import alerts_page

    alert = _search_alert(env, "ana")
    env.db.add(AlertFollowUp(alert_id=alert.id, action_type="CONTACTADO", created_by=env.users["ana"].id,
                             created_at=T0 + timedelta(hours=1)))
    env.db.commit()
    # Perfil ya completo: guardarlo otra vez es una edición («Perfil guardado»)
    _complete_profile(env)
    assert _save_profile(env, env.users["ana"], alert).status_code == 302
    assert [f.action_type for f in _reload(env, alert).follow_ups].count("PERFIL_GUARDADO") == 1

    response = asyncio.run(alerts_page(
        _request(env, env.users["ana"], "/alerts"), q="", status_filter=[], agent_id=None,
        page=None, per_page=None, b_q="", b_page=None, db=env.db,
    ))
    assert response.context["alert_stages"][alert.id]["value"] == "CONTACTADO"


# ---------------------------------------------------------------------------
# Sugerencias
# ---------------------------------------------------------------------------

def test_sugerencias_sin_m2_de_la_empresa_y_de_cualquier_agente(env):
    from app.models.buyer_search_criteria import BuyerSearchCriteria
    from app.services.buyer_matching import matching_properties

    criteria = BuyerSearchCriteria(buyer_id=env.buyer.id, business_type="Venta", max_price=200000,
                                   min_m2=300, max_m2=310)
    titles = [p.title for p in matching_properties(env.db, criteria, env.moyza.id)]
    # Sin filtro de m², de Ana y de Bea, ordenadas por precio; con empresa, solo esa
    # ("Solo {empresa}", PLAN_SUGERENCIAS_MULTIEMPRESA.md)
    assert titles == ["Piso Centro", "Piso Bea"]
    assert [p.title for p in matching_properties(env.db, criteria, env.moes.id)] == ["Piso MOES"]
    # Sin empresa: las dos (PLAN_SUGERENCIAS_MULTIEMPRESA.md), por precio y sin agrupar
    assert [p.title for p in matching_properties(env.db, criteria)] == ["Piso Centro", "Piso MOES", "Piso Bea"]


def test_buscador_con_alert_id_devuelve_toda_la_empresa(env):
    import json
    from app.web.routes.alerts import search_properties

    alert = _search_alert(env, "ana")

    def titles(user, alert_id=None):
        request = _request(env, user, "/alerts/search-properties")
        response = asyncio.run(search_properties(request, q="Piso", alert_id=alert_id, db=env.db))
        return sorted(r["title"] for r in json.loads(response.body)["results"])

    # Sin perfil completo no se puede asociar: regla de siempre (PLAN_PERFIL_OBLIGATORIO.md)
    assert titles(env.users["ana"], str(alert.id)) == ["Piso Centro"]

    _complete_profile(env)
    assert titles(env.users["ana"]) == ["Piso Centro"]                      # regla de siempre
    # Con alert_id: las dos empresas (PLAN_SUGERENCIAS_MULTIEMPRESA.md)
    assert titles(env.users["ana"], str(alert.id)) == ["Piso Bea", "Piso Centro", "Piso MOES"]
    assert titles(env.users["bea"], str(alert.id)) == ["Piso Bea"]          # no es su búsqueda


# ---------------------------------------------------------------------------
# Asociar y cambiar propiedad
# ---------------------------------------------------------------------------

def test_asociar_y_cambiar_propiedad(env):
    alert = _search_alert(env, "ana")
    _complete_profile(env)

    response = _link(env, env.users["ana"], alert, "bea")
    assert response.headers["location"] == f"/alerts/{alert.id}"
    assert _flash(response)["message"] == "Piso Bea asociada a la búsqueda de Juan Comprador"
    stored = _reload(env, alert)
    assert stored.property_id == env.props["bea"].id and stored.property_linked_at is not None
    # La alerta sigue con quien atiende al comprador (decisión 2)
    assert stored.agent_id == env.agents["ana"].id and stored.company_id == env.moyza.id
    notes = [f.notes for f in stored.follow_ups if f.action_type == FollowUpActionType.PROPIEDAD_ASOCIADA]
    assert notes == ["Propiedad asociada: Piso Bea"]
    assert stored.status == AlertStatus.IN_PROGRESS

    response = _link(env, env.users["ana"], alert, "ana")
    assert _flash(response)["message"].startswith("Propiedad cambiada")
    stored = _reload(env, alert)
    assert stored.property_id == env.props["ana"].id
    notes = sorted(f.notes for f in stored.follow_ups if f.action_type == FollowUpActionType.PROPIEDAD_ASOCIADA)
    assert "Cambio de propiedad: de Piso Bea a Piso Centro" in notes

    # Otra empresa: se puede asociar (PLAN_SUGERENCIAS_MULTIEMPRESA.md); la alerta
    # sigue en MOYZA. Detalle en tests/test_sugerencias_multiempresa.py
    response = _link(env, env.users["ana"], alert, "moes")
    assert _flash(response)["category"] == "success"
    assert _reload(env, alert).company_id == env.moyza.id


def test_asociar_duplicado_exige_confirmacion(env):
    alert = _search_alert(env, "ana")
    other = _property_alert(env, "bea", "bea", created_at=T0 - timedelta(days=1))
    _complete_profile(env)

    response = _link(env, env.users["ana"], alert, "bea")
    assert response.headers["location"] == (
        f"/alerts/{alert.id}?step=proposal&confirm_property={env.props['bea'].id}#propuesta"
    )
    assert _flash(response)["category"] == "warning"
    assert _reload(env, alert).property_id is None

    # El detalle pinta el aviso con "Asociar de todas formas"
    _, html = _detail(env, env.users["ana"], alert, step="proposal", confirm_property=str(env.props["bea"].id))
    assert "ya tiene una alerta abierta sobre Piso Bea" in html and "Asociar de todas formas" in html
    assert f'href="/alerts/{other.id}"' not in html  # la otra es de Bea: Ana no la abre

    response = _link(env, env.users["ana"], alert, "bea", confirm="1")
    assert _flash(response)["category"] == "success"
    stored = _reload(env, alert)
    assert stored.property_id == env.props["bea"].id
    assert f"alerta abierta #{other.id}" in stored.message


def test_alerta_con_referencia_cambia_de_propiedad_solo_con_perfil(env):
    """PLAN_PERFIL_OBLIGATORIO.md: el origen ya no cuenta; el perfil completo sí."""
    alert = _property_alert(env, "ana", "ana")
    response = _link(env, env.users["ana"], alert, "bea")
    assert response.headers["location"] == f"/alerts/{alert.id}?step=profile#propuesta"
    assert _flash(response) == {"category": "error", "message": "Registra primero el perfil del comprador"}
    assert _reload(env, alert).property_id == env.props["ana"].id

    _complete_profile(env)
    response = _link(env, env.users["ana"], alert, "bea")
    assert _flash(response)["category"] == "success"
    stored = _reload(env, alert)
    assert stored.property_id == env.props["bea"].id and stored.origin == AlertOrigin.PROPERTY
    assert stored.agent_id == env.agents["ana"].id


def test_metricas_por_agente_cuentan_busquedas_sin_propiedad(env):
    from app.models.alert_follow_up import AlertFollowUp
    from app.services.performance_report_service import PerformanceReportService

    search = _search_alert(env, "ana", created_at=T0)
    _property_alert(env, "bea", "bea", created_at=T0)
    env.db.add(AlertFollowUp(alert_id=search.id, action_type=FollowUpActionType.CERRADO, notes="Cerrado",
                             created_at=T0 + timedelta(days=1), created_by=env.users["ana"].id))
    env.db.commit()

    svc = PerformanceReportService(env.db, env.moyza.id)
    agents = [env.agents["ana"].id, env.agents["bea"].id]
    start, end = T0 - timedelta(days=1), T0 + timedelta(days=5)
    contacts = svc.grouped_counts("contactos", start, end, agents)
    closings = svc.grouped_counts("cierres", start, end, agents)
    assert contacts[(env.agents["ana"].id, None)]["venta"] == 1   # la búsqueda, sin propiedad
    assert contacts[(env.agents["bea"].id, None)]["venta"] == 1
    assert closings[(env.agents["ana"].id, None)]["venta"] == 1   # tipo de la alerta (OUTER JOIN)
    # En MOES no cuenta nada de MOYZA
    assert PerformanceReportService(env.db, env.moes.id).grouped_counts("contactos", start, end, agents) == {}


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

def _list_html(env, user, q=""):
    from app.web.routes.alerts import alerts_page
    request = _request(env, user, "/alerts", query=urlencode({"q": q}) if q else "")
    response = asyncio.run(alerts_page(request, q=q, status_filter=[], agent_id=None, page=None,
                                       per_page=None, b_q="", b_page=None, db=env.db))
    return response.body.decode("utf-8")


def test_listado_muestra_busqueda_general(env):
    from app.models.buyer_search_criteria import BuyerSearchCriteria
    alert = _search_alert(env, "ana")
    env.db.add(BuyerSearchCriteria(buyer_id=env.buyer.id, property_type="Piso", cities=["Jaen"],
                                   min_bedrooms=2, max_bedrooms=3, max_price=150000))
    env.db.commit()

    html = _list_html(env, env.admin)
    assert "Búsqueda general" in html
    assert "Piso · Jaen · 2-3 dorm · ≤ 150.000 €" in html
    assert f'href="/alerts/{alert.id}"' in html
    # El flujo "Agregar alerta con filtro" ya no existe; el modal tiene Con/Sin referencia
    assert "Agregar alerta con filtro" not in html and "filterAlertModal" not in html
    assert "Con referencia" in html and "Sin referencia" in html

    # El buscador por texto encuentra la búsqueda sin propiedad (OUTER JOIN)
    assert f'href="/alerts/{alert.id}"' in _list_html(env, env.users["ana"], q="Juan")


def test_detalle_tres_pasos_perfil_sin_m2_sugerencias_y_cambio(env):
    alert = _search_alert(env, "ana")

    # Recién creada: cabecera "Búsqueda general" y paso Contactar
    response, html = _detail(env, env.users["ana"], alert)
    assert response.status_code == 200 and response.context["step"] == "contact"
    for label in ("1. Contactar", "2. Perfil", "3. Propuesta", "Búsqueda general", "Registrar seguimiento"):
        assert label in html, label

    # Perfil: formulario inline sin m², con la operación de la alerta precargada y
    # editable (PLAN_PERFIL_UBICACION.md: si cambia, cambia la de la alerta)
    response, html = _detail(env, env.users["ana"], alert, step="profile")
    assert f'action="/alerts/{alert.id}/search-profile"' in html
    assert "Guardar perfil y ver propiedades" in html
    assert 'name="min_m2"' not in html and 'name="max_m2"' not in html and "m²" not in html
    assert '<select name="business_type" id="spBusinessType" required' in html
    assert '<option value="Venta" selected>Venta</option>' in html
    assert "Si la cambias, cambia la operación de la alerta" in html
    # Sin perfil: poblaciones sin marcar y zonas ocultas hasta marcar una (PLAN_PERFIL_ZONAS.md)
    assert 'name="cities" value="Jaen"' in html and 'name="zones" value="Centro"' not in html

    # Tras guardar el perfil: Propuesta con sugerencias de cualquier agente
    _save_profile(env, env.users["ana"], alert)
    response, html = _detail(env, env.users["ana"], alert)
    assert response.context["step"] == "proposal"
    # De las dos empresas (PLAN_SUGERENCIAS_MULTIEMPRESA.md)
    assert [p.title for p in response.context["suggestions"]] == ["Piso Centro", "Piso MOES", "Piso Bea"]
    assert html.count("Asociar a esta alerta") >= 2
    assert "Agente de la propiedad: Agente Bea" in html
    # Sin enlace "Ver" a la ficha de la propiedad de Bea; sí a la suya
    assert f'href="/properties/{env.props["ana"].id}"' in html
    assert f'href="/properties/{env.props["bea"].id}"' not in html
    assert "¿No está en la lista?" in html

    # Tras asociar: tarjeta de propiedad y "Cambiar propiedad"; los pasos siguen
    # (PLAN_PERFIL_OBLIGATORIO.md: en todas las alertas), en Propuesta
    _link(env, env.users["ana"], alert, "bea")
    response, html = _detail(env, env.users["ana"], alert)
    assert response.context["show_steps"] is True and response.context["step"] == "proposal"
    assert "Piso Bea" in html and "Cambiar propiedad" in html and "1. Contactar" in html

    # "Cambiar propiedad": paso Propuesta con la actual marcada
    response, html = _detail(env, env.users["ana"], alert, step="proposal")
    assert response.context["show_steps"] is True
    assert "Asociada ahora" in html and html.count("Asociar a esta alerta") >= 1


def test_detalle_admin_y_alerta_cerrada(env):
    alert = _search_alert(env, "bea")
    response, html = _detail(env, env.admin, alert)
    assert response.context["show_steps"] is True and 'id="alertAssignment"' in html
    assert "Búsqueda general: sin propiedad asociada" in html

    alert.status = AlertStatus.COMPLETED
    env.db.commit()
    response, html = _detail(env, env.admin, alert)
    assert response.context["show_steps"] is False and "Cambiar propiedad" not in html
    assert "Búsqueda general" in html


def test_ficha_del_comprador_sin_m2_y_con_busqueda(env):
    from app.models.buyer_search_criteria import BuyerSearchCriteria
    from app.web.routes.alerts import buyer_detail

    _search_alert(env, "ana")
    env.db.add(BuyerSearchCriteria(buyer_id=env.buyer.id, business_type="Venta", min_m2=300, cities=["Jaen"]))
    env.db.commit()
    for tab in ("criteria", "matches", "alerts"):
        request = _request(env, env.admin, f"/buyers/{env.buyer.id}", query=f"tab={tab}")
        response = asyncio.run(buyer_detail(env.buyer.id, request, tab=tab, db=env.db))
        html = response.body.decode("utf-8")
        assert response.status_code == 200
        assert 'name="min_m2"' not in html and "m²" not in html
        assert "Búsqueda general" in html
        # El perfil con m² antiguo ya no filtra: las tres de Venta de MOYZA y la de MOES
        # (PLAN_SUGERENCIAS_MULTIEMPRESA.md)
        assert [p.title for p in response.context["matching_properties"]] == [
            "Piso Centro", "Piso MOES", "Piso Bea", "Casa Cara"]


# ---------------------------------------------------------------------------
# Migración
# ---------------------------------------------------------------------------

def test_migracion_presente_y_sql_offline():
    path = BACKEND / "alembic" / "versions" / "y8z9a0b1c2d3_alert_without_property.py"
    text = path.read_text(encoding="utf-8")
    assert "revision = 'y8z9a0b1c2d3'" in text and "down_revision = 'x7y8z9a0b1c2'" in text

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "x7y8z9a0b1c2:y8z9a0b1c2d3", "--sql"],
        cwd=BACKEND, capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        pytest.skip(f"alembic --sql no disponible aquí: {result.stderr[-300:]}")
    sql = result.stdout
    assert "UPDATE property_alerts SET company_id = (SELECT company_id FROM properties" in sql
    assert "ALTER COLUMN company_id SET NOT NULL" in sql
    assert "ALTER COLUMN property_id DROP NOT NULL" in sql
    assert "ADD COLUMN origin VARCHAR DEFAULT 'property' NOT NULL" in sql
    assert "ADD COLUMN property_linked_at" in sql
    assert "CREATE INDEX ix_property_alerts_company_id" in sql
