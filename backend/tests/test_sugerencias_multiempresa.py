"""
Sugerencias del perfil del comprador de las dos empresas (MOYZA y MOES
PREMIUM), con distintivo de empresa, y asociación de una propiedad de la otra
empresa a la alerta (PLAN_SUGERENCIAS_MULTIEMPRESA.md).

Es una excepción acotada al aislamiento por empresa: solo cruzan las
sugerencias (Propuesta de la alerta y ficha del comprador), la cascada y los
tipos del perfil, el buscador manual de la Propuesta y asociar/cambiar la
propiedad desde la alerta. El modal de creación con referencia y la ficha de
la propiedad siguen limitados a la empresa activa.

Rutas y servicios en proceso contra una SQLite en memoria con los modelos
reales; mismo entorno y helpers que tests/test_alert_search.py (MOYZA: Piso
Centro de Ana, Piso Bea, Casa Cara; MOES: Piso MOES, cuyo captador es Ana).

    cd backend && python -m pytest tests/test_sugerencias_multiempresa.py -q
"""
import asyncio
import json
from datetime import timedelta
from urllib.parse import urlencode

from sqlalchemy import event

from app.core.constants import FollowUpActionType
from app.services import buyer_matching
from tests.test_alert_search import (  # noqa: F401  (env es un fixture)
    PROFILE,
    T0,
    _complete_profile,
    _create,
    _detail,
    _flash,
    _link,
    _list_html,
    _reload,
    _request,
    _save_profile,
    _search_alert,
    env,
)


MOES_COLOR_STYLE = "background-color: #8A6D1F"


def _prop(env, title, company, price=130000, status="Activa", estado=None, city="Jaen", zona="Centro",
          cp=None, property_type="Piso", agent="ana"):
    from app.models.property import Property
    prop = Property(title=title, address=f"Calle {title}", city=city, zona=zona, cod_postal=cp,
                    property_type=property_type, business_type="Venta", price=price, status=status,
                    estado_inmueble=estado, num_dormitorios=2, num_banos_aseos=1,
                    company_id=company.id, agent_id=env.agents[agent].id)
    env.db.add(prop)
    env.db.commit()
    return prop


def _criteria(**fields):
    from app.models.buyer_search_criteria import BuyerSearchCriteria
    data = dict(property_type="Piso", business_type="Venta", max_price=200000, zones=["Centro"])
    data.update(fields)
    return BuyerSearchCriteria(**data)


def _search(env, user, alert_id=None, q="Piso"):
    from app.web.routes.alerts import search_properties
    request = _request(env, user, "/alerts/search-properties")
    response = asyncio.run(search_properties(request, q=q, alert_id=alert_id, db=env.db))
    return json.loads(response.body)["results"]


def _proposal(env, user, alert, company=None):
    """Detalle en el paso Propuesta; `company="active"`: filtro "Solo {empresa}"."""
    from app.web.routes.alerts import alert_detail
    params = {"step": "proposal"}
    if company:
        params["company"] = company
    request = _request(env, user, f"/alerts/{alert.id}", query=urlencode(params))
    response = asyncio.run(alert_detail(alert.id, request, step="proposal", confirm_property=None,
                                        company=company, db=env.db))
    return response, response.body.decode("utf-8")


def _buyer_html(env, user, tab):
    from app.web.routes.alerts import buyer_detail
    request = _request(env, user, f"/buyers/{env.buyer.id}", query=f"tab={tab}")
    response = asyncio.run(buyer_detail(env.buyer.id, request, tab=tab, db=env.db))
    return response, response.body.decode("utf-8")


# ---------------------------------------------------------------------------
# Servicio: sugerencias, desglose y cascada
# ---------------------------------------------------------------------------

