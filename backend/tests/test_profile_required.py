"""
Perfil y propuesta en TODAS las alertas, perfil obligatorio al contactar y
bloqueo de etapas avanzadas sin perfil (PLAN_PERFIL_OBLIGATORIO.md).

Rutas en proceso contra una SQLite en memoria con los modelos reales; mismo
entorno y helpers que tests/test_alert_search.py (MOYZA y MOES, admin, Ana y
Bea, comprador Juan de Ana; Piso Centro de Ana 120.000 €, Piso Bea 140.000 €,
Casa Cara de Bea 500.000 €). Cada test parte de una base nueva.

    cd backend && python -m pytest tests/test_profile_required.py -q
"""
import asyncio
import json
from datetime import timedelta

import pytest

from app.core.constants import AlertOrigin, AlertStatus, FollowUpActionType
from app.services import buyer_matching
from tests.test_alert_search import (  # noqa: F401  (env es un fixture)
    CONTACT_PROFILE,
    T0,
    _add_follow_up,
    _complete_profile,
    _detail,
    _flash,
    _link,
    _list_html,
    _property_alert,
    _reload,
    _request,
    _save_profile,
    _search_alert,
    env,
)


PROFILE_STEP = "?step=profile#propuesta"


def _criteria(env):
    from app.models.buyer_search_criteria import BuyerSearchCriteria
    env.db.expire_all()
    return env.db.query(BuyerSearchCriteria).filter_by(buyer_id=env.buyer.id).one_or_none()


def _actions(env, alert):
    return sorted(f.action_type for f in _reload(env, alert).follow_ups)


# ---------------------------------------------------------------------------
# Definición única de "perfil completo"
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fields, missing", [
    (None, ["tipo de inmueble", "precio máximo", "ubicación"]),
    ({}, ["tipo de inmueble", "precio máximo", "ubicación"]),
    ({"property_type": "Piso"}, ["precio máximo", "ubicación"]),
    ({"property_type": "  ", "max_price": 150000, "zones": ["Centro"]}, ["tipo de inmueble"]),
    ({"property_type": "Piso", "max_price": 150000}, ["ubicación"]),
    ({"property_type": "Piso", "max_price": 0, "cities": ["Jaen"]}, ["precio máximo"]),
    ({"property_type": "Piso", "max_price": 150000, "zones": [], "cities": []}, ["ubicación"]),
    ({"property_type": "Piso", "max_price": 150000, "zones": ["Centro"]}, []),
    ({"property_type": "Piso", "max_price": 150000, "cities": ["Jaen"]}, []),
    # Opcionales: no cuentan
    ({"min_price": 1, "min_bedrooms": 2, "min_bathrooms": 1, "notes": "Terraza"},
     ["tipo de inmueble", "precio máximo", "ubicación"]),
])
def test_perfil_completo_y_lo_que_falta(fields, missing):
    from app.models.buyer_search_criteria import BuyerSearchCriteria
    criteria = None if fields is None else BuyerSearchCriteria(**fields)
    assert buyer_matching.missing_profile_fields(criteria) == missing
    assert buyer_matching.profile_is_complete(criteria) is (not missing)


def test_texto_de_lo_que_falta():
    assert buyer_matching.missing_profile_text(["tipo de inmueble", "precio máximo"]) == \
        "tipo de inmueble, precio máximo"


def test_etapas_que_exigen_perfil():
    required = FollowUpActionType.PROFILE_REQUIRED_STAGES
    assert required == {"VISITA_PROGRAMADA", "OFERTA", "CERRADO"}
    # Se registran sin perfil: Sin respuesta y los cierres negativos; Contactado lo lleva dentro
    for free in ("SIN_RESPUESTA", "SIN_INTERES", "SIN_SOLVENCIA_ECONOMICA", "NO_APTO_PROPIETARIO", "CONTACTADO"):
        assert free not in required
    assert required <= FollowUpActionType.values()


# ---------------------------------------------------------------------------
# add_follow_up: bloqueos
# ---------------------------------------------------------------------------

def test_sin_respuesta_sin_perfil_se_registra(env):
    alert = _property_alert(env, "ana", "ana")
    response = _add_follow_up(env, env.users["ana"], alert, "SIN_RESPUESTA")
    assert _flash(response) == {"category": "success", "message": "Seguimiento agregado correctamente"}
    assert _actions(env, alert) == ["SIN_RESPUESTA"]
    assert _criteria(env) is None


