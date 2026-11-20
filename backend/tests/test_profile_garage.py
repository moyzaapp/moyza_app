"""
Filtro de garaje en el perfil del comprador.

`buyer_search_criteria.garage`: NULL = indiferente, True = con garaje
(`num_garaje_aparcam >= 1`; una propiedad sin el dato o con 0 cuenta como sin
garaje). Select opcional de dos opciones: no existe "Sin garaje".
Mismo entorno y helpers que tests/test_profile_elevator.py.

    cd backend && python -m pytest tests/test_profile_garage.py -q
"""
import pytest

from app.core.constants import GaragePreference
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
    _save_profile,
    env,
)
from tests.test_profile_location import _criteria, _save_buyer_profile


def _with_garages(env):
    """Propiedades del entorno con distintas plazas (Piso MOES sin dato)."""
    env.props["ana"].num_garaje_aparcam = 1       # Piso Centro
    env.props["bea"].num_garaje_aparcam = 0       # Piso Bea
    env.props["cara"].num_garaje_aparcam = 2      # Casa Cara (otro tipo)
    env.props["moes"].num_garaje_aparcam = None   # Piso MOES
    env.db.commit()


def _titles(env, garage):
    from app.models.buyer_search_criteria import BuyerSearchCriteria
    criteria = BuyerSearchCriteria(max_price=1000000, garage=garage)
    return sorted(p.title for p in buyer_matching.matching_properties(env.db, criteria))


# ---------------------------------------------------------------------------
# Servicio
# ---------------------------------------------------------------------------

def test_opciones_del_select():
    assert GaragePreference.choices() == (("", "Indiferente"), ("yes", "Con garaje"))


@pytest.mark.parametrize("raw, parsed", [
    ("yes", True), (" YES ", True), ("", None), (None, None), ("no", None), ("cualquiera", None),
])
def test_parse_garage(raw, parsed):
    assert buyer_matching.parse_garage(raw) is parsed


def test_valor_del_select_y_apply_profile():
    from app.models.buyer_search_criteria import BuyerSearchCriteria
    criteria = BuyerSearchCriteria()
    assert buyer_matching.garage_value(None) == "" and buyer_matching.garage_value(criteria) == ""

    buyer_matching.apply_profile(criteria, garage="yes")
    assert criteria.garage is True and buyer_matching.garage_value(criteria) == "yes"
    # Indiferente (o no enviar el campo) lo deja vacío
    buyer_matching.apply_profile(criteria, garage="")
    assert criteria.garage is None
    buyer_matching.apply_profile(criteria, garage="yes")
    buyer_matching.apply_profile(criteria)
    assert criteria.garage is None


def test_cruce_con_las_propiedades(env):
    _with_garages(env)
    assert _titles(env, None) == ["Casa Cara", "Piso Bea", "Piso Centro", "Piso MOES"]
    # Con garaje: 1 plaza o más; sin dato (Piso MOES) o 0 (Piso Bea) no salen
    assert _titles(env, True) == ["Casa Cara", "Piso Centro"]


def test_garaje_y_ascensor_se_combinan(env):
    from app.models.buyer_search_criteria import BuyerSearchCriteria
    _with_garages(env)
    env.props["ana"].num_ascensores = 0
    env.props["cara"].num_ascensores = 1
    env.db.commit()
    criteria = BuyerSearchCriteria(max_price=1000000, garage=True, elevator=True)
    assert [p.title for p in buyer_matching.matching_properties(env.db, criteria)] == ["Casa Cara"]


def test_resumen_con_garaje():
    from app.models.buyer_search_criteria import BuyerSearchCriteria
    criteria = BuyerSearchCriteria(property_type="Piso", max_price=150000, garage=True)
    assert buyer_matching.criteria_summary(criteria) == "Piso · con garaje · ≤ 150.000 €"
    criteria.elevator = True
    assert buyer_matching.criteria_summary(criteria) == "Piso · con ascensor · con garaje · ≤ 150.000 €"
    criteria.garage = None
    assert "garaje" not in buyer_matching.criteria_summary(criteria)


def test_el_garaje_cuenta_como_dato_del_perfil():
    from app.web.routes.alerts import PROFILE_TEXT_FIELDS, _profile_values_present
    assert "garage" in PROFILE_TEXT_FIELDS
    empty = {name: None for name in (*PROFILE_TEXT_FIELDS, "province", "notes")}
    empty.update(zones=[], cities=[])
    assert not _profile_values_present(dict(empty, garage=""))           # Indiferente
    assert _profile_values_present(dict(empty, garage="yes"))


# ---------------------------------------------------------------------------
# Rutas: paso Perfil, Contactado y ficha del comprador
# ---------------------------------------------------------------------------

def test_paso_perfil_guarda_el_garaje(env):
    _with_garages(env)
    alert = _property_alert(env, "ana", "ana")
    response = _save_profile(env, env.users["ana"], alert, form=dict(CONTACT_PROFILE, garage="yes"))
    assert response.headers["location"] == f"/alerts/{alert.id}?step=proposal"
    # Solo Piso Centro: Piso Bea con 0 plazas, Piso MOES sin dato, Casa Cara es otro tipo
    assert _flash(response)["message"].endswith(": 1 propiedad sugerida")
    assert _criteria(env).garage is True
    [follow_up] = _reload(env, alert).follow_ups
    assert follow_up.notes == "Perfil de búsqueda: Piso · Centro, Jaen · ≤ 3 dorm · con garaje · ≤ 150.000 €."

    # Editar a Indiferente lo deja vacío
    _save_profile(env, env.users["ana"], alert, form=dict(CONTACT_PROFILE, garage=""))
    assert _criteria(env).garage is None


def test_contactado_guarda_el_garaje(env):
    alert = _property_alert(env, "ana", "ana")
    response = _add_follow_up(env, env.users["ana"], alert, "CONTACTADO", form=dict(CONTACT_PROFILE, garage="yes"))
    assert _flash(response)["category"] == "success"
    assert _criteria(env).garage is True


def test_ficha_del_comprador_guarda_el_garaje(env):
    form = dict(CONTACT_PROFILE, business_type="Venta", garage="yes")
    response = _save_buyer_profile(env, env.admin, form)
    assert _flash(response) == {"category": "success", "message": "Perfil de búsqueda guardado"}
    assert _criteria(env).garage is True


# ---------------------------------------------------------------------------
# Render del formulario y migración
# ---------------------------------------------------------------------------

def test_formulario_con_select_de_garaje(env):
    _complete_profile(env, garage=True)
    alert = _property_alert(env, "ana", "ana")
    _add_follow_up(env, env.users["ana"], alert, "SIN_RESPUESTA")
    response, html = _detail(env, env.users["ana"], alert, step="profile")
    assert response.status_code == 200
    select = html.split('<select id="spGarage" name="garage"')[1].split("</select>")[0]
    assert "required" not in select.split(">")[0]                        # opcional
    assert '<option value="" >Indiferente</option>' in select
    assert '<option value="yes" selected>Con garaje</option>' in select
    assert "Sin garaje" not in html
    assert '<label for="spGarage"' in html
    # El modal de seguimiento lleva su propio select
    assert 'id="fuGarage" name="garage"' in html


def test_migracion_garage():
    path = BACKEND / "alembic" / "versions" / "n0u1z2a3b4c5_criteria_garage.py"
    text = path.read_text(encoding="utf-8")
    assert "revision = 'n0u1z2a3b4c5'" in text and "down_revision = 'm9t0y1z2a3b4'" in text
    assert "add_column('buyer_search_criteria', sa.Column('garage', sa.Boolean(), nullable=True))" in text
