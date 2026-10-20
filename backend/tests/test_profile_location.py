"""
Ubicación del perfil en cascada País → Provincia → Población → Zona, provincia
deducida del código postal, operación editable desde el perfil de la alerta y
mínimos del perfil también en la ficha del comprador (PLAN_PERFIL_UBICACION.md).

Rutas y servicios en proceso contra una SQLite en memoria con los modelos
reales; mismo entorno y helpers que tests/test_alert_search.py. Además de las
propiedades del entorno (Jaen / Centro, sin CP ni país), cada test que lo
necesita añade propiedades de Jaén (CP 23…), Madrid (28…) y Portugal.

    cd backend && python -m pytest tests/test_profile_location.py -q
"""
import asyncio
import json
import re
import subprocess
import sys

import pytest

from app.core import geo
from app.core.constants import AlertStatus, FollowUpActionType
from app.services import buyer_matching
from tests.test_alert_search import (  # noqa: F401  (env es un fixture)
    BACKEND,
    CONTACT_PROFILE,
    _add_follow_up,
    _complete_profile,
    _detail,
    _flash,
    _property_alert,
    _reload,
    _request,
    _save_profile,
    env,
)


PROFILE_STEP = "?step=profile#propuesta"


def _prop(env, title, city, zona, cp=None, pais=None, price=100000, company=None, status="Activa",
          agent="ana", business_type="Venta"):
    from app.models.property import Property
    prop = Property(title=title, address=f"Calle {title}", city=city, zona=zona, cod_postal=cp, pais=pais,
                    property_type="Piso", business_type=business_type, price=price, status=status,
                    company_id=(company or env.moyza).id, agent_id=env.agents[agent].id)
    env.db.add(prop)
    env.db.commit()
    return prop


def _jaen_and_more(env):
    """Jaén (dos zonas en la capital, Martos con Centro y Norte, Úbeda), Madrid y Portugal."""
    return {
        "jaen_centro": _prop(env, "Jaén Centro", "Jaén", "Centro", "23004"),
        "jaen_bulevar": _prop(env, "Jaén Bulevar", "Jaén", "Bulevar", "23009", pais="España"),
        "martos_centro": _prop(env, "Martos Centro", "Martos", "Centro", "23600"),
        "martos_norte": _prop(env, "Martos Norte", "Martos", "Norte", "23600"),
        "ubeda": _prop(env, "Úbeda Casco", "Úbeda", "Casco", "23400"),
        "madrid": _prop(env, "Madrid Sol", "Madrid", "Sol", "28001", pais="spain"),
        "lisboa": _prop(env, "Lisboa Baixa", "Lisboa", "Baixa", "11000", pais="Portugal"),
    }


def _criteria(env):
    from app.models.buyer_search_criteria import BuyerSearchCriteria
    env.db.expire_all()
    return env.db.query(BuyerSearchCriteria).filter_by(buyer_id=env.buyer.id).one_or_none()


def _titles(env, **fields):
    from app.models.buyer_search_criteria import BuyerSearchCriteria
    data = dict(property_type="Piso", max_price=1000000)
    data.update(fields)
    return sorted(p.title for p in buyer_matching.matching_properties(env.db, BuyerSearchCriteria(**data), env.moyza.id))


# ---------------------------------------------------------------------------
# app/core/geo.py y Property.provincia
# ---------------------------------------------------------------------------

def test_tabla_de_provincias_completa():
    assert len(geo.PROVINCIAS_POR_CP) == 52
    assert sorted(geo.PROVINCIAS_POR_CP) == [f"{n:02d}" for n in range(1, 53)]
    assert len(set(geo.PROVINCIAS_POR_CP.values())) == 52          # sin nombres repetidos
    assert geo.PROVINCIAS_POR_CP["01"] == "Álava" and geo.PROVINCIAS_POR_CP["52"] == "Melilla"
    for prefix, name in geo.PROVINCIAS_POR_CP.items():
        assert geo.cp_prefix_for_provincia(name) == prefix


@pytest.mark.parametrize("cp, provincia", [
    ("23004", "Jaén"), ("28001", "Madrid"), (" 08001 ", "Barcelona"), ("52001", "Melilla"),
    ("", None), (None, None), ("ABCDE", None), ("99999", None), ("00123", None), ("2300", None), ("230045", None),
])
def test_provincia_desde_el_cp(cp, provincia):
    assert geo.provincia_from_cp(cp) == provincia