@pytest.mark.parametrize("action, label", [
    ("VISITA_PROGRAMADA", "Visita Programada"),
    ("OFERTA", "Oferta/Negociación"),
    ("CERRADO", "Cerrado (éxito)"),
])
def test_etapas_avanzadas_sin_perfil_rechazadas(env, action, label):
    alert = _property_alert(env, "ana", "ana")
    response = _add_follow_up(env, env.users["ana"], alert, action, notes="Nota de cierre")
    assert response.headers["location"] == f"/alerts/{alert.id}{PROFILE_STEP}"
    assert _flash(response) == {
        "category": "error",
        "message": f"Registra primero el perfil del comprador (seguimiento Contactado) para poder marcar «{label}»",
    }
    stored = _reload(env, alert)
    assert stored.follow_ups == [] and stored.status == AlertStatus.PENDING and stored.completed_at is None


def test_etapas_avanzadas_tampoco_para_el_admin(env):
    alert = _search_alert(env, "bea")
    response = _add_follow_up(env, env.admin, alert, "VISITA_PROGRAMADA")
    assert _flash(response)["category"] == "error"
    assert _reload(env, alert).follow_ups == []


def test_perfil_incompleto_tambien_bloquea(env):
    """Un perfil antiguo sin los mínimos cuenta como pendiente (decisión 6)."""
    _complete_profile(env, max_price=None)
    alert = _property_alert(env, "ana", "ana")
    response = _add_follow_up(env, env.users["ana"], alert, "OFERTA")
    assert _flash(response)["category"] == "error"
    assert _reload(env, alert).follow_ups == []


@pytest.mark.parametrize("action", ["SIN_INTERES", "SIN_SOLVENCIA_ECONOMICA", "NO_APTO_PROPIETARIO"])
def test_cierres_negativos_sin_perfil(env, action):
    alert = _property_alert(env, "ana", "ana")
    response = _add_follow_up(env, env.users["ana"], alert, action, notes="No le interesa")
    assert _flash(response)["category"] == "success" and response.headers["location"] == "/alerts"
    stored = _reload(env, alert)
    assert stored.status == AlertStatus.COMPLETED and _actions(env, alert) == [action]


def test_con_perfil_completo_se_registran_las_etapas_avanzadas(env):
    _complete_profile(env)
    alert = _property_alert(env, "ana", "ana")
    for action in ("VISITA_PROGRAMADA", "OFERTA"):
        assert _flash(_add_follow_up(env, env.users["ana"], alert, action))["category"] == "success"
    response = _add_follow_up(env, env.users["ana"], alert, "CERRADO", notes="Vendida")
    assert _flash(response) == {"category": "success", "message": "Alerta cerrada con éxito"}
    assert _reload(env, alert).status == AlertStatus.COMPLETED


def test_alerta_sin_comprador_queda_fuera_del_requisito(env):
    """Sin comprador no hay dónde guardar el perfil: no se bloquea (decisión documentada)."""
    from app.models.property_alert import PropertyAlert
    from app.services import alert_assignment_service as svc
    alert = PropertyAlert(property=env.props["ana"], lead_name="Antigua sin comprador", business_type="Venta",
                          status=AlertStatus.IN_PROGRESS, priority="NORMAL", created_by=env.admin.id, created_at=T0)
    env.db.add(alert)
    svc.assign(env.db, alert, env.agents["ana"], env.admin, None, is_new=True, now=T0)
    env.db.commit()
    for action in ("CONTACTADO", "VISITA_PROGRAMADA"):
        assert _flash(_add_follow_up(env, env.users["ana"], alert, action))["category"] == "success"
    assert _actions(env, alert) == ["CONTACTADO", "VISITA_PROGRAMADA"]


# ---------------------------------------------------------------------------
# add_follow_up: Contactado lleva el perfil
# ---------------------------------------------------------------------------

def test_contactado_sin_campos_ni_perfil_rechazado(env):
    alert = _property_alert(env, "ana", "ana")
    response = _add_follow_up(env, env.users["ana"], alert, "CONTACTADO", notes="Hablado")
    assert response.headers["location"] == f"/alerts/{alert.id}{PROFILE_STEP}"
    assert _flash(response) == {
        "category": "error",
        "message": "Para registrar «Contactado» completa el perfil del comprador. "
                   "Falta: tipo de inmueble, precio máximo, ubicación",
    }
    assert _reload(env, alert).follow_ups == [] and _criteria(env) is None


