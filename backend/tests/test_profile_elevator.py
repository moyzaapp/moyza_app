"""
Filtro de ascensor en el perfil del comprador (PLAN_PERFIL_ZONAS.md, fase C).

`buyer_search_criteria.elevator`: NULL = indiferente, True = con ascensor
(`num_ascensores >= 1`), False = sin ascensor (`num_ascensores` 0 o vacío).
Rutas y servicios en proceso contra una SQLite en memoria con los modelos
reales; mismo entorno y helpers que tests/test_alert_search.py.

    cd backend && python -m pytest tests/test_profile_elevator.py -q
"""
import subprocess
import sys

import pytest

from app.core.constants import ElevatorPreference
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


def _with_lifts(env):
    """Las propiedades del entorno con distinto número de ascensores (Piso MOES sin dato)."""
    env.props["ana"].num_ascensores = 1       # Piso Centro
    env.props["bea"].num_ascensores = 0       # Piso Bea
    env.props["cara"].num_ascensores = 2      # Casa Cara (otro tipo)
    env.props["moes"].num_ascensores = None   # Piso MOES
    env.db.commit()


def _titles(env, elevator):
    from app.models.buyer_search_criteria import BuyerSearchCriteria
    criteria = BuyerSearchCriteria(max_price=1000000, elevator=elevator)
    return sorted(p.title for p in buyer_matching.matching_properties(env.db, criteria))


# ---------------------------------------------------------------------------
# Servicio
# ---------------------------------------------------------------------------

def test_opciones_del_select():
    assert ElevatorPreference.choices() == (("", "Indiferente"), ("yes", "Con ascensor"), ("no", "Sin ascensor"))


@pytest.mark.parametrize("raw, parsed", [
    ("yes", True), (" YES ", True), ("no", False), ("", None), (None, None), ("quizá", None),
])
def test_parse_elevator(raw, parsed):
    assert buyer_matching.parse_elevator(raw) is parsed


def test_valor_del_select_y_apply_profile():
    from app.models.buyer_search_criteria import BuyerSearchCriteria
    assert buyer_matching.elevator_value(None) == ""
    for raw, stored, shown in (("yes", True, "yes"), ("no", False, "no"), ("", None, "")):
        criteria = buyer_matching.apply_profile(BuyerSearchCriteria(), elevator=raw)
        assert criteria.elevator is stored
        assert buyer_matching.elevator_value(criteria) == shown
    # Sin el campo (opcional): indiferente
    assert buyer_matching.apply_profile(BuyerSearchCriteria()).elevator is None


def test_cruce_con_las_propiedades(env):
    _with_lifts(env)
    assert _titles(env, None) == ["Casa Cara", "Piso Bea", "Piso Centro", "Piso MOES"]
    assert _titles(env, True) == ["Casa Cara", "Piso Centro"]           # num_ascensores >= 1
    assert _titles(env, False) == ["Piso Bea", "Piso MOES"]             # 0 o sin dato


def test_resumen_con_ascensor():
    from app.models.buyer_search_criteria import BuyerSearchCriteria
    c = BuyerSearchCriteria(property_type="Piso", cities=["Jaen"], max_bedrooms=3, min_bathrooms=1,
                            max_price=150000, elevator=True)
    assert buyer_matching.criteria_summary(c) == "Piso · Jaen · ≤ 3 dorm · ≥ 1 baño · con ascensor · ≤ 150.000 €"
    c.elevator = False
    assert "sin ascensor" in buyer_matching.criteria_parts(c)
    c.elevator = None
    assert not any("ascensor" in part for part in buyer_matching.criteria_parts(c))


def test_el_ascensor_no_es_un_minimo():
    from app.models.buyer_search_criteria import BuyerSearchCriteria
    criteria = BuyerSearchCriteria(property_type="Piso", max_price=150000, max_bedrooms=3, cities=["Jaen"])
    assert buyer_matching.profile_is_complete(criteria)


def test_el_ascensor_cuenta_como_dato_del_perfil():
    from app.web.routes.alerts import PROFILE_TEXT_FIELDS, _profile_values_present
    assert "elevator" in PROFILE_TEXT_FIELDS
    empty = {name: None for name in (*PROFILE_TEXT_FIELDS, "province", "notes")}
    empty.update(zones=[], cities=[])
    assert not _profile_values_present(empty)
    assert not _profile_values_present(dict(empty, elevator=""))           # Indiferente
    assert _profile_values_present(dict(empty, elevator="yes"))