def test_prefijo_de_provincia():
    assert geo.cp_prefix_for_provincia("Jaén") == "23"
    assert geo.cp_prefix_for_provincia(" Madrid ") == "28"
    assert geo.cp_prefix_for_provincia("Sin provincia") is None
    assert geo.cp_prefix_for_provincia("") is None and geo.cp_prefix_for_provincia(None) is None


def test_pais_vacio_o_variantes_son_espana():
    for value in (None, "", "  ", "España", "españa", "ESPAÑA", "Espana", "Spain", "ES"):
        assert geo.is_spain(value) and geo.normalize_country(value) == "España", value
    assert not geo.is_spain("Portugal") and geo.normalize_country(" Portugal ") == "Portugal"


def test_property_provincia_es_de_solo_lectura_y_depende_del_pais():
    from app.models.property import Property
    assert Property(cod_postal="23004").provincia == "Jaén"
    assert Property(cod_postal="23004", pais="España").provincia == "Jaén"
    assert Property(cod_postal="23004", pais="Portugal").provincia is None
    assert Property(cod_postal=None).provincia is None
    assert "provincia" not in Property.__table__.columns            # sin columna nueva en properties
    with pytest.raises(AttributeError):
        Property().provincia = "Jaén"


# ---------------------------------------------------------------------------
# Cascada: geo_options y geo_choices
# ---------------------------------------------------------------------------

def test_geo_options_agrupa_por_pais_provincia_poblacion_y_zona(env):
    _jaen_and_more(env)
    _prop(env, "Archivada", "Jaén", "Archivo", "23001", status="Archivada")
    _prop(env, "Otra empresa", "Jaén", "MOES", "23001", company=env.moes)
    _prop(env, "Sin población", "", "Huérfana", "23001")
    _prop(env, "Reservada", "Andújar", "Centro", "23740", status="Reservada")   # no archivada: entra

    tree = buyer_matching.geo_options(env.db, env.moyza.id)

    assert list(tree) == ["España", "Portugal"]                           # España primero
    assert list(tree["España"]) == ["Jaén", "Madrid", "Sin provincia"]   # Sin provincia la última
    assert tree["España"]["Jaén"] == {
        "Andújar": ["Centro"], "Jaén": ["Bulevar", "Centro"], "Martos": ["Centro", "Norte"], "Úbeda": ["Casco"],
    }
    assert list(tree["España"]["Jaén"]) == ["Andújar", "Jaén", "Martos", "Úbeda"]   # orden sin acentos
    assert tree["España"]["Madrid"] == {"Madrid": ["Sol"]}               # "spain" cuenta como España
    # Las propiedades del entorno (sin CP ni país) van a España / Sin provincia
    assert tree["España"]["Sin provincia"] == {"Jaen": ["Centro"]}
    assert tree["Portugal"] == {"Sin provincia": {"Lisboa": ["Baixa"]}}  # fuera de España no hay provincia
    flat = json.dumps(tree, ensure_ascii=False)
    for absent in ("Archivo", "MOES", "Huérfana"):
        assert absent not in flat


def test_geo_options_una_sola_consulta(env):
    from sqlalchemy import event
    _jaen_and_more(env)
    company_id = env.moyza.id          # cargado antes de escuchar (tras el commit está expirado)
    statements = []
    engine = env.db.get_bind()
    listener = lambda *args: statements.append(args[2])  # noqa: E731
    event.listen(engine, "before_cursor_execute", listener)
    try:
        buyer_matching.geo_options(env.db, company_id)
    finally:
        event.remove(engine, "before_cursor_execute", listener)
    assert len(statements) == 1 and "DISTINCT" in statements[0].upper()