def test_contactado_con_perfil_a_medias_rechazado(env):
    alert = _property_alert(env, "ana", "ana")
    response = _add_follow_up(env, env.users["ana"], alert, "CONTACTADO",
                              form={"property_type": "Piso", "min_bedrooms": "2"})
    assert _flash(response)["message"].endswith("Falta: precio máximo, ubicación")
    assert _reload(env, alert).follow_ups == [] and _criteria(env) is None


def test_contactado_con_minimos_guarda_perfil_y_un_solo_seguimiento(env):
    from app.services import alert_view
    alert = _property_alert(env, "ana", "ana")
    later = _property_alert(env, "bea", "ana", created_at=T0 + timedelta(hours=1))
    assert alert_view.get_locked_alert_ids(env.agents["ana"].id, env.db, env.moyza.id) == {later.id}

    form = dict(CONTACT_PROFILE, cities=["Jaen"], min_bedrooms="2", profile_notes="Con ascensor")
    response = _add_follow_up(env, env.users["ana"], alert, "CONTACTADO", notes="Le interesa la zona", form=form)
    assert response.headers["location"] == f"/alerts/{alert.id}"
    assert _flash(response) == {"category": "success",
                                "message": "«Contactado» registrado con el perfil de Juan Comprador"}

    criteria = _criteria(env)
    assert buyer_matching.profile_is_complete(criteria)
    assert (criteria.property_type, float(criteria.max_price)) == ("Piso", 150000)
    assert criteria.zones == ["Centro"] and criteria.cities == ["Jaen"] and criteria.min_bedrooms == 2
    assert criteria.notes == "Con ascensor"                      # imprescindibles, no la nota del seguimiento
    assert criteria.business_type == "Venta" and criteria.agent_id == env.agents["ana"].id

    stored = _reload(env, alert)
    assert [f.action_type for f in stored.follow_ups] == ["CONTACTADO"]   # sin PERFIL_GUARDADO aparte
    note = stored.follow_ups[0].notes
    assert note == ("Le interesa la zona\n"
                    "Perfil de búsqueda: Piso · Centro, Jaen · ≥ 2 dorm · ≤ 150.000 €. Imprescindibles: Con ascensor")
    assert stored.status == AlertStatus.IN_PROGRESS
    # Gestión real: desbloquea la cola
    assert alert_view.get_locked_alert_ids(env.agents["ana"].id, env.db, env.moyza.id) == set()

    # Ya puede programar la visita
    assert _flash(_add_follow_up(env, env.users["ana"], alert, "VISITA_PROGRAMADA"))["category"] == "success"


def test_contactado_sin_nota_del_agente_lleva_solo_el_resumen(env):
    alert = _property_alert(env, "ana", "ana")
    _add_follow_up(env, env.users["ana"], alert, "CONTACTADO", form=CONTACT_PROFILE)
    [follow_up] = _reload(env, alert).follow_ups
    assert follow_up.notes == "Perfil de búsqueda: Piso · Centro · ≤ 150.000 €."


def test_contactado_con_perfil_completo_y_campos_vacios_no_borra_el_perfil(env):
    _complete_profile(env, cities=["Jaen"], notes="Terraza")
    alert = _property_alert(env, "ana", "ana")
    response = _add_follow_up(env, env.users["ana"], alert, "CONTACTADO", notes="Segunda llamada")
    assert _flash(response) == {"category": "success", "message": "Seguimiento agregado correctamente"}

    criteria = _criteria(env)
    assert (criteria.property_type, float(criteria.max_price)) == ("Piso", 200000)
    assert criteria.zones == ["Centro"] and criteria.cities == ["Jaen"] and criteria.notes == "Terraza"
    [follow_up] = _reload(env, alert).follow_ups
    assert follow_up.action_type == "CONTACTADO" and follow_up.notes == "Segunda llamada"


