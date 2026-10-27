"""
Perfil de búsqueda obligatorio solo en Venta; opcional en Alquiler
(PLAN_PERFIL_SOLO_VENTA.md).

`buyer_matching.profile_required(alert)` es la única fuente de verdad de
"hace falta perfil". En Alquiler el perfil no bloquea etapas, ni la
Propuesta, ni asociar propiedad.

2026-10-26 (alquiler sin perfil de comprador): en Alquiler el perfil ya ni
se muestra ni se guarda (`buyer_matching.profile_applies`): sin bloque de
perfil, sin paso Perfil, sin sugerencias y sin perfil en «Contactado»; la
ficha de un comprador solo de alquiler no tiene las pestañas de perfil ni de
compatibles (`buyer_profile_applies`). Los datos guardados se conservan.

Rutas en proceso contra una SQLite en memoria con los modelos reales; mismo
entorno y helpers que tests/test_alert_search.py y tests/test_profile_required.py.

    cd backend && python -m pytest tests/test_profile_solo_venta.py -q
"""
import asyncio
import json
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.core.constants import AlertStatus, BusinessType
from app.services import buyer_matching
from tests.test_alert_search import (  # noqa: F401  (env es un fixture)
    CONTACT_PROFILE,
    T0,
    _add_follow_up,
    _complete_profile,
    _detail,
    _flash,
    _link,
    _property_alert,
    _reload,
    _request,
    _save_profile,
    _search_alert,
    env,
)
from tests.test_profile_location import _save_buyer_profile
from tests.test_profile_required import _actions, _criteria


def _rent_alert(env, prop_key="ana", agent_key="ana", created_at=T0, buyer=None):
    """Alerta con referencia de Alquiler (misma alerta que _property_alert, otra operación)."""
    alert = _property_alert(env, prop_key, agent_key, created_at=created_at, buyer=buyer)
    alert.business_type = BusinessType.ALQUILER
    env.db.commit()
    return alert


# ---------------------------------------------------------------------------
# Única fuente de verdad
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("buyer_id, business_type, expected", [
    (1, "Venta", True),
    (1, "Alquiler", False),
    (None, "Venta", False),       # sin comprador no hay dónde guardarlo
    (1, None, False),
    (1, "", False),
    (1, "Traspaso", False),       # cualquier otro valor: opcional
])
def test_profile_required(buyer_id, business_type, expected):
    alert = SimpleNamespace(buyer_id=buyer_id, business_type=business_type)
    assert buyer_matching.profile_required(alert) is expected


def test_profile_required_con_la_operacion_pedida():
    """La obligatoriedad va con la operación pedida en la misma petición (cambio desde el perfil)."""
    venta = SimpleNamespace(buyer_id=1, business_type="Venta")
    alquiler = SimpleNamespace(buyer_id=1, business_type="Alquiler")
    assert buyer_matching.profile_required(venta, "Alquiler") is False
    assert buyer_matching.profile_required(alquiler, "Venta") is True
    assert buyer_matching.profile_required(SimpleNamespace(buyer_id=None, business_type="Alquiler"), "Venta") is False


def test_operaciones_con_perfil_obligatorio():
    assert buyer_matching.profile_required_for_business_type("Venta") is True
    assert buyer_matching.profile_required_for_business_type("Alquiler") is False
    assert buyer_matching.profile_required_for_business_type(None) is False
    assert buyer_matching.profile_required_operations() == ["Venta"]


def test_profile_required_con_alertas_reales(env):
    venta = _property_alert(env, "ana", "ana")
    alquiler = _rent_alert(env, "bea", "bea")
    assert buyer_matching.profile_required(venta) is True
    assert buyer_matching.profile_required(alquiler) is False


# ---------------------------------------------------------------------------
# Alquiler sin perfil: nada se bloquea
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("action", ["VISITA_PROGRAMADA", "OFERTA"])
def test_alquiler_etapas_avanzadas_sin_perfil(env, action):
    alert = _rent_alert(env)
    response = _add_follow_up(env, env.users["ana"], alert, action)
    assert _flash(response) == {"category": "success", "message": "Seguimiento agregado correctamente"}
    assert _actions(env, alert) == [action] and _criteria(env) is None


