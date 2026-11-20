"""
La ficha del comprador es de consulta; el trabajo se hace desde la alerta
(PLAN_FICHA_COMPRADOR_CONSULTA.md).

Con una alerta abierta del usuario con el comprador (`work_alert`), el perfil
se guarda en esa alerta y las compatibles se añaden a su lista; sin ella, la
ficha es de solo lectura y ofrece «Crear búsqueda», que crea la alerta sin
referencia y lleva a su detalle. Entorno de test_alert_search.py:

    cd backend && python -m pytest tests/test_buyer_detail_work_alert.py -q
"""
import asyncio
from datetime import timedelta
from urllib.parse import urlencode

from app.core.constants import AlertOrigin, AlertStatus, FollowUpActionType
from tests.test_alert_search import (  # noqa: F401  (env es un fixture)
    PROFILE,
    T0,
    _complete_profile,
    _create,
    _flash,
    _property_alert,
    _reload,
    _request,
    _search_alert,
    env,
)
from tests.test_alert_interest_properties import _add


def _ficha(env, user, tab="criteria"):
    from app.web.routes.alerts import buyer_detail
    request = _request(env, user, f"/buyers/{env.buyer.id}", query=urlencode({"tab": tab}))
    response = asyncio.run(buyer_detail(env.buyer.id, request, tab=tab, db=env.db))
    return response, response.body.decode("utf-8")


def _create_search(env, user, business_type="Venta", agent_id=None, confirm=None, return_to="buyer"):
    """Lo que envía el modal «Crear búsqueda» de la ficha: comprador, sin propiedad, return_to=buyer."""
    return _create(env, user, business_type=business_type, agent_id=str(agent_id) if agent_id else None,
                   confirm_duplicate=confirm, return_to=return_to)


def _save_profile_via_alert(env, user, alert, form=None):
    from app.web.routes.alerts import save_alert_search_profile
    form = dict(PROFILE if form is None else form)
    fields = {k: form.get(k) for k in ("property_type", "min_price", "max_price", "min_bedrooms",
                                       "max_bedrooms", "min_bathrooms", "elevator", "garage", "notes")}
    request = _request(env, user, f"/alerts/{alert.id}/search-profile", "POST", form=form)
    return asyncio.run(save_alert_search_profile(alert.id, request, db=env.db, **fields))


def _follow_ups(env, alert):
    from app.models.alert_follow_up import AlertFollowUp
    env.db.expire_all()
    return env.db.query(AlertFollowUp).filter(AlertFollowUp.alert_id == alert.id).all()


# ---------------------------------------------------------------------------
# Con alerta abierta del agente
# ---------------------------------------------------------------------------

def test_con_alerta_abierta_el_perfil_y_las_compatibles_van_a_la_alerta(env):
    alert = _search_alert(env, "ana")
    _complete_profile(env)
    _add(env, env.users["ana"], alert, "moes")

    response, html = _ficha(env, env.users["ana"])
    assert response.context["work_alert"].id == alert.id
    assert f"se hace desde su alerta #{alert.id}" in html and f'href="/alerts/{alert.id}"' in html
    # Perfil: formulario enviado a la alerta, responsable = agente de la alerta
    assert f'action="/alerts/{alert.id}/search-profile"' in html
    assert '/search-criteria"' not in html
    assert "Agente Ana" in html and "agente de la alerta" in html
    assert 'name="agent_id" id="bcAgent"' not in html
    # Compatibles: la de MOES «En su lista»; las otras con casilla; barra hacia la alerta
    response, html = _ficha(env, env.users["ana"], tab="matches")
    assert response.context["work_interest_ids"] == {env.props["moes"].id}
    assert "En su lista" in html
    assert f'value="{env.props["ana"].id}" form="interestForm"' in html
    assert f'value="{env.props["bea"].id}" form="interestForm"' in html
    assert f'value="{env.props["moes"].id}" form="interestForm"' not in html
    assert f'action="/alerts/{alert.id}/interest-properties"' in html and "data-interest-form" in html
    assert "Crear búsqueda" not in html and "Crear alerta" not in html