def test_contactado_edita_el_perfil_completo(env):
    _complete_profile(env)
    alert = _property_alert(env, "ana", "ana")
    form = dict(CONTACT_PROFILE, max_price="130000")
    assert _flash(_add_follow_up(env, env.users["ana"], alert, "CONTACTADO", form=form))["category"] == "success"
    assert float(_criteria(env).max_price) == 130000
    assert _actions(env, alert) == ["CONTACTADO"]


def test_contactado_no_deja_un_perfil_completo_a_medias(env):
    _complete_profile(env)
    alert = _property_alert(env, "ana", "ana")
    # Desmarca zonas y ciudades pero envía el resto: la edición dejaría el perfil incompleto
    response = _add_follow_up(env, env.users["ana"], alert, "CONTACTADO",
                              form={"property_type": "Piso", "max_price": "150000"})
    assert _flash(response)["message"].endswith("Falta: ubicación")
    assert _criteria(env).zones == ["Centro"] and _reload(env, alert).follow_ups == []


# ---------------------------------------------------------------------------
# Paso Perfil: primera vez = Contactado; ediciones = Perfil guardado
# ---------------------------------------------------------------------------

def test_paso_perfil_primera_vez_contactado_y_despues_perfil_guardado(env):
    alert = _property_alert(env, "ana", "ana")

    response = _save_profile(env, env.users["ana"], alert)
    assert response.headers["location"] == f"/alerts/{alert.id}?step=proposal"
    assert "registrado como «Contactado»" in _flash(response)["message"]
    assert _actions(env, alert) == ["CONTACTADO"]

    response = _save_profile(env, env.users["ana"], alert, form=dict(CONTACT_PROFILE, max_price="160000"))
    # Piso Centro, Piso Bea y Piso MOES (dos empresas, PLAN_SUGERENCIAS_MULTIEMPRESA.md)
    assert _flash(response)["message"] == "Perfil de Juan Comprador guardado: 3 propiedades sugeridas"
    assert _actions(env, alert) == ["CONTACTADO", "PERFIL_GUARDADO"]
    assert float(_criteria(env).max_price) == 160000


def test_paso_perfil_con_perfil_completo_de_la_ficha_es_edicion(env):
    """El perfil es del comprador: si ya estaba completo (otra alerta, la ficha), es una edición."""
    _complete_profile(env)
    alert = _property_alert(env, "ana", "ana")
    _save_profile(env, env.users["ana"], alert)
    assert _actions(env, alert) == ["PERFIL_GUARDADO"]


def test_paso_perfil_sin_minimos_no_guarda(env):
    alert = _property_alert(env, "ana", "ana")
    response = _save_profile(env, env.users["ana"], alert,
                             form={"property_type": "Piso", "max_price": "150000"})
    assert response.headers["location"] == f"/alerts/{alert.id}{PROFILE_STEP}"
    assert _flash(response) == {"category": "error", "message": "Faltan datos del perfil: ubicación"}
    assert _criteria(env) is None and _reload(env, alert).follow_ups == []


def test_paso_perfil_en_alerta_con_referencia(env):
    """El origen ya no cuenta: una alerta con referencia guarda perfil como una búsqueda."""
    alert = _property_alert(env, "ana", "ana")
    assert alert.origin == AlertOrigin.PROPERTY
    assert _save_profile(env, env.users["ana"], alert).headers["location"].endswith("?step=proposal")
    assert buyer_matching.profile_is_complete(_criteria(env))


# ---------------------------------------------------------------------------
# Asociar / cambiar propiedad en una alerta con referencia
# ---------------------------------------------------------------------------

def test_cambiar_propiedad_de_alerta_con_referencia(env):
    alert = _property_alert(env, "ana", "ana")

    # Sin perfil: rechazado, al paso Perfil
    response = _link(env, env.users["ana"], alert, "bea")
    assert response.headers["location"] == f"/alerts/{alert.id}{PROFILE_STEP}"
    assert _flash(response) == {"category": "error", "message": "Registra primero el perfil del comprador"}
    assert _reload(env, alert).property_id == env.props["ana"].id

    # Con perfil: cambia a la de Bea; el agente sigue siendo Ana
    _add_follow_up(env, env.users["ana"], alert, "CONTACTADO", form=CONTACT_PROFILE)
    response = _link(env, env.users["ana"], alert, "bea")
    assert _flash(response)["message"] == "Propiedad cambiada: Juan Comprador ahora tiene asociada Piso Bea"
    stored = _reload(env, alert)
    assert stored.property_id == env.props["bea"].id and stored.property_linked_at is not None
    assert stored.agent_id == env.agents["ana"].id and stored.origin == AlertOrigin.PROPERTY
    notes = [f.notes for f in stored.follow_ups if f.action_type == FollowUpActionType.PROPIEDAD_ASOCIADA]
    assert notes == ["Cambio de propiedad: de Piso Centro a Piso Bea"]