def test_sugerencias_de_las_dos_empresas_sin_archivadas_ni_no_disponibles(env):
    _prop(env, "MOES Archivada", env.moes, status="Archivada")
    _prop(env, "MOES No disponible", env.moes, estado="No disponible")
    _prop(env, "MOYZA No disponible", env.moyza, estado="No disponible")
    _prop(env, "MOES Reservada", env.moes, status="Reservada")       # no activa: tampoco se sugiere

    titles = [p.title for p in buyer_matching.matching_properties(env.db, _criteria())]
    # Por precio ascendente, sin agrupar por empresa
    assert titles == ["Piso Centro", "Piso MOES", "Piso Bea"]
    # Con empresa: solo esa (filtro "Solo {empresa activa}")
    assert [p.title for p in buyer_matching.matching_properties(env.db, _criteria(), env.moyza.id)] == [
        "Piso Centro", "Piso Bea"]


def test_empresa_y_agente_cargados_sin_n_mas_1(env):
    for i in range(4):
        _prop(env, f"MOES Extra {i}", env.moes, price=150000 + i)
    criteria = _criteria()
    engine = env.db.get_bind()
    statements = []
    listener = lambda *args: statements.append(args[2])  # noqa: E731
    event.listen(engine, "before_cursor_execute", listener)
    try:
        props = buyer_matching.matching_properties(env.db, criteria)
        before = len(statements)
        names = {(p.company.name, p.company.primary_color, p.agent.name) for p in props}
    finally:
        event.remove(engine, "before_cursor_execute", listener)
    assert len(props) == 7 and ("MOES PREMIUM", "#8A6D1F", "Agente Ana") in names
    assert before <= 2                    # propiedades+agentes (JOIN) y empresas (selectinload)
    assert len(statements) == before      # pintar empresa y agente no lanza consultas


def test_desglose_por_empresa(env):
    _prop(env, "MOES Dos", env.moes)
    summary = buyer_matching.matching_summary_by_company(env.db, _criteria(), first_company_id=env.moyza.id)
    assert [(row["company"].name, row["count"]) for row in summary] == [("MOYZA", 2), ("MOES PREMIUM", 2)]
    # La activa primero
    summary = buyer_matching.matching_summary_by_company(env.db, _criteria(), first_company_id=env.moes.id)
    assert [row["company"].name for row in summary] == ["MOES PREMIUM", "MOYZA"]
    # Sin sugerencias: vacío
    assert buyer_matching.matching_summary_by_company(env.db, _criteria(max_price=1)) == []


def test_cascada_y_tipos_del_perfil_incluyen_la_otra_empresa(env):
    from app.web.routes.alerts import _property_filter_values
    _prop(env, "Chalet Andújar", env.moes, city="Andújar", zona="Ribera", cp="23740", property_type="Chalet")
    _prop(env, "MOES Archivada", env.moes, city="Linares", zona="Norte", cp="23700", status="Archivada")

    tree = buyer_matching.geo_options(env.db)
    assert tree["España"]["Jaén"] == {"Andújar": ["Ribera"]}       # solo la tiene MOES
    assert "Linares" not in json.dumps(tree, ensure_ascii=False)    # archivada: fuera
    # Con empresa, como antes
    assert "Jaén" not in buyer_matching.geo_options(env.db, env.moyza.id).get("España", {})

    values = _property_filter_values(env.db)
    assert "Chalet" in values["property_types"] and "Piso" in values["property_types"]
    assert "Andújar" in values["location"]["cities"]


# ---------------------------------------------------------------------------
# Asociar una propiedad de la otra empresa
# ---------------------------------------------------------------------------

def test_asociar_propiedad_de_la_otra_empresa(env):
    alert = _search_alert(env, "ana")
    _complete_profile(env)

    response = _link(env, env.users["ana"], alert, "moes")
    assert response.headers["location"] == f"/alerts/{alert.id}"
    assert _flash(response) == {"category": "success",
                                "message": "Piso MOES (MOES PREMIUM) asociada a la búsqueda de Juan Comprador"}
    stored = _reload(env, alert)
    assert stored.property_id == env.props["moes"].id
    assert stored.company_id == env.moyza.id                 # la alerta no cambia de empresa
    assert stored.agent_id == env.agents["ana"].id
    notes = [f.notes for f in stored.follow_ups if f.action_type == FollowUpActionType.PROPIEDAD_ASOCIADA]
    assert notes == ["Propiedad asociada: Piso MOES (MOES PREMIUM)"]

    # Cambiar a una de MOYZA: la de MOES se nombra con su empresa, la de MOYZA no
    response = _link(env, env.users["ana"], alert, "ana")
    assert _flash(response)["category"] == "success"
    stored = _reload(env, alert)
    assert stored.company_id == env.moyza.id and stored.property_id == env.props["ana"].id
    notes = [f.notes for f in stored.follow_ups if f.action_type == FollowUpActionType.PROPIEDAD_ASOCIADA]
    assert "Cambio de propiedad: de Piso MOES (MOES PREMIUM) a Piso Centro" in notes