def test_alquiler_cerrado_sin_perfil(env):
    alert = _rent_alert(env)
    response = _add_follow_up(env, env.users["ana"], alert, "CERRADO", notes="Alquilada")
    assert _flash(response) == {"category": "success", "message": "Alerta cerrada con éxito"}
    assert _reload(env, alert).status == AlertStatus.COMPLETED


def test_alquiler_contactado_sin_campos(env):
    alert = _rent_alert(env)
    response = _add_follow_up(env, env.users["ana"], alert, "CONTACTADO", notes="Hablado")
    assert response.headers["location"] == f"/alerts/{alert.id}"
    assert _flash(response) == {"category": "success", "message": "Seguimiento agregado correctamente"}
    [follow_up] = _reload(env, alert).follow_ups
    assert follow_up.action_type == "CONTACTADO" and follow_up.notes == "Hablado"
    assert _criteria(env) is None                                   # no se crea un perfil vacío


def test_alquiler_contactado_con_campos_del_perfil_los_ignora(env):
    """Alquiler sin perfil de comprador (buyer_matching.profile_applies): si llegan
    campos del perfil (parciales o completos) se ignoran; ni se exigen mínimos ni
    se guarda perfil. Antes: parciales → error de mínimos; completos → perfil."""
    alert = _rent_alert(env)
    response = _add_follow_up(env, env.users["ana"], alert, "CONTACTADO",
                              form={"property_type": "Piso", "min_bedrooms": "2"})
    assert _flash(response) == {"category": "success", "message": "Seguimiento agregado correctamente"}
    assert _actions(env, alert) == ["CONTACTADO"] and _criteria(env) is None


def test_alquiler_contactado_con_minimos_no_guarda_perfil(env):
    alert = _rent_alert(env)
    response = _add_follow_up(env, env.users["ana"], alert, "CONTACTADO", notes="Busca piso",
                              form=dict(CONTACT_PROFILE, business_type="Alquiler"))
    assert _flash(response) == {"category": "success", "message": "Seguimiento agregado correctamente"}
    assert _criteria(env) is None
    stored = _reload(env, alert)
    assert [(f.action_type, f.notes) for f in stored.follow_ups] == [("CONTACTADO", "Busca piso")]
    assert stored.business_type == "Alquiler"


def test_alquiler_asociar_propiedad_sin_perfil(env):
    alert = _rent_alert(env)
    response = _link(env, env.users["ana"], alert, "bea")
    assert _flash(response) == {"category": "success",
                                "message": "Propiedad cambiada: Juan Comprador ahora tiene asociada Piso Bea"}
    stored = _reload(env, alert)
    assert stored.property_id == env.props["bea"].id and stored.agent_id == env.agents["ana"].id
    assert _criteria(env) is None


def test_alquiler_buscador_de_la_propuesta_sin_perfil(env):
    from app.web.routes.alerts import search_properties
    alquiler = _rent_alert(env)

    def titles(alert):
        request = _request(env, env.users["ana"], "/alerts/search-properties")
        response = asyncio.run(search_properties(request, q="Piso", alert_id=str(alert.id), db=env.db))
        return sorted(r["title"] for r in json.loads(response.body)["results"])

    # Las dos empresas, sin perfil (PLAN_SUGERENCIAS_MULTIEMPRESA.md)
    assert titles(alquiler) == ["Piso Bea", "Piso Centro", "Piso MOES"]

    # Venta sin perfil: la regla de siempre (solo las suyas)
    alquiler.status = AlertStatus.COMPLETED
    env.db.commit()
    venta = _property_alert(env, "ana", "ana", created_at=T0 + timedelta(hours=1))
    assert titles(venta) == ["Piso Centro"]