def test_geo_choices_estado_inicial(env):
    from app.models.buyer_search_criteria import BuyerSearchCriteria
    _jaen_and_more(env)
    tree = buyer_matching.geo_options(env.db, env.moyza.id)

    # Sin perfil: España preseleccionada, todas las provincias, Todas las poblaciones y zonas
    empty = buyer_matching.geo_choices(tree, None)
    assert empty["country"] == "España" and empty["province"] == ""
    assert empty["provinces"] == ["Jaén", "Madrid"]
    assert empty["cities_all"] and empty["zones_all"]
    assert empty["cities"] == ["Jaen", "Jaén", "Madrid", "Martos", "Úbeda"]

    # Provincia y dos poblaciones: las zonas son solo las de esas dos
    criteria = BuyerSearchCriteria(country="España", province="Jaén", cities=["Jaén", "Martos"], zones=["Centro"])
    choices = buyer_matching.geo_choices(tree, criteria)
    assert choices["cities"] == ["Jaén", "Martos", "Úbeda"]
    assert choices["selected_cities"] == ["Jaén", "Martos"] and not choices["cities_all"]
    assert choices["zones"] == ["Bulevar", "Centro", "Norte"] and choices["selected_zones"] == ["Centro"]

    # Un perfil antiguo (sin país ni provincia) conserva lo que tenía, aunque ya no exista
    old = BuyerSearchCriteria(cities=["Jaen", "Baeza"], zones=["Ronda"])
    choices = buyer_matching.geo_choices(tree, old)
    assert choices["country"] == "España" and choices["province"] == ""
    assert choices["cities"][-1] == "Baeza" and "Ronda" in choices["zones"]


# ---------------------------------------------------------------------------
# Matching por país / provincia / poblaciones / zonas
# ---------------------------------------------------------------------------

def test_matching_por_provincia_poblaciones_y_zonas(env):
    _jaen_and_more(env)
    jaen = ["Jaén Bulevar", "Jaén Centro", "Martos Centro", "Martos Norte", "Úbeda Casco"]

    # Provincia (prefijo del CP) con Todas las poblaciones: no entran las de Jaen sin CP
    assert _titles(env, country="España", province="Jaén") == jaen
    assert _titles(env, country="España", province="Jaén", cities=[]) == jaen
    # Zonas de varias poblaciones
    assert _titles(env, province="Jaén", cities=["Jaén", "Martos"], zones=["Centro"]) == ["Jaén Centro", "Martos Centro"]
    assert _titles(env, province="Jaén", zones=["Centro", "Norte"]) == ["Jaén Centro", "Martos Centro", "Martos Norte"]
    # País: España incluye las de país vacío; otro país excluye
    spain = _titles(env, country="España")
    assert "Lisboa Baixa" not in spain and "Piso Centro" in spain and "Madrid Sol" in spain
    assert _titles(env, country="Portugal") == ["Lisboa Baixa"]
    assert _titles(env, country="Portugal", cities=["Jaén"]) == []
    # La provincia implica España aunque otro país tenga el mismo prefijo de CP
    assert "Lisboa Baixa" not in _titles(env, province="Cádiz")
    # Sin país ni provincia: como antes (solo poblaciones/zonas)
    assert _titles(env, cities=["Jaen"]) == ["Casa Cara", "Piso Bea", "Piso Centro"]


# ---------------------------------------------------------------------------
# Mínimos del perfil (decisión 4) y guardado
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("location, complete", [
    ({}, False),
    ({"country": "España"}, False),                       # el país solo no basta
    ({"country": "España", "province": "Jaén"}, True),    # provincia con Todas las poblaciones
    ({"province": "Jaén"}, True),
    ({"cities": ["Martos"]}, True),
    ({"zones": ["Centro"]}, True),
    ({"cities": [], "zones": []}, False),
])
def test_minimo_de_ubicacion(location, complete):
    from app.models.buyer_search_criteria import BuyerSearchCriteria
    criteria = BuyerSearchCriteria(property_type="Piso", max_price=150000, **location)
    assert buyer_matching.profile_is_complete(criteria) is complete
    assert buyer_matching.missing_profile_fields(criteria) == ([] if complete else ["ubicación"])


def test_apply_profile_pais_y_provincia():
    from app.models.buyer_search_criteria import BuyerSearchCriteria
    c = buyer_matching.apply_profile(BuyerSearchCriteria(), country="españa", province="Jaén", cities=["Jaén", ""])
    assert (c.country, c.province, c.cities, c.zones) == ("España", "Jaén", ["Jaén"], None)
    # Provincia sin país: España
    c = buyer_matching.apply_profile(BuyerSearchCriteria(), province="Jaén")
    assert (c.country, c.province) == ("España", "Jaén")
    # Provincia desconocida o de otro país: no se guarda
    c = buyer_matching.apply_profile(BuyerSearchCriteria(), country="España", province="Sin provincia")
    assert (c.country, c.province) == ("España", None)
    c = buyer_matching.apply_profile(BuyerSearchCriteria(), country="Portugal", province="Jaén")
    assert (c.country, c.province) == ("Portugal", None)