def test_asociar_archivada_o_no_disponible_de_la_otra_empresa_rechazada(env):
    alert = _search_alert(env, "ana")
    _complete_profile(env)
    for key, prop in (("archivada", _prop(env, "MOES Archivada", env.moes, status="Archivada")),
                      ("no_disp", _prop(env, "MOES Fuera", env.moes, estado="No disponible"))):
        env.props[key] = prop
        response = _link(env, env.users["ana"], alert, key)
        assert response.headers["location"] == f"/alerts/{alert.id}?step=proposal"
        assert _flash(response) == {"category": "error", "message": f"{prop.title} (MOES PREMIUM) no está disponible"}
    assert _reload(env, alert).property_id is None

    # Inexistente
    env.props["nada"] = type("P", (), {"id": 999999})()
    assert _flash(_link(env, env.users["ana"], alert, "nada")) == {"category": "error",
                                                                  "message": "Propiedad no encontrada"}


def test_duplicado_con_propiedad_de_la_otra_empresa(env):
    first = _search_alert(env, "ana")
    _complete_profile(env)
    _link(env, env.users["ana"], first, "moes")
    second = _search_alert(env, "ana", created_at=T0 + timedelta(hours=1), business_type="Alquiler")

    response = _link(env, env.users["ana"], second, "moes")
    assert response.headers["location"] == (
        f"/alerts/{second.id}?step=proposal&confirm_property={env.props['moes'].id}#propuesta")
    assert _flash(response)["category"] == "warning"
    assert "alerta abierta sobre Piso MOES (MOES PREMIUM)" in _flash(response)["message"]

    # El detalle encuentra la propiedad de la otra empresa para el aviso
    _, html = _detail(env, env.users["ana"], second, step="proposal", confirm_property=str(env.props["moes"].id))
    assert "ya tiene una alerta abierta sobre Piso MOES" in html and "Asociar de todas formas" in html

    response = _link(env, env.users["ana"], second, "moes", confirm="1")
    assert _flash(response)["category"] == "success"
    stored = _reload(env, second)
    assert stored.property_id == env.props["moes"].id and stored.company_id == env.moyza.id


# ---------------------------------------------------------------------------
# Buscadores: el de la Propuesta cruza, el del modal de creación no
# ---------------------------------------------------------------------------

def test_buscador_de_la_propuesta_trae_las_dos_empresas_con_su_empresa(env):
    alert = _search_alert(env, "ana")
    _complete_profile(env)

    results = {r["title"]: r for r in _search(env, env.users["ana"], str(alert.id))}
    assert sorted(results) == ["Piso Bea", "Piso Centro", "Piso MOES"]
    assert results["Piso MOES"]["company"] == {"id": env.moes.id, "name": "MOES PREMIUM",
                                               "color": "#8A6D1F", "active": False}
    assert results["Piso Centro"]["company"]["active"] is True
    assert "owner" not in json.dumps(results)                 # nunca el propietario


def test_buscador_del_modal_de_creacion_sigue_limitado(env):
    # Ana es captadora de Piso MOES, pero con MOYZA activa el modal solo ofrece sus propiedades de MOYZA
    assert [r["title"] for r in _search(env, env.users["ana"])] == ["Piso Centro"]
    assert sorted(r["title"] for r in _search(env, env.admin)) == ["Piso Bea", "Piso Centro"]
    assert all("company" not in r for r in _search(env, env.admin))
    # Una alerta de otra empresa (o inexistente) no abre el buscador cruzado
    assert sorted(r["title"] for r in _search(env, env.admin, alert_id="999")) == ["Piso Bea", "Piso Centro"]