@pytest.mark.parametrize("form", [
    {"country": "España", "business_type": "Alquiler"},              # vacío
    {"property_type": "Piso", "max_price": "900"},                   # parcial
    CONTACT_PROFILE,                                                 # completo
])
def test_alquiler_paso_perfil_no_guarda_nada(env, form):
    """Alquiler sin perfil de comprador: el paso Perfil no existe y su POST no
    guarda nada (antes: vacío → aviso, parcial → mínimos, completo → Contactado)."""
    alert = _rent_alert(env)
    response = _save_profile(env, env.users["ana"], alert, form=form)
    assert response.headers["location"] == f"/alerts/{alert.id}?step=proposal#propuesta"
    assert _flash(response) == {"category": "info", "message": "En alquiler no se registra el perfil del comprador"}
    assert _criteria(env) is None and _reload(env, alert).follow_ups == []


# ---------------------------------------------------------------------------
# Cambio de operación desde el perfil: la obligatoriedad cambia en la misma petición
# ---------------------------------------------------------------------------

def test_venta_a_alquiler_en_el_paso_perfil_deja_de_bloquear(env):
    alert = _property_alert(env, "ana", "ana")
    assert _flash(_add_follow_up(env, env.users["ana"], alert, "VISITA_PROGRAMADA"))["category"] == "error"

    # Solo la operación, sin datos del perfil: vale (ya no es obligatorio)
    response = _save_profile(env, env.users["ana"], alert, form={"country": "España", "business_type": "Alquiler"})
    assert response.headers["location"] == f"/alerts/{alert.id}?step=proposal"
    assert _flash(response) == {"category": "success",
                                "message": "La alerta pasa a Alquiler; el perfil de Juan Comprador queda como estaba"}
    stored = _reload(env, alert)
    assert stored.business_type == "Alquiler" and _criteria(env) is None
    [follow_up] = stored.follow_ups
    assert (follow_up.action_type, follow_up.notes) == ("PERFIL_GUARDADO", "Operación: Venta → Alquiler")

    # Ya no bloquea
    assert _flash(_add_follow_up(env, env.users["ana"], alert, "VISITA_PROGRAMADA"))["category"] == "success"


def test_venta_a_alquiler_con_contactado_sin_campos(env):
    alert = _property_alert(env, "ana", "ana")
    response = _add_follow_up(env, env.users["ana"], alert, "CONTACTADO", notes="Prefiere alquilar",
                              form={"country": "España", "business_type": "Alquiler"})
    assert _flash(response) == {"category": "success",
                                "message": "Seguimiento agregado correctamente. La alerta pasa a Alquiler"}
    stored = _reload(env, alert)
    assert stored.business_type == "Alquiler" and _criteria(env) is None
    [follow_up] = stored.follow_ups                                    # un solo seguimiento
    assert follow_up.action_type == "CONTACTADO"
    assert follow_up.notes == "Prefiere alquilar\nOperación: Venta → Alquiler"


def test_cambio_de_operacion_sin_datos_actualiza_el_perfil_existente(env):
    """Un perfil incompleto ya guardado toma la operación nueva (sugerencias y avisos coherentes)."""
    _complete_profile(env, max_price=None)                             # incompleto, de Venta
    alert = _property_alert(env, "ana", "ana")
    _save_profile(env, env.users["ana"], alert, form={"business_type": "Alquiler"})
    criteria = _criteria(env)
    assert criteria.business_type == "Alquiler" and criteria.max_price is None and criteria.zones == ["Centro"]


def test_alquiler_a_venta_ya_no_se_cambia_desde_el_perfil(env):
    """En Alquiler no hay formulario de perfil: ni el paso Perfil ni «Contactado»
    cambian la operación (antes: Alquiler → Venta exigía los mínimos)."""
    alert = _rent_alert(env)
    response = _save_profile(env, env.users["ana"], alert, form=dict(CONTACT_PROFILE, business_type="Venta"))
    assert _flash(response)["category"] == "info"
    response = _add_follow_up(env, env.users["ana"], alert, "CONTACTADO", form={"business_type": "Venta"})
    assert _flash(response) == {"category": "success", "message": "Seguimiento agregado correctamente"}
    stored = _reload(env, alert)
    assert stored.business_type == "Alquiler" and _criteria(env) is None
    assert [(f.action_type, f.notes) for f in stored.follow_ups] == [("CONTACTADO", None)]