def test_resumen_con_provincia():
    from app.models.buyer_search_criteria import BuyerSearchCriteria
    c = BuyerSearchCriteria(property_type="Piso", country="España", province="Jaén", max_price=150000)
    assert buyer_matching.criteria_summary(c) == "Piso · Jaén · Todas las poblaciones · ≤ 150.000 €"
    c.cities, c.zones = ["Jaén", "Martos"], ["Centro"]
    assert buyer_matching.criteria_summary(c) == "Piso · Jaén · Jaén, Martos · Zona Centro · ≤ 150.000 €"
    c.cities = ["Jaén", "Martos", "Úbeda"]
    assert "Jaén, Martos +1" in buyer_matching.criteria_summary(c)
    # Otro país se nombra; España no
    c = BuyerSearchCriteria(country="Portugal", cities=["Lisboa"])
    assert buyer_matching.criteria_summary(c) == "Portugal · Lisboa"


def test_paso_perfil_con_provincia_y_todas_las_poblaciones(env):
    _jaen_and_more(env)
    alert = _property_alert(env, "ana", "ana")
    form = {"country": "España", "province": "Jaén", "property_type": "Piso", "max_price": "200000"}
    response = _save_profile(env, env.users["ana"], alert, form=form)
    assert response.headers["location"] == f"/alerts/{alert.id}?step=proposal"
    criteria = _criteria(env)
    assert (criteria.country, criteria.province, criteria.cities, criteria.zones) == ("España", "Jaén", None, None)
    assert buyer_matching.profile_is_complete(criteria)
    [follow_up] = _reload(env, alert).follow_ups
    assert follow_up.action_type == "CONTACTADO"
    assert follow_up.notes == "Perfil de búsqueda: Piso · Jaén · Todas las poblaciones · ≤ 200.000 €."
    assert "5 propiedades sugeridas" in _flash(response)["message"]


def test_paso_perfil_solo_pais_falta_ubicacion(env):
    alert = _property_alert(env, "ana", "ana")
    response = _save_profile(env, env.users["ana"], alert,
                             form={"country": "España", "property_type": "Piso", "max_price": "200000"})
    assert response.headers["location"] == f"/alerts/{alert.id}{PROFILE_STEP}"
    assert _flash(response) == {"category": "error", "message": "Faltan datos del perfil: ubicación"}
    assert _criteria(env) is None and _reload(env, alert).follow_ups == []


def test_contactado_con_provincia(env):
    _jaen_and_more(env)
    alert = _property_alert(env, "ana", "ana")
    form = {"country": "España", "province": "Jaén", "cities": ["Martos"], "property_type": "Piso",
            "max_price": "200000", "business_type": "Venta"}
    response = _add_follow_up(env, env.users["ana"], alert, "CONTACTADO", notes="Hablado", form=form)
    assert _flash(response)["category"] == "success"
    criteria = _criteria(env)
    assert (criteria.province, criteria.cities) == ("Jaén", ["Martos"])
    [follow_up] = _reload(env, alert).follow_ups
    # Misma operación: sin línea de operación
    assert follow_up.notes == "Hablado\nPerfil de búsqueda: Piso · Jaén · Martos · ≤ 200.000 €."


# ---------------------------------------------------------------------------
# Operación editable desde el perfil de la alerta (decisión 2)
# ---------------------------------------------------------------------------

def test_cambiar_operacion_en_el_paso_perfil(env):
    alert = _property_alert(env, "ana", "ana")
    form = dict(CONTACT_PROFILE, business_type="Alquiler")
    response = _save_profile(env, env.users["ana"], alert, form=form)
    assert response.headers["location"] == f"/alerts/{alert.id}?step=proposal"
    assert _flash(response)["message"].endswith(". La alerta pasa a Alquiler")

    stored = _reload(env, alert)
    assert stored.business_type == "Alquiler"
    assert _criteria(env).business_type == "Alquiler"                  # las sugerencias se recalculan con ella
    [follow_up] = stored.follow_ups                                     # un solo seguimiento
    assert follow_up.action_type == "CONTACTADO"
    assert follow_up.notes == "Operación: Venta → Alquiler\nPerfil de búsqueda: Piso · Centro · ≤ 150.000 €."
    assert stored.property_id == env.props["ana"].id                    # la propiedad se mantiene


