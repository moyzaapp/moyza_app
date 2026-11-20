"""
Varias propiedades de interés por alerta (PLAN_ALERTA_VARIAS_PROPIEDADES.md).

En el paso Propuesta el agente marca varias propiedades (de MOYZA y MOES y de
cualquier agente) y se añaden a la lista de la alerta: la primera ocupa
`property_alerts.property_id` y el resto `alert_properties`. Cada cambio deja
un seguimiento «Propiedad asociada». Entorno de test_alert_search.py (SQLite
en memoria, rutas en proceso):

    cd backend && python -m pytest tests/test_alert_interest_properties.py -q
"""
import asyncio
from datetime import timedelta

from app.core.constants import AlertStatus, FollowUpActionType
from tests.test_alert_search import (  # noqa: F401  (env es un fixture)
    T0,
    _complete_profile,
    _detail,
    _flash,
    _list_html,
    _property_alert,
    _reload,
    _request,
    _search_alert,
    env,
)


ASSOC = FollowUpActionType.PROPIEDAD_ASOCIADA


def _add(env, user, alert, *prop_keys, confirm=None, ids=None):
    from app.web.routes.alerts import add_interest_properties
    values = ids if ids is not None else [str(env.props[k].id) for k in prop_keys]
    request = _request(env, user, f"/alerts/{alert.id}/interest-properties", "POST",
                       form={"property_ids": values})
    return asyncio.run(add_interest_properties(alert.id, request, property_ids=values,
                                               confirm_duplicate=confirm, db=env.db))


def _remove(env, user, alert, prop_key):
    from app.web.routes.alerts import remove_interest_property
    pid = env.props[prop_key].id
    request = _request(env, user, f"/alerts/{alert.id}/interest-properties/{pid}/remove", "POST", form={})
    return asyncio.run(remove_interest_property(alert.id, pid, request, db=env.db))


def _titles(alert):
    return [p.title for p in alert.interest_properties]


def _notes(env, alert):
    from app.models.alert_follow_up import AlertFollowUp
    rows = (env.db.query(AlertFollowUp)
            .filter(AlertFollowUp.alert_id == alert.id, AlertFollowUp.action_type == ASSOC)
            .order_by(AlertFollowUp.id).all())
    return [r.notes for r in rows]


# ---------------------------------------------------------------------------
# Añadir
# ---------------------------------------------------------------------------

def test_anade_varias_de_dos_empresas_y_de_otro_agente(env):
    alert = _search_alert(env, "ana")
    _complete_profile(env)

    response = _add(env, env.users["ana"], alert, "bea", "moes")
    assert response.status_code == 302
    assert response.headers["location"] == f"/alerts/{alert.id}?step=proposal#propuesta"
    assert _flash(response) == {"category": "success",
                                "message": "2 propiedades añadidas a la lista de Juan Comprador"}

    stored = _reload(env, alert)
    # La primera pasa a ser la de la alerta; la empresa y el agente no cambian
    assert stored.property_id == env.props["bea"].id and stored.property_linked_at is not None
    assert _titles(stored) == ["Piso Bea", "Piso MOES"]
    assert stored.extra_properties_count == 1
    assert stored.company_id == env.moyza.id and stored.agent_id == env.agents["ana"].id
    assert stored.status == AlertStatus.IN_PROGRESS
    # Un solo seguimiento, con la empresa de la de MOES
    assert _notes(env, stored) == ["Propiedades de interés: Piso Bea, Piso MOES (MOES PREMIUM)"]


def test_anadir_mas_tarde_y_repetidas_se_ignoran(env):
    alert = _search_alert(env, "ana")
    _complete_profile(env)
    _add(env, env.users["ana"], alert, "ana")

    response = _add(env, env.users["ana"], alert, "ana", "moes")
    assert _flash(response)["message"] == "Piso MOES (MOES PREMIUM) añadida a la lista de Juan Comprador"
    stored = _reload(env, alert)
    assert _titles(stored) == ["Piso Centro", "Piso MOES"]
    assert _notes(env, stored) == ["Propiedad de interés: Piso Centro",
                                   "Propiedad de interés: Piso MOES (MOES PREMIUM)"]

    response = _add(env, env.users["ana"], alert, "ana")
    assert _flash(response) == {"category": "info", "message": "Piso Centro ya está en su lista"}
    assert len(_notes(env, _reload(env, alert))) == 2