def test_alta_con_referencia_y_ficha_de_la_otra_empresa_siguen_limitadas(env):
    from app.models.property_alert import PropertyAlert
    from app.web.routes.properties import property_detail

    response = _create(env, env.admin, property_id=env.props["moes"].id, agent_id=str(env.agents["ana"].id))
    assert _flash(response) == {"category": "error", "message": "Propiedad no encontrada"}
    assert env.db.query(PropertyAlert).count() == 0

    request = _request(env, env.admin, f"/properties/{env.props['moes'].id}")
    response = asyncio.run(property_detail(env.props["moes"].id, request, db=env.db))
    assert response.status_code == 302 and response.headers["location"] == "/properties"


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

def test_propuesta_con_sugerencias_de_la_otra_empresa(env):
    alert = _search_alert(env, "ana")
    _save_profile(env, env.users["ana"], alert, form=PROFILE)

    response, html = _proposal(env, env.users["ana"], alert)
    ctx = response.context
    assert [p.title for p in ctx["suggestions"]] == ["Piso Centro", "Piso MOES", "Piso Bea"]
    assert [(r["company"].name, r["count"]) for r in ctx["suggestions_by_company"]] == [
        ("MOYZA", 2), ("MOES PREMIUM", 1)]
    # Desglose en la cabecera y filtro de un clic
    assert "3 propiedades sugeridas · 2 MOYZA · 1 MOES PREMIUM · de cualquier agente" in html
    assert f'href="/alerts/{alert.id}?step=proposal&amp;company=active#propuesta"' in html
    assert ">Solo MOYZA</a>" in html
    # Distintivo en cada tarjeta, con el color de la empresa en el punto
    # (el negro de MOYZA también lo usa el sidebar: se comprueba por el title del badge)
    assert MOES_COLOR_STYLE in html
    assert html.count('title="Propiedad de MOES PREMIUM"') == 1 and html.count('title="Propiedad de MOYZA"') == 2
    # Ana es la captadora de Piso MOES, pero es de la otra empresa: sin "Ver"
    assert f'href="/properties/{env.props["moes"].id}"' not in html
    assert "Cambia de empresa para ver la ficha" in html
    assert f'href="/properties/{env.props["ana"].id}"' in html          # la suya de MOYZA, sí
    # Se puede asociar la de MOES
    assert f'name="property_id" value="{env.props["moes"].id}"' in html
    # El buscador manual explica que busca en las dos
    assert "disponibles de las dos empresas" in html


def test_filtro_solo_empresa_activa(env):
    alert = _search_alert(env, "ana")
    _save_profile(env, env.users["ana"], alert, form=PROFILE)

    response, html = _proposal(env, env.users["ana"], alert, company="active")
    ctx = response.context
    assert ctx["only_active_company"] is True and ctx["suggestions_total"] == 2
    assert [p.title for p in ctx["suggestions"]] == ["Piso Centro", "Piso Bea"]
    assert "2 propiedades sugeridas de MOYZA" in html and "Ver las de todas las empresas" in html
    assert MOES_COLOR_STYLE not in html

    # Solo hay de la otra empresa: estado vacío con el enlace de vuelta
    for key in ("ana", "bea", "cara"):
        env.props[key].status = "Archivada"
    env.db.commit()
    response, html = _proposal(env, env.users["ana"], alert, company="active")
    assert response.context["suggestions"] == []
    assert "No hay propiedades de MOYZA que encajen con su perfil" in html
    assert "Ver las de todas las empresas" in html
    # Sin filtro: la de MOES, sin enlace "Solo MOYZA" (solo hay de una empresa)
    response, html = _proposal(env, env.users["ana"], alert)
    assert [p.title for p in response.context["suggestions"]] == ["Piso MOES"]
    assert ">Solo MOYZA</a>" not in html and "1 propiedad sugerida · 1 MOES PREMIUM" in html