def test_cambiar_operacion_con_contactado_un_solo_seguimiento(env):
    alert = _property_alert(env, "ana", "ana")
    form = dict(CONTACT_PROFILE, business_type="Alquiler")
    response = _add_follow_up(env, env.users["ana"], alert, "CONTACTADO", notes="Prefiere alquilar", form=form)
    assert _flash(response)["category"] == "success"
    stored = _reload(env, alert)
    assert stored.business_type == "Alquiler"
    assert [f.action_type for f in stored.follow_ups] == ["CONTACTADO"]
    assert stored.follow_ups[0].notes == ("Prefiere alquilar\nOperación: Venta → Alquiler\n"
                                          "Perfil de búsqueda: Piso · Centro · ≤ 150.000 €.")


def test_misma_operacion_no_cambia_nada(env):
    alert = _property_alert(env, "ana", "ana")
    _save_profile(env, env.users["ana"], alert, form=dict(CONTACT_PROFILE, business_type="Venta"))
    [follow_up] = _reload(env, alert).follow_ups
    assert "Operación" not in follow_up.notes and _reload(env, alert).business_type == "Venta"


def test_operacion_invalida_rechazada(env):
    alert = _property_alert(env, "ana", "ana")
    response = _save_profile(env, env.users["ana"], alert, form=dict(CONTACT_PROFILE, business_type="Traspaso"))
    assert response.headers["location"] == f"/alerts/{alert.id}{PROFILE_STEP}"
    assert _flash(response) == {"category": "error", "message": "Selecciona la operación del comprador: Venta o Alquiler"}
    assert _reload(env, alert).business_type == "Venta" and _criteria(env) is None


def test_alerta_cerrada_no_cambia_la_operacion(env):
    alert = _property_alert(env, "ana", "ana")
    alert.status = AlertStatus.COMPLETED
    env.db.commit()

    # Paso Perfil: alerta cerrada
    response = _save_profile(env, env.users["ana"], alert, form=dict(CONTACT_PROFILE, business_type="Alquiler"))
    assert _flash(response) == {"category": "error", "message": "La alerta está cerrada"}
    # Contactado en una alerta cerrada: tampoco
    response = _add_follow_up(env, env.users["ana"], alert, "CONTACTADO",
                              form=dict(CONTACT_PROFILE, business_type="Alquiler"))
    assert _flash(response) == {"category": "error",
                                "message": "La alerta está cerrada: no se puede cambiar la operación"}
    stored = _reload(env, alert)
    assert stored.business_type == "Venta" and stored.follow_ups == [] and _criteria(env) is None


def test_propuesta_avisa_si_la_propiedad_es_de_otra_operacion(env):
    alert = _property_alert(env, "ana", "ana")
    _save_profile(env, env.users["ana"], alert, form=dict(CONTACT_PROFILE, business_type="Alquiler"))

    response, html = _detail(env, env.users["ana"], alert, step="proposal")
    assert response.context["operation_mismatch"] == {"property": "Venta", "wanted": "Alquiler"}
    assert "La propiedad asociada es de Venta y el comprador busca Alquiler" in html
    assert "Asociada ahora" in html                                    # la propiedad se mantiene

    # Al volver a Venta el aviso desaparece
    _save_profile(env, env.users["ana"], alert, form=dict(CONTACT_PROFILE, business_type="Venta"))
    response, html = _detail(env, env.users["ana"], alert, step="proposal")
    assert response.context["operation_mismatch"] is None
    assert "La propiedad asociada es de" not in html


# ---------------------------------------------------------------------------
# Ficha del comprador: mismos mínimos, sin seguimientos
# ---------------------------------------------------------------------------

def _save_buyer_profile(env, user, form):
    from app.web.routes.alerts import save_search_criteria
    fields = {k: form.get(k) for k in ("agent_id", "property_type", "business_type", "min_price", "max_price",
                                       "min_bedrooms", "max_bedrooms", "min_bathrooms", "notes")}
    request = _request(env, user, f"/buyers/{env.buyer.id}/search-criteria", "POST", form=form)
    return asyncio.run(save_search_criteria(env.buyer.id, request, db=env.db, **fields))