def test_buscador_de_la_propuesta_en_alerta_con_referencia(env):
    from app.web.routes.alerts import search_properties
    alert = _property_alert(env, "ana", "ana")

    def titles():
        request = _request(env, env.users["ana"], "/alerts/search-properties")
        response = asyncio.run(search_properties(request, q="Piso", alert_id=str(alert.id), db=env.db))
        return sorted(r["title"] for r in json.loads(response.body)["results"])

    assert titles() == ["Piso Centro"]                # sin perfil: solo las suyas
    _complete_profile(env)
    assert titles() == ["Piso Bea", "Piso Centro", "Piso MOES"]    # con perfil: las dos empresas


# ---------------------------------------------------------------------------
# Render del detalle de una alerta con referencia
# ---------------------------------------------------------------------------

def test_detalle_con_referencia_sin_perfil(env):
    alert = _property_alert(env, "ana", "ana")
    response, html = _detail(env, env.users["ana"], alert)
    ctx = response.context
    assert response.status_code == 200
    assert ctx["show_steps"] is True and ctx["step"] == "contact"
    assert ctx["profile_complete"] is False
    assert ctx["profile_missing"] == ["tipo de inmueble", "precio máximo", "ubicación"]

    # Indicador de pasos, banner y tarjeta de la propiedad ARRIBA de los pasos
    for text in ("1. Contactar", "2. Perfil", "3. Propuesta", "Perfil pendiente",
                 "Cuando hables con el comprador, registra su perfil en el seguimiento Contactado.",
                 "Ir al perfil", "Registrar seguimiento"):
        assert text in html, text
    assert html.index("Calle Piso Centro 1") < html.index('id="propuesta"')
    assert f'href="/properties/{env.props["ana"].id}"' in html
    # Sin perfil no se puede cambiar de propiedad
    assert "Cambiar propiedad" not in html

    # Modal de seguimiento: Contactado con el perfil (obligatorio) y aviso de etapas bloqueadas
    for text in ('id="followUpProfile"', "Perfil del comprador", 'name="profile_notes"',
                 'id="fuPropertyType" name="property_type" required', "data-places-required",
                 'id="followUpProfileBlocked"', "Primero registra el perfil con Contactado",
                 '"CERRADO", "OFERTA", "VISITA_PROGRAMADA"', "const PROFILE_BLOCKS_STAGES = true",
                 'id="followUpSubmit"', "/static/js/search-profile.js"):
        assert text in html, text
    # Las etapas bloqueadas siguen en el select (no se deshabilitan)
    assert '<option value="VISITA_PROGRAMADA">' in html and '<option value="CERRADO">' in html


def test_propuesta_sin_perfil_estado_vacio(env):
    alert = _property_alert(env, "ana", "ana")
    _add_follow_up(env, env.users["ana"], alert, "SIN_RESPUESTA")
    response, html = _detail(env, env.users["ana"], alert, step="proposal")
    assert response.context["suggestions"] == []
    assert "Aún no hay propuesta" in html and "Perfil pendiente" in html
    assert "Asociar a esta alerta" not in html and "¿No está en la lista?" not in html

    # Por defecto, con gestión y sin perfil: paso Perfil con los mínimos marcados
    response, html = _detail(env, env.users["ana"], alert)
    assert response.context["step"] == "profile"
    assert "Datos mínimos: tipo, precio máximo y ubicación (provincia, población o zona)" in html
    assert "Al guardar se registra el seguimiento «Contactado»" in html
    assert 'id="spPropertyType" name="property_type" required' in html
    assert 'id="spMaxPrice" name="max_price"' in html and 'data-places-error="spPlacesError"' in html