# ---------------------------------------------------------------------------
# Render del detalle
# ---------------------------------------------------------------------------

def test_detalle_alquiler_sin_perfil_de_comprador(env):
    """Alquiler: sin bloque de perfil, sin paso Perfil, sin perfil en «Contactado».
    Se mantienen el comprador, la propiedad, los seguimientos y la Propuesta con
    el buscador manual."""
    alert = _rent_alert(env)

    response, html = _detail(env, env.users["ana"], alert)
    ctx = response.context
    assert ctx["step"] == "contact" and ctx["profile_shown"] is False and ctx["can_propose"] is True
    assert ctx["search_steps"] == (("contact", "1. Contactar"), ("proposal", "2. Propuesta"))
    assert ctx["follow_up_profile"] is False
    for text in ("Perfil del comprador", "2. Perfil", "Perfil opcional", "Registrar perfil",
                 "Perfil pendiente", "Siguiente: perfil de búsqueda", 'id="followUpProfile"',
                 'id="fuPropertyType"', "toma su perfil"):
        assert text not in html, text
    for text in ("Información del Interesado", "Juan Comprador", "Historial de Seguimientos",
                 "Piso Centro", "Cambiar propiedad", "1. Contactar", "2. Propuesta",
                 "Siguiente: propuesta", '<option value="CONTACTADO">', "const PROFILE_BLOCKS_STAGES = false"):
        assert text in html, text

    # ?step=profile no existe en Alquiler: abre el paso por defecto
    response, html = _detail(env, env.users["ana"], alert, step="profile")
    assert response.context["step"] == "contact" and 'id="spPropertyType"' not in html

    # Tras una gestión, Propuesta: buscador manual, sin sugerencias
    _add_follow_up(env, env.users["ana"], alert, "SIN_RESPUESTA")
    response, html = _detail(env, env.users["ana"], alert)
    assert response.context["step"] == "proposal" and response.context["suggestions"] == []
    for text in ('id="linkPropertySearch"', "Buscar una propiedad", 'id="linkPropertyForm"', "Asociada ahora"):
        assert text in html, text
    for text in ("Perfil pendiente", "Aún no hay propuesta", ">¿No está en la lista?</h3>", "Perfil opcional",
                 "No hay propiedades que encajen con su perfil"):
        assert text not in html, text


def test_detalle_alquiler_con_perfil_guardado_no_lo_muestra(env):
    """Un perfil ya guardado no se borra, pero en Alquiler no se muestra ni sugiere."""
    _complete_profile(env, business_type="Alquiler", max_price=500000)
    alert = _rent_alert(env)
    _add_follow_up(env, env.users["ana"], alert, "SIN_RESPUESTA")
    response, html = _detail(env, env.users["ana"], alert)
    ctx = response.context
    assert ctx["step"] == "proposal" and ctx["profile_complete"] is True and ctx["criteria_parts"] == []
    assert ctx["suggestions"] == [] and ctx["suggestions_by_company"] == []
    for text in (">Editar</a>", "Perfil del comprador", ">¿No está en la lista?</h3>", "No hay propiedades que encajen"):
        assert text not in html, text
    assert "Buscar una propiedad" in html
    assert _criteria(env) is not None                                    # el dato se conserva


def test_detalle_busqueda_general_alquiler_sin_resumen_del_perfil(env):
    _complete_profile(env, business_type="Alquiler", max_price=500000)
    alert = _search_alert(env, "ana", business_type="Alquiler")
    response, html = _detail(env, env.users["ana"], alert)
    assert "Aún sin propiedad asociada." in html
    assert "≤ 500.000 €" not in html and "Aún sin perfil de búsqueda" not in html