def test_ficha_del_comprador_sin_minimos_no_guarda(env):
    response = _save_buyer_profile(env, env.admin, {"business_type": "Venta", "country": "España"})
    assert response.headers["location"] == f"/buyers/{env.buyer.id}?tab=criteria"
    assert _flash(response) == {"category": "error",
                                "message": "Faltan datos del perfil: tipo de inmueble, precio máximo, ubicación"}
    assert _criteria(env) is None

    # La operación se sigue validando antes que nada
    response = _save_buyer_profile(env, env.admin, {"business_type": "", "property_type": "Piso"})
    assert "Venta o Alquiler" in _flash(response)["message"]


def test_ficha_del_comprador_con_minimos_sin_seguimientos(env):
    _jaen_and_more(env)
    alert = _property_alert(env, "ana", "ana")
    form = {"business_type": "Alquiler", "country": "España", "province": "Jaén", "cities": ["Jaén", "Martos"],
            "property_type": "Piso", "max_price": "180000"}
    response = _save_buyer_profile(env, env.users["ana"], form)
    assert response.headers["location"] == f"/buyers/{env.buyer.id}?tab=matches"
    assert _flash(response) == {"category": "success", "message": "Perfil de búsqueda guardado"}
    criteria = _criteria(env)
    assert (criteria.country, criteria.province, criteria.cities) == ("España", "Jaén", ["Jaén", "Martos"])
    assert criteria.business_type == "Alquiler" and criteria.agent_id == env.agents["ana"].id
    # Sin alerta de por medio: ningún seguimiento y la operación de la alerta no cambia
    stored = _reload(env, alert)
    assert stored.follow_ups == [] and stored.business_type == "Venta"


def test_ficha_del_comprador_render_con_minimos(env):
    from app.web.routes.alerts import buyer_detail
    _jaen_and_more(env)
    _complete_profile(env, country="España", province="Jaén", zones=None, cities=["Martos"])
    request = _request(env, env.admin, f"/buyers/{env.buyer.id}")
    response = asyncio.run(buyer_detail(env.buyer.id, request, tab="criteria", db=env.db))
    html = response.body.decode("utf-8")
    assert response.status_code == 200
    for text in ("Datos mínimos: tipo, precio máximo y ubicación (provincia, población o zona)",
                 'id="geoData-bc"', 'id="bcCountry"', 'id="bcProvince"', "data-places-required",
                 'id="bcPropertyType" name="property_type" required', "/static/js/search-profile.js",
                 '<option value="Jaén" selected>Jaén</option>', "Provincia: Jaén"):
        assert text in html, text
    assert "Si la cambias, cambia la operación de la alerta" not in html   # aquí no hay alerta


# ---------------------------------------------------------------------------
# Render del partial (paso Perfil y modal de seguimiento)
# ---------------------------------------------------------------------------

def _checkbox(html, name, value):
    match = re.search(r'<input type="checkbox" name="%s" value="%s"([^>]*)>' % (name, re.escape(value)), html)
    assert match, (name, value)
    attrs = match.group(1)
    return "checked" in attrs, "disabled" in attrs


def test_partial_precargado_con_provincia_y_dos_poblaciones(env):
    _jaen_and_more(env)
    _complete_profile(env, country="España", province="Jaén", cities=["Jaén", "Martos"], zones=None)
    alert = _property_alert(env, "ana", "ana")
    _add_follow_up(env, env.users["ana"], alert, "SIN_RESPUESTA")

    response, html = _detail(env, env.users["ana"], alert, step="profile")
    assert response.status_code == 200

    # Dos selects: País (España y Portugal, España elegida) y Provincia con Jaén elegida
    assert '<select id="spCountry" name="country"' in html and '<select id="spProvince" name="province"' in html
    assert '<option value="España" selected>España</option>' in html
    assert '<option value="">Todos los países</option>' in html
    assert '<option value="Jaén" selected>Jaén</option>' in html
    assert '<option value="">Todas las provincias</option>' in html
    assert "Sin provincia</option>" not in html                         # no es una provincia elegible

    # Dos listas con "Todas"
    assert 'data-geo-list="cities"' in html and 'data-geo-list="zones"' in html
    section = html[html.index('id="spCitiesList"'):]
    assert section.count("data-geo-all") >= 2
    # Poblaciones de Jaén: Jaén y Martos marcadas (activas), Úbeda sin marcar; "Todas" sin marcar
    assert _checkbox(html, "cities", "Jaén") == (True, False)
    assert _checkbox(html, "cities", "Martos") == (True, False)
    assert _checkbox(html, "cities", "Úbeda") == (False, False)
    assert 'name="cities" value="Madrid"' not in html.split('id="spZonesList"')[0].split('id="spCitiesList"')[1]
    # Zonas: las de Jaén y Martos, con "Todas" (marcadas y deshabilitadas: no se envían)
    zones_html = html.split('id="spZonesList"')[1].split("</fieldset>")[0]
    for zone in ("Bulevar", "Centro", "Norte"):
        assert _checkbox(zones_html, "zones", zone) == (True, True), zone
    assert 'value="Casco"' not in zones_html

    # JSON del árbol para el JS, con la provincia deducida del CP
    raw = html.split('<script type="application/json" id="geoData-sp">')[1].split("</script>")[0]
    tree = json.loads(raw)
    assert tree["España"]["Jaén"]["Martos"] == ["Centro", "Norte"]
    assert "Portugal" in tree

    # Operación precargada con la de la alerta, editable, y mínimos marcados
    assert '<option value="Venta" selected>Venta</option>' in html
    assert "Si la cambias, cambia la operación de la alerta" in html
    assert 'data-places-error="spPlacesError"' in html
    assert "Elige la provincia, o al menos una población o zona" in html

    # El modal de seguimiento lleva su propia copia (ids distintos)
    assert 'id="geoData-fu"' in html and 'id="fuProvince"' in html