def test_detalle_con_referencia_tras_contactado_con_perfil(env):
    alert = _property_alert(env, "ana", "ana")
    _add_follow_up(env, env.users["ana"], alert, "CONTACTADO", notes="Hablado", form=CONTACT_PROFILE)

    response, html = _detail(env, env.users["ana"], alert)
    ctx = response.context
    assert ctx["step"] == "proposal" and ctx["profile_complete"] is True
    # Chips del perfil con "Editar", sin aviso
    for part in ("Piso", "Centro", "≤ 150.000 €"):
        assert f'text-xs text-gray-700">{part}</span>' in html, part
    assert "Perfil pendiente" not in html and ">Editar</a>" in html
    # "Cambiar propiedad" y sugerencias: la actual marcada, la de Bea para asociar
    assert "Cambiar propiedad" in html
    # De las dos empresas (PLAN_SUGERENCIAS_MULTIEMPRESA.md)
    assert [p.title for p in ctx["suggestions"]] == ["Piso Centro", "Piso MOES", "Piso Bea"]
    assert ctx["current_in_suggestions"] is True
    assert "Asociada ahora" in html and html.count("Asociar a esta alerta") >= 1
    assert "¿No está en la lista?" in html
    # El historial muestra la nota del agente y el resumen en otra línea
    assert "Hablado\nPerfil de búsqueda: Piso · Centro · ≤ 150.000 €." in html
    # Modal: perfil precargado y opcional; las etapas ya no se bloquean
    assert "const PROFILE_BLOCKS_STAGES = false" in html
    assert "Su perfil guardado; cámbialo si te ha contado algo nuevo." in html
    assert 'id="fuPropertyType" name="property_type" required' not in html
    assert 'name="max_price" value="150000"' in html

    # Tras cambiar a la de Bea: tarjeta nueva, sin enlace a la ficha ajena, con su agente
    _link(env, env.users["ana"], alert, "bea")
    _, html = _detail(env, env.users["ana"], alert)
    assert "Calle Piso Bea 1" in html
    assert f'href="/properties/{env.props["bea"].id}"' not in html
    assert "Con referencia · propiedad cambiada el" in html and "agente de la propiedad: Agente Bea" in html


def test_propiedad_actual_fuera_del_perfil_se_ve_asociada(env):
    """Si la propiedad de la alerta no encaja con el perfil, sale aparte como "Asociada ahora"."""
    _complete_profile(env, max_price=100000)
    alert = _property_alert(env, "ana", "ana")
    _add_follow_up(env, env.users["ana"], alert, "SIN_RESPUESTA")
    response, html = _detail(env, env.users["ana"], alert, step="proposal")
    assert response.context["suggestions"] == [] and response.context["current_in_suggestions"] is False
    assert "Asociada ahora" in html and "No hay propiedades que encajen con su perfil" in html


def test_detalle_admin_alerta_con_referencia(env):
    alert = _property_alert(env, "bea", "bea")
    response, html = _detail(env, env.admin, alert)
    assert response.context["show_steps"] is True and "Perfil pendiente" in html
    assert 'id="alertAssignment"' in html

    # Cerrada: sin pasos ni perfil en el modal
    alert.status = AlertStatus.COMPLETED
    env.db.commit()
    response, html = _detail(env, env.admin, alert)
    assert response.context["show_steps"] is False and 'id="followUpProfile"' not in html


# ---------------------------------------------------------------------------
# Listado: chip "Sin perfil" para el admin
# ---------------------------------------------------------------------------

def test_listado_chip_sin_perfil_solo_admin(env):
    open_alert = _property_alert(env, "ana", "ana")
    closed = _search_alert(env, "bea", created_at=T0 + timedelta(hours=1))
    closed.status = AlertStatus.COMPLETED
    env.db.commit()

    from app.web.routes.alerts import alerts_page

    def page(user, status_filter=()):
        request = _request(env, user, "/alerts")
        return asyncio.run(alerts_page(request, q="", status_filter=list(status_filter), agent_id=None,
                                       page=None, per_page=None, b_q="", b_page=None, db=env.db))

    response = page(env.admin, ["PENDING", "IN_PROGRESS", "COMPLETED"])
    assert response.context["profile_missing_ids"] == {open_alert.id}   # la cerrada no cuenta
    assert "Sin perfil" in response.body.decode("utf-8")

    assert "Sin perfil" not in _list_html(env, env.users["ana"])

    _complete_profile(env)
    response = page(env.admin)
    assert response.context["profile_missing_ids"] == set()
    assert "Sin perfil" not in response.body.decode("utf-8")