def test_alerta_con_referencia_anade_a_su_propiedad(env):
    alert = _property_alert(env, "ana", "ana")
    _complete_profile(env)
    _add(env, env.users["ana"], alert, "bea")
    stored = _reload(env, alert)
    assert stored.property_id == env.props["ana"].id and stored.property_linked_at is None
    assert _titles(stored) == ["Piso Centro", "Piso Bea"]


def test_no_disponible_se_anade_y_archivada_no_anade_ninguna(env):
    alert = _search_alert(env, "ana")
    _complete_profile(env)
    # Archivada: no se añade ninguna de las marcadas
    env.props["moes"].status = "Archivada"
    env.db.commit()
    response = _add(env, env.users["ana"], alert, "bea", "moes")
    assert _flash(response) == {"category": "error", "message": "Piso MOES (MOES PREMIUM) no está disponible"}
    assert _titles(_reload(env, alert)) == []

    # "No disponible" (en el inventario, sin publicar) sí se puede añadir
    env.props["moes"].status = "Activa"
    env.props["moes"].estado_inmueble = "No disponible"
    env.db.commit()
    response = _add(env, env.users["ana"], alert, "moes")
    assert _flash(response)["category"] == "success"
    assert _titles(_reload(env, alert)) == ["Piso MOES"]

    response = _add(env, env.users["ana"], alert, ids=[])
    assert _flash(response) == {"category": "error", "message": "Marca al menos una propiedad"}
    response = _add(env, env.users["ana"], alert, ids=["99999"])
    assert _flash(response) == {"category": "error", "message": "Propiedad no encontrada"}
    # Solo queda la nota de la propiedad No disponible añadida
    assert _notes(env, _reload(env, alert)) == ["Propiedad de interés: Piso MOES (MOES PREMIUM)"]


def test_exige_perfil_y_ser_el_agente_de_la_alerta(env):
    alert = _search_alert(env, "ana")

    response = _add(env, env.users["ana"], alert, "bea")
    assert response.headers["location"] == f"/alerts/{alert.id}?step=profile#propuesta"
    assert _flash(response)["category"] == "error"

    _complete_profile(env)
    response = _add(env, env.users["bea"], alert, "bea")
    assert response.headers["location"] == "/alerts"
    assert _flash(response) == {"category": "error", "message": "No tienes permisos para esta alerta"}

    # El admin sí
    response = _add(env, env.admin, alert, "bea")
    assert _flash(response)["category"] == "success"
    assert _titles(_reload(env, alert)) == ["Piso Bea"]


def test_alerta_cerrada_no_anade(env):
    alert = _search_alert(env, "ana")
    _complete_profile(env)
    alert.status = AlertStatus.COMPLETED
    env.db.commit()
    response = _add(env, env.users["ana"], alert, "bea")
    assert _flash(response) == {"category": "error", "message": "La alerta está cerrada"}


# ---------------------------------------------------------------------------
# Duplicados
# ---------------------------------------------------------------------------

def test_duplicado_pide_confirmacion_del_lote_entero(env):
    alert = _search_alert(env, "ana")
    other = _property_alert(env, "bea", "bea", created_at=T0 - timedelta(days=1))
    _complete_profile(env)

    response = _add(env, env.users["ana"], alert, "ana", "bea")
    ids = f"{env.props['ana'].id},{env.props['bea'].id}"
    assert response.headers["location"] == f"/alerts/{alert.id}?step=proposal&confirm_property={ids}#propuesta"
    flash = _flash(response)
    assert flash["category"] == "warning"
    assert f"Piso Bea (#{other.id})" in flash["message"] and "No se ha añadido nada" in flash["message"]
    assert _titles(_reload(env, alert)) == []

    # El aviso reenvía el lote entero con la confirmación
    _, html = _detail(env, env.users["ana"], alert, step="proposal", confirm_property=ids)
    assert "Juan Comprador ya tiene una alerta abierta sobre Piso Bea" in html
    assert "Añadir de todas formas" in html
    assert f'name="property_ids" value="{env.props["ana"].id}"' in html
    assert f'href="/alerts/{other.id}"' not in html  # la otra es de Bea

    response = _add(env, env.users["ana"], alert, "ana", "bea", confirm="1")
    assert _flash(response)["category"] == "success"
    stored = _reload(env, alert)
    assert _titles(stored) == ["Piso Centro", "Piso Bea"]
    assert f"alerta abierta #{other.id}" in stored.message