def test_partial_un_solo_pais_fijo(env):
    """Con un solo país (las propiedades del entorno no tienen país): preseleccionado y fijo."""
    alert = _property_alert(env, "ana", "ana")
    _add_follow_up(env, env.users["ana"], alert, "SIN_RESPUESTA")
    _, html = _detail(env, env.users["ana"], alert, step="profile")
    assert re.search(r'<select id="spCountry" name="country"\s+data-geo="country" disabled', html)
    assert '<input type="hidden" name="country" value="España" data-geo="country-fixed">' in html
    assert '<option value="">Todos los países</option>' not in html
    # Sin perfil: Todas las poblaciones (Jaen, sin CP) y Todas las zonas
    assert _checkbox(html, "cities", "Jaen") == (True, True)


# ---------------------------------------------------------------------------
# Formulario de propiedad: ayuda "Provincia (según CP)" (sin campo nuevo)
# ---------------------------------------------------------------------------

def test_formulario_de_propiedad_muestra_la_provincia_segun_cp():
    from app.web.template_env import templates
    html = templates.env.get_template("properties/form.html").render(clients=[], agents=[], is_admin=True)
    assert 'aria-describedby="cod_postal_provincia"' in html
    assert "Provincia (según CP):" in html and 'id="cod_postal_provincia_value"' in html
    assert 'name="provincia"' not in html                                # solo informativa
    raw = re.search(r"const GEO_CP = (.*);", html).group(1)
    data = json.loads(raw)
    assert data["provincias"]["23"] == "Jaén" and "spain" in data["spain_aliases"]
    assert data["no_province"] == "Sin provincia"
    assert "updateProvinciaHint();" in html


# ---------------------------------------------------------------------------
# Migración
# ---------------------------------------------------------------------------

def test_migracion_country_province():
    path = BACKEND / "alembic" / "versions" / "a0b1c2d3e4f5_criteria_country_province.py"
    text = path.read_text(encoding="utf-8")
    assert "revision = 'a0b1c2d3e4f5'" in text and "down_revision = 'z9a0b1c2d3e4'" in text

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "z9a0b1c2d3e4:a0b1c2d3e4f5", "--sql"],
        cwd=BACKEND, capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        pytest.skip(f"alembic --sql no disponible aquí: {result.stderr[-300:]}")
    sql = result.stdout
    assert "ALTER TABLE buyer_search_criteria ADD COLUMN country VARCHAR" in sql
    assert "ALTER TABLE buyer_search_criteria ADD COLUMN province VARCHAR" in sql
    assert "properties" not in sql.replace("alembic_version", "")   # sin columnas en properties

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "a0b1c2d3e4f5:z9a0b1c2d3e4", "--sql"],
        cwd=BACKEND, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr[-300:]
    assert "DROP COLUMN province" in result.stdout and "DROP COLUMN country" in result.stdout


def test_seguimiento_unico_por_accion_en_constantes():
    """Cambiar la operación no es una etapa ni un seguimiento aparte."""
    assert "OPERACION" not in " ".join(FollowUpActionType.values())