# ---------------------------------------------------------------------------
# Rutas: paso Perfil, Contactado y ficha del comprador
# ---------------------------------------------------------------------------

def test_paso_perfil_guarda_el_ascensor(env):
    _with_lifts(env)
    alert = _property_alert(env, "ana", "ana")
    response = _save_profile(env, env.users["ana"], alert, form=dict(CONTACT_PROFILE, elevator="yes"))
    assert response.headers["location"] == f"/alerts/{alert.id}?step=proposal"
    # Solo Piso Centro: Piso Bea sin ascensor, Piso MOES sin dato, Casa Cara es otro tipo
    assert _flash(response)["message"].endswith(": 1 propiedad sugerida")
    assert _criteria(env).elevator is True
    [follow_up] = _reload(env, alert).follow_ups
    assert follow_up.notes == "Perfil de búsqueda: Piso · Centro, Jaen · ≤ 3 dorm · con ascensor · ≤ 150.000 €."

    # Editar a Indiferente lo deja vacío
    _save_profile(env, env.users["ana"], alert, form=dict(CONTACT_PROFILE, elevator=""))
    assert _criteria(env).elevator is None


def test_contactado_guarda_el_ascensor(env):
    alert = _property_alert(env, "ana", "ana")
    response = _add_follow_up(env, env.users["ana"], alert, "CONTACTADO", form=dict(CONTACT_PROFILE, elevator="no"))
    assert _flash(response)["category"] == "success"
    assert _criteria(env).elevator is False


def test_contactado_solo_con_ascensor_exige_los_minimos(env):
    """Con el perfil completo, enviar solo el ascensor es una edición: debe traer los mínimos."""
    _complete_profile(env)
    alert = _property_alert(env, "ana", "ana")
    response = _add_follow_up(env, env.users["ana"], alert, "CONTACTADO", form={"elevator": "yes"})
    assert _flash(response)["category"] == "error"
    assert _criteria(env).elevator is None and _reload(env, alert).follow_ups == []


def test_ficha_del_comprador_guarda_el_ascensor(env):
    form = dict(CONTACT_PROFILE, business_type="Venta", elevator="no")
    response = _save_buyer_profile(env, env.admin, form)
    assert _flash(response) == {"category": "success", "message": "Perfil de búsqueda guardado"}
    assert _criteria(env).elevator is False


# ---------------------------------------------------------------------------
# Render del formulario
# ---------------------------------------------------------------------------

def test_formulario_con_select_de_ascensor(env):
    _complete_profile(env, elevator=True)
    alert = _property_alert(env, "ana", "ana")
    _add_follow_up(env, env.users["ana"], alert, "SIN_RESPUESTA")
    response, html = _detail(env, env.users["ana"], alert, step="profile")
    assert response.status_code == 200
    select = html.split('<select id="spElevator" name="elevator"')[1].split("</select>")[0]
    assert "required" not in select.split(">")[0]                        # opcional
    assert '<option value="" >Indiferente</option>' in select
    assert '<option value="yes" selected>Con ascensor</option>' in select
    assert '<option value="no" >Sin ascensor</option>' in select
    assert '<label for="spElevator"' in html
    # Imprescindibles ya no pone el ascensor de ejemplo
    assert "terraza, ascensor" not in html and "Ej: planta baja, terraza, sin reformar…" in html
    # El modal de seguimiento lleva su propio select
    assert 'id="fuElevator" name="elevator"' in html


# ---------------------------------------------------------------------------
# Migración
# ---------------------------------------------------------------------------

def test_migracion_elevator():
    path = BACKEND / "alembic" / "versions" / "e4f5a6b7c8d9_criteria_elevator.py"
    text = path.read_text(encoding="utf-8")
    assert "revision = 'e4f5a6b7c8d9'" in text and "down_revision = 'd3e4f5a6b7c8'" in text

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "d3e4f5a6b7c8:e4f5a6b7c8d9", "--sql"],
        cwd=BACKEND, capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        pytest.skip(f"alembic --sql no disponible aquí: {result.stderr[-300:]}")
    assert "ALTER TABLE buyer_search_criteria ADD COLUMN elevator BOOLEAN" in result.stdout

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "e4f5a6b7c8d9:d3e4f5a6b7c8", "--sql"],
        cwd=BACKEND, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr[-300:]
    assert "ALTER TABLE buyer_search_criteria DROP COLUMN elevator" in result.stdout