def test_detalle_venta_muestra_el_perfil_del_comprador(env):
    alert = _property_alert(env, "ana", "ana")
    response, html = _detail(env, env.users["ana"], alert)
    assert response.context["profile_shown"] is True
    assert "Perfil del comprador" in html and "2. Perfil" in html and 'id="followUpProfile"' in html


def test_detalle_venta_sin_perfil_como_antes(env):
    alert = _property_alert(env, "ana", "ana")
    response, html = _detail(env, env.users["ana"], alert)
    assert response.context["profile_required"] is True and response.context["can_propose"] is False
    assert "Perfil pendiente" in html and "Perfil opcional" not in html
    assert "Cambiar propiedad" not in html
    assert "const PROFILE_BLOCKS_STAGES = true" in html
    assert 'id="fuPropertyType" name="property_type" required' in html
    assert "Datos mínimos: tipo, precio máximo y ubicación (provincia, población o zona)." in html

    _add_follow_up(env, env.users["ana"], alert, "SIN_RESPUESTA")
    response, html = _detail(env, env.users["ana"], alert)
    assert response.context["step"] == "profile"
    assert 'id="spPropertyType" name="property_type" required' in html
    _, html = _detail(env, env.users["ana"], alert, step="proposal")
    assert "Aún no hay propuesta" in html and 'id="linkPropertySearch"' not in html


# ---------------------------------------------------------------------------
# Listado: chip "Sin perfil" solo en Venta
# ---------------------------------------------------------------------------

def test_chip_sin_perfil_solo_en_venta(env):
    from app.web.routes.alerts import alerts_page
    venta = _property_alert(env, "ana", "ana")
    alquiler = _search_alert(env, "bea", created_at=T0 + timedelta(hours=1), business_type="Alquiler")

    request = _request(env, env.admin, "/alerts")
    response = asyncio.run(alerts_page(request, q="", status_filter=[], agent_id=None,
                                       page=None, per_page=None, b_q="", b_page=None, db=env.db))
    assert response.context["profile_missing_ids"] == {venta.id}
    assert alquiler.id not in response.context["profile_missing_ids"]


def test_listado_sin_resumen_del_perfil_en_busquedas_de_alquiler(env):
    from app.web.routes.alerts import _page_profiles
    _complete_profile(env, max_price=500000)
    venta = _search_alert(env, "ana")
    alquiler = _search_alert(env, "bea", created_at=T0 + timedelta(hours=1), business_type="Alquiler")
    summaries, _ = _page_profiles(env.db, [venta, alquiler])
    assert venta.id in summaries and alquiler.id not in summaries


def test_modal_alta_texto_sin_perfil_en_alquiler(env):
    from app.web.routes.alerts import alerts_page
    request = _request(env, env.admin, "/alerts")
    response = asyncio.run(alerts_page(request, q="", status_filter=[], agent_id=None,
                                       page=None, per_page=None, b_q="", b_page=None, db=env.db))
    html = response.body.decode("utf-8")
    assert response.context["no_profile_operations"] == ["Alquiler"]
    assert 'id="refWithoutRentText"' in html and "Búsqueda general de alquiler" in html


# ---------------------------------------------------------------------------
# Ficha del comprador: mínimos según la operación enviada
# ---------------------------------------------------------------------------

def test_ficha_alquiler_sin_minimos_se_guarda(env):
    response = _save_buyer_profile(env, env.admin, {"business_type": "Alquiler", "property_type": "Piso"})
    assert response.headers["location"] == f"/buyers/{env.buyer.id}?tab=matches"
    assert _flash(response) == {"category": "success", "message": "Perfil de búsqueda guardado"}
    criteria = _criteria(env)
    assert (criteria.business_type, criteria.property_type, criteria.max_price) == ("Alquiler", "Piso", None)


def test_ficha_venta_sin_minimos_rechazada(env):
    response = _save_buyer_profile(env, env.admin, {"business_type": "Venta", "property_type": "Piso"})
    assert response.headers["location"] == f"/buyers/{env.buyer.id}?tab=criteria"
    assert _flash(response) == {"category": "error", "message": "Faltan datos del perfil: precio máximo, ubicación"}
    assert _criteria(env) is None