def test_duplicado_detectado_en_la_lista_de_otra_alerta(env):
    """find_duplicate_alerts también mira las propiedades adicionales."""
    from app.services.alert_duplicate_service import find_duplicate_alerts
    first = _search_alert(env, "ana")
    _complete_profile(env)
    _add(env, env.users["ana"], first, "ana", "bea")

    found = find_duplicate_alerts(env.db, env.moyza.id, env.buyer.id, env.props["bea"].id)
    assert [a.id for a in found["open"]] == [first.id]

    second = _search_alert(env, "ana", created_at=T0 + timedelta(hours=1))
    response = _add(env, env.users["ana"], second, "bea")
    assert _flash(response)["category"] == "warning"
    assert f"Piso Bea (#{first.id})" in _flash(response)["message"]


# ---------------------------------------------------------------------------
# Quitar
# ---------------------------------------------------------------------------

def test_quitar_adicional_y_principal_con_relevo(env):
    alert = _search_alert(env, "ana")
    _complete_profile(env)
    _add(env, env.users["ana"], alert, "ana", "bea", "moes")

    response = _remove(env, env.users["ana"], alert, "bea")
    assert _flash(response) == {"category": "success", "message": "Piso Bea quitada de su lista"}
    assert _titles(_reload(env, alert)) == ["Piso Centro", "Piso MOES"]

    # La principal: la siguiente ocupa su lugar
    _remove(env, env.users["ana"], alert, "ana")
    stored = _reload(env, alert)
    assert stored.property_id == env.props["moes"].id
    assert _titles(stored) == ["Piso MOES"] and stored.extra_properties_count == 0

    # La única no se quita
    response = _remove(env, env.users["ana"], alert, "moes")
    assert _flash(response)["category"] == "warning"
    assert _titles(_reload(env, alert)) == ["Piso MOES"]

    assert _notes(env, _reload(env, alert))[1:] == ["Quitada de su lista: Piso Bea",
                                                    "Quitada de su lista: Piso Centro"]


def test_quitar_una_que_no_esta(env):
    alert = _search_alert(env, "ana")
    _complete_profile(env)
    _add(env, env.users["ana"], alert, "ana", "bea")
    response = _remove(env, env.users["ana"], alert, "moes")
    assert _flash(response) == {"category": "error", "message": "Esa propiedad no está en su lista"}


# ---------------------------------------------------------------------------
# Interfaz
# ---------------------------------------------------------------------------

def test_propuesta_con_casillas_y_su_lista(env):
    alert = _search_alert(env, "ana")
    _complete_profile(env)

    response, html = _detail(env, env.users["ana"], alert, step="proposal")
    assert response.context["interest_properties"] == []
    # Una casilla por sugerencia (las tres de las dos empresas), un único botón
    assert html.count('form="interestForm" data-interest-check') == 3
    assert 'id="interestForm"' in html
    assert f'action="/alerts/{alert.id}/interest-properties"' in html
    assert "Su lista (" not in html

    _add(env, env.users["ana"], alert, "ana", "moes")
    response, html = _detail(env, env.users["ana"], alert, step="proposal")
    assert [p.title for p in response.context["interest_properties"]] == ["Piso Centro", "Piso MOES"]
    assert "Su lista (2)" in html
    # Las de la lista: «En su lista» y Quitar; sin casilla
    assert f'value="{env.props["ana"].id}" form="interestForm"' not in html
    assert f'value="{env.props["bea"].id}" form="interestForm"' in html
    assert f'/interest-properties/{env.props["moes"].id}/remove' in html
    assert "En su lista" in html


def test_detalle_y_listado_muestran_el_resto_de_su_lista(env):
    alert = _search_alert(env, "ana")
    _complete_profile(env)
    _add(env, env.users["ana"], alert, "ana", "bea", "moes")

    _, html = _detail(env, env.users["ana"], alert)
    assert "Otras propiedades de interés (2)" in html and "Gestionar su lista" in html
    assert "agente: Agente Bea" in html

    html = _list_html(env, env.admin)
    assert "+2 más" in html


def test_seguimiento_visible_para_el_agente(env):
    alert = _search_alert(env, "ana")
    _complete_profile(env)
    _add(env, env.users["ana"], alert, "bea", "moes")
    response, html = _detail(env, env.users["ana"], alert)
    assert any(f.action_type == ASSOC for f in response.context["follow_ups"])
    assert "Propiedades de interés: Piso Bea, Piso MOES (MOES PREMIUM)" in html


def test_migracion_presente():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "alembic" / "versions"
              / "k7r8w9x0y1z2_add_alert_properties.py").read_text()
    assert "down_revision = 'j6q7v8c9m0d1'" in source and "'alert_properties'" in source