def test_tras_asociar_una_de_moes_badge_en_detalle_listado_y_ficha(env):
    alert = _search_alert(env, "ana")
    _save_profile(env, env.users["ana"], alert, form=PROFILE)
    _link(env, env.users["ana"], alert, "moes")
    assert _reload(env, alert).company_id == env.moyza.id

    # Detalle: tarjeta de la propiedad con el distintivo y sin enlace a su ficha
    response, html = _detail(env, env.users["ana"], alert)
    assert response.context["property_other_company"] is True
    assert "Piso MOES" in html and MOES_COLOR_STYLE in html
    assert f'href="/properties/{env.props["moes"].id}"' not in html
    assert "Cambia de empresa para ver la ficha" in html
    # Admin: tampoco enlaza (la ficha da "no encontrada" fuera de su empresa)
    _, html = _detail(env, env.admin, alert)
    assert f'href="/properties/{env.props["moes"].id}"' not in html and MOES_COLOR_STYLE in html

    # Propuesta: la asociada (de MOES) sale marcada "Asociada ahora" con su distintivo
    response, html = _proposal(env, env.users["ana"], alert)
    assert response.context["current_in_suggestions"] is True and "Asociada ahora" in html

    # Listado /alerts: distintivo solo en la de la otra empresa
    html = _list_html(env, env.admin)
    assert "Piso MOES" in html and 'title="Propiedad de MOES PREMIUM"' in html
    assert 'title="Propiedad de MOYZA"' not in html

    # Ficha del comprador: columna Propiedad con el distintivo; compatibles de las dos
    response, html = _buyer_html(env, env.admin, "alerts")
    assert 'title="Propiedad de MOES PREMIUM"' in html
    titles = [p.title for p in response.context["matching_properties"]]
    assert titles == ["Piso Centro", "Piso MOES", "Piso Bea"]
    # En compatibles, la de MOES sin "Crear alerta" (el alta con referencia sigue limitada)
    assert f'data-prop-id="{env.props["moes"].id}"' not in html
    assert f'data-prop-id="{env.props["ana"].id}"' in html
    assert "De otra empresa: para proponerla, asóciala desde la alerta del comprador" in html


def test_alerta_de_moes_ve_las_de_moyza_con_su_distintivo(env):
    """Simétrico: con MOES activa, las de MOYZA llevan el distintivo y no enlazan."""
    from app.models.property_alert import PropertyAlert
    from app.services import alert_assignment_service as svc
    from app.web.routes.alerts import alert_detail

    from app.models.buyer import Buyer
    from app.models.buyer_search_criteria import BuyerSearchCriteria
    buyer = Buyer(name="Comprador MOES", phone="34600999888", company_id=env.moes.id, created_by=env.admin.id)
    env.db.add(buyer)
    env.db.flush()
    env.db.add(BuyerSearchCriteria(buyer_id=buyer.id, property_type="Piso", business_type="Venta",
                                   max_price=200000, max_bedrooms=3, cities=["Jaen"], zones=["Centro"]))
    alert = PropertyAlert(company_id=env.moes.id, origin="search", buyer_id=buyer.id, lead_name=buyer.name,
                          business_type="Venta", status="PENDING", priority="NORMAL",
                          created_by=env.admin.id, created_at=T0)
    env.db.add(alert)
    svc.assign(env.db, alert, env.agents["ana"], env.admin, None, is_new=True, now=T0)
    env.db.commit()

    request = _request(env, env.admin, f"/alerts/{alert.id}", company=env.moes, query="step=proposal")
    response = asyncio.run(alert_detail(alert.id, request, step="proposal", confirm_property=None,
                                        company=None, db=env.db))
    html = response.body.decode("utf-8")
    assert [r["company"].name for r in response.context["suggestions_by_company"]] == ["MOES PREMIUM", "MOYZA"]
    assert "3 propiedades sugeridas · 1 MOES PREMIUM · 2 MOYZA" in html
    assert f'href="/properties/{env.props["moes"].id}"' in html          # admin, de la activa
    assert f'href="/properties/{env.props["ana"].id}"' not in html       # de la otra
    assert ">Solo MOES PREMIUM</a>" in html