def _buyer_page(env, user=None, tab="criteria"):
    from app.web.routes.alerts import buyer_detail
    request = _request(env, user or env.admin, f"/buyers/{env.buyer.id}")
    response = asyncio.run(buyer_detail(env.buyer.id, request, tab=tab, db=env.db))
    return response, response.body.decode("utf-8")


def test_ficha_render_minimos_segun_operacion(env):
    # Con una alerta de Venta la ficha muestra el perfil (aunque el guardado sea
    # de Alquiler); sin ella, sería un comprador solo de alquiler (ver abajo)
    _property_alert(env, "ana", "ana")

    def html():
        return _buyer_page(env)[1]

    _complete_profile(env, business_type="Alquiler", max_price=None)
    page = html()
    assert 'data-required-operations="[&#34;Venta&#34;]"' in page and "data-minimums-if-filled" not in page
    assert "Obligatorios en venta; en alquiler, opcionales." in page
    assert 'id="bcPropertyType" name="property_type" required' not in page   # Alquiler al pintar

    criteria = _criteria(env)
    criteria.business_type = "Venta"
    env.db.commit()
    assert 'id="bcPropertyType" name="property_type" required' in html()     # Venta al pintar


# ---------------------------------------------------------------------------
# Ficha del comprador solo de alquiler: sin pestañas de perfil
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("operations, criteria_operation, expected", [
    (["Venta"], None, True),
    (["Alquiler", "Venta"], "Alquiler", True),        # alguna de Venta: como hoy
    (["Alquiler"], None, False),                      # todas de Alquiler
    (["Alquiler", "Alquiler"], "Venta", False),
    ([], "Alquiler", False),                          # sin alertas, perfil en Alquiler
    ([None, "Alquiler"], "Alquiler", False),          # sin alertas de Venta, perfil en Alquiler
    ([None], None, True),
    ([], None, True),                                 # sin alertas ni perfil: como hoy
    ([], "Venta", True),
])
def test_buyer_profile_applies(operations, criteria_operation, expected):
    assert buyer_matching.buyer_profile_applies(operations, criteria_operation) is expected


def test_profile_applies():
    assert buyer_matching.profile_applies("Venta") is True
    assert buyer_matching.profile_applies(None) is True
    assert buyer_matching.profile_applies("Alquiler") is False
    assert buyer_matching.no_profile_operations() == ["Alquiler"]


def test_ficha_comprador_solo_alquiler_sin_pestana_de_criterios(env):
    _complete_profile(env, business_type="Alquiler", max_price=500000)
    _rent_alert(env)
    for tab in ("criteria", "matches", "alerts"):
        response, page = _buyer_page(env, tab=tab)
        ctx = response.context
        assert ctx["profile_shown"] is False and ctx["tab"] == "alerts", tab
        assert ctx["matching_properties"] == []
        for text in ('id="tab-criteria"', 'id="panel-criteria"', 'id="tab-matches"', 'id="panel-matches"',
                     "Perfil de búsqueda", "Propiedades compatibles", 'action="/buyers/%d/search-criteria"' % env.buyer.id):
            assert text not in page, (tab, text)
        assert 'id="tab-alerts"' in page and 'id="panel-alerts" class=""' in page
    assert _criteria(env) is not None                                    # el perfil se conserva

    # El agente también
    _, page = _buyer_page(env, user=env.users["ana"])
    assert 'id="tab-criteria"' not in page


def test_ficha_comprador_con_alguna_alerta_de_venta_como_hoy(env):
    _rent_alert(env)
    _property_alert(env, "bea", "bea", created_at=T0 + timedelta(hours=1))
    response, page = _buyer_page(env)
    assert response.context["profile_shown"] is True and response.context["tab"] == "criteria"
    assert 'id="tab-criteria"' in page and 'id="tab-matches"' in page and "Perfil de búsqueda" in page
