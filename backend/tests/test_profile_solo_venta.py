"""
Perfil de búsqueda obligatorio solo en Venta; opcional en Alquiler
(PLAN_PERFIL_SOLO_VENTA.md).

`buyer_matching.profile_required(alert)` es la única fuente de verdad de
"hace falta perfil". En Alquiler el perfil se puede registrar (y sugiere
propiedades), pero no bloquea etapas, ni la Propuesta, ni asociar propiedad.

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
from tests.test_profile_required import PROFILE_STEP, _actions, _criteria


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


def test_alquiler_contactado_con_campos_parciales_exige_minimos(env):
    alert = _rent_alert(env)
    response = _add_follow_up(env, env.users["ana"], alert, "CONTACTADO",
                              form={"property_type": "Piso", "min_bedrooms": "2"})
    assert response.headers["location"] == f"/alerts/{alert.id}{PROFILE_STEP}"
    assert _flash(response) == {
        "category": "error",
        "message": "Para registrar «Contactado» completa el perfil del comprador. Falta: precio máximo, ubicación",
    }
    assert _reload(env, alert).follow_ups == [] and _criteria(env) is None


def test_alquiler_contactado_con_minimos_un_solo_contactado(env):
    alert = _rent_alert(env)
    response = _add_follow_up(env, env.users["ana"], alert, "CONTACTADO", notes="Busca piso",
                              form=dict(CONTACT_PROFILE, business_type="Alquiler"))
    assert _flash(response) == {"category": "success",
                                "message": "«Contactado» registrado con el perfil de Juan Comprador"}
    criteria = _criteria(env)
    assert buyer_matching.profile_is_complete(criteria) and criteria.business_type == "Alquiler"
    stored = _reload(env, alert)
    assert [f.action_type for f in stored.follow_ups] == ["CONTACTADO"]
    assert stored.follow_ups[0].notes == "Busca piso\nPerfil de búsqueda: Piso · Centro · ≤ 150.000 €."
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


def test_alquiler_paso_perfil_vacio_no_guarda_nada(env):
    alert = _rent_alert(env)
    response = _save_profile(env, env.users["ana"], alert, form={"country": "España", "business_type": "Alquiler"})
    assert response.headers["location"] == f"/alerts/{alert.id}?step=proposal#propuesta"
    assert _flash(response) == {
        "category": "info",
        "message": "No se ha guardado nada: el perfil de Juan Comprador está vacío y es opcional en alquiler",
    }
    assert _criteria(env) is None and _reload(env, alert).follow_ups == []


def test_alquiler_paso_perfil_parcial_exige_minimos(env):
    alert = _rent_alert(env)
    response = _save_profile(env, env.users["ana"], alert, form={"property_type": "Piso", "max_price": "900"})
    assert response.headers["location"] == f"/alerts/{alert.id}{PROFILE_STEP}"
    assert _flash(response) == {"category": "error", "message": "Faltan datos del perfil: ubicación"}
    assert _criteria(env) is None


def test_alquiler_paso_perfil_completo_registra_contactado(env):
    alert = _rent_alert(env)
    response = _save_profile(env, env.users["ana"], alert, form=CONTACT_PROFILE)
    assert response.headers["location"] == f"/alerts/{alert.id}?step=proposal"
    assert "registrado como «Contactado»" in _flash(response)["message"]
    assert _actions(env, alert) == ["CONTACTADO"]
    assert _criteria(env).business_type == "Alquiler"


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


def test_alquiler_a_venta_con_perfil_incompleto_rechazado(env):
    alert = _rent_alert(env)
    response = _save_profile(env, env.users["ana"], alert, form={"business_type": "Venta", "property_type": "Piso"})
    assert response.headers["location"] == f"/alerts/{alert.id}{PROFILE_STEP}"
    assert _flash(response) == {"category": "error", "message": "Faltan datos del perfil: precio máximo, ubicación"}
    stored = _reload(env, alert)
    assert stored.business_type == "Alquiler" and stored.follow_ups == [] and _criteria(env) is None

    # Sin ningún dato: también, con todos los mínimos
    response = _save_profile(env, env.users["ana"], alert, form={"business_type": "Venta"})
    assert _flash(response)["message"] == "Faltan datos del perfil: tipo de inmueble, precio máximo, ubicación"

    # Y con «Contactado» igual
    response = _add_follow_up(env, env.users["ana"], alert, "CONTACTADO", form={"business_type": "Venta"})
    assert _flash(response)["message"].endswith("Falta: tipo de inmueble, precio máximo, ubicación")
    assert _reload(env, alert).business_type == "Alquiler"


def test_alquiler_a_venta_con_minimos(env):
    alert = _rent_alert(env)
    response = _save_profile(env, env.users["ana"], alert, form=dict(CONTACT_PROFILE, business_type="Venta"))
    assert _flash(response)["message"].endswith(". La alerta pasa a Venta")
    stored = _reload(env, alert)
    assert stored.business_type == "Venta" and _actions(env, alert) == ["CONTACTADO"]
    assert buyer_matching.profile_is_complete(_criteria(env))


# ---------------------------------------------------------------------------
# Render del detalle
# ---------------------------------------------------------------------------

def test_detalle_alquiler_sin_perfil(env):
    alert = _rent_alert(env)

    # Contactar: línea discreta en lugar del banner; "Cambiar propiedad" disponible
    response, html = _detail(env, env.users["ana"], alert)
    ctx = response.context
    assert ctx["step"] == "contact" and ctx["profile_required"] is False and ctx["can_propose"] is True
    assert "Perfil opcional en alquiler: si lo registras verás propiedades sugeridas." in html
    assert "Registrar perfil" in html
    assert "Perfil pendiente" not in html and "Cuando hables con el comprador" not in html
    assert "Cambiar propiedad" in html

    # Modal: perfil opcional (sin `required` al pintar) que sigue a la operación;
    # Visita programada no se bloquea
    assert "const PROFILE_BLOCKS_STAGES = false" in html
    assert 'id="fuPropertyType" name="property_type" required' not in html
    assert 'id="fuMaxPrice" name="max_price" value="" placeholder="–" required' not in html
    assert "Opcional en alquiler: si lo rellenas, incluye tipo, precio máximo y ubicación" in html
    assert 'data-required-operations="[&#34;Venta&#34;]"' in html and "data-minimums-if-filled" in html
    assert '<option value="VISITA_PROGRAMADA">' in html

    # Tras una gestión, por defecto la Propuesta (no el Perfil)
    _add_follow_up(env, env.users["ana"], alert, "SIN_RESPUESTA")
    response, html = _detail(env, env.users["ana"], alert)
    assert response.context["step"] == "proposal"
    assert response.context["suggestions"] == []                      # sin perfil no hay sugerencias
    for text in ('id="linkPropertySearch"', "Buscar una propiedad", 'id="linkPropertyForm"',
                 "Perfil opcional en alquiler", "Asociada ahora"):
        assert text in html, text
    for text in ("Perfil pendiente", "Aún no hay propuesta", ">¿No está en la lista?</h3>",
                 "No hay propiedades que encajen con su perfil"):
        assert text not in html, text


def test_detalle_alquiler_paso_perfil_opcional(env):
    alert = _rent_alert(env)
    response, html = _detail(env, env.users["ana"], alert, step="profile")
    assert "Opcional en alquiler: si lo registras verás propiedades sugeridas" in html
    assert "Si lo rellenas, incluye tipo, precio máximo y ubicación" in html
    assert "Datos mínimos: tipo, precio máximo y ubicación (provincia, población o zona)" not in html
    assert 'id="spPropertyType" name="property_type" required' not in html
    assert 'data-places-error="spPlacesError"' in html                # el JS lo exige si rellena algo


def test_detalle_alquiler_con_perfil_sugiere(env):
    _complete_profile(env, business_type="Alquiler", max_price=500000)
    alert = _rent_alert(env)
    _add_follow_up(env, env.users["ana"], alert, "SIN_RESPUESTA")
    response, html = _detail(env, env.users["ana"], alert)
    ctx = response.context
    assert ctx["step"] == "proposal" and ctx["profile_complete"] is True
    # Las propiedades de prueba son de Venta: ninguna encaja, pero salen el estado y el buscador de siempre
    assert ctx["suggestions"] == []
    assert "No hay propiedades que encajen con su perfil" in html and "¿No está en la lista?" in html
    assert ">Editar</a>" in html and "Perfil opcional" not in html


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


def test_ficha_render_minimos_segun_operacion(env):
    from app.web.routes.alerts import buyer_detail

    def html():
        request = _request(env, env.admin, f"/buyers/{env.buyer.id}")
        return asyncio.run(buyer_detail(env.buyer.id, request, tab="criteria", db=env.db)).body.decode("utf-8")

    _complete_profile(env, business_type="Alquiler", max_price=None)
    page = html()
    assert 'data-required-operations="[&#34;Venta&#34;]"' in page and "data-minimums-if-filled" not in page
    assert "Obligatorios en venta; en alquiler, opcionales." in page
    assert 'id="bcPropertyType" name="property_type" required' not in page   # Alquiler al pintar

    criteria = _criteria(env)
    criteria.business_type = "Venta"
    env.db.commit()
    assert 'id="bcPropertyType" name="property_type" required' in html()     # Venta al pintar