def test_guardar_el_perfil_desde_la_ficha_registra_contactado_en_la_alerta(env):
    alert = _search_alert(env, "ana")
    response = _save_profile_via_alert(env, env.users["ana"], alert)
    assert response.headers["location"].startswith(f"/alerts/{alert.id}?step=proposal")
    rows = _follow_ups(env, alert)
    assert [f.action_type for f in rows] == [FollowUpActionType.CONTACTADO]
    assert _reload(env, alert).status == AlertStatus.IN_PROGRESS


def test_el_admin_trabaja_desde_cualquier_alerta_abierta_del_comprador(env):
    alert = _property_alert(env, "ana", "bea")
    response, html = _ficha(env, env.admin)
    assert response.context["work_alert"].id == alert.id
    assert f'action="/alerts/{alert.id}/search-profile"' in html


# ---------------------------------------------------------------------------
# Sin alerta abierta
# ---------------------------------------------------------------------------

def test_sin_alerta_abierta_solo_lectura_y_crear_busqueda(env):
    _complete_profile(env)
    response, html = _ficha(env, env.users["ana"])
    assert response.context["work_alert"] is None
    assert "Sin alerta abierta" in html and html.count('data-modal-open="createSearchModal"') >= 2
    assert 'id="bcPropertyType"' not in html and '/search-profile"' not in html
    assert "Piso" in html and "Para cambiar el perfil" in html
    # Compatibles sin casillas ni barra
    _, html = _ficha(env, env.users["ana"], tab="matches")
    assert "data-interest-check" not in html and "data-interest-form" not in html
    assert "crea su búsqueda" in html
    # El modal lleva el comprador, sin propiedad y con vuelta a la ficha
    assert f'name="buyer_id" value="{env.buyer.id}"' in html and 'name="return_to" value="buyer"' in html
    assert '<option value="Venta" selected>Venta</option>' in html


def test_sin_perfil_la_ficha_dice_sin_definir(env):
    _, html = _ficha(env, env.users["ana"])
    assert "Aún sin definir" in html and "Para registrar el perfil" in html


def test_alerta_cerrada_o_de_otro_agente_no_cuenta(env):
    closed = _search_alert(env, "ana")
    closed.status = AlertStatus.COMPLETED
    env.db.commit()
    _property_alert(env, "bea", "bea")      # abierta, pero de Bea
    response, html = _ficha(env, env.users["ana"])
    assert response.context["work_alert"] is None and "Sin alerta abierta" in html


# ---------------------------------------------------------------------------
# Crear búsqueda desde la ficha
# ---------------------------------------------------------------------------

def test_el_agente_crea_la_busqueda_y_va_a_la_alerta(env):
    from app.models.property_alert import PropertyAlert
    response = _create_search(env, env.users["ana"])
    alert = env.db.query(PropertyAlert).filter(PropertyAlert.buyer_id == env.buyer.id).one()
    assert response.headers["location"] == f"/alerts/{alert.id}"
    assert _flash(response)["category"] == "success"
    assert alert.origin == AlertOrigin.SEARCH and alert.property_id is None
    assert alert.agent_id == env.agents["ana"].id and alert.company_id == env.moyza.id
    assert alert.business_type == "Venta"
    # Ahora la ficha trabaja desde ella
    response, _ = _ficha(env, env.users["ana"])
    assert response.context["work_alert"].id == alert.id


def test_el_admin_elige_agente_y_sin_el_vuelve_a_la_ficha(env):
    response = _create_search(env, env.admin)
    assert response.headers["location"] == f"/buyers/{env.buyer.id}"
    assert _flash(response)["category"] == "error"

    response = _create_search(env, env.admin, agent_id=env.agents["bea"].id)
    assert response.headers["location"].startswith("/alerts/")
    assert "asignada a Agente Bea" in _flash(response)["message"]


def test_busqueda_duplicada_vuelve_a_la_pestana_de_alertas(env):
    _search_alert(env, "bea", created_at=T0 - timedelta(days=1))   # abierta, de otro agente
    response = _create_search(env, env.users["ana"])
    assert response.headers["location"] == f"/buyers/{env.buyer.id}?tab=alerts"
    assert _flash(response)["category"] == "warning"
    assert "ya tiene una búsqueda de Venta abierta" in _flash(response)["message"]


def test_sin_return_to_el_alta_sigue_yendo_al_listado(env):
    response = _create_search(env, env.users["ana"], return_to=None)
    assert response.headers["location"] == "/alerts"
