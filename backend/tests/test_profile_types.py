"""
Varios tipos de inmueble en el perfil del comprador.

`buyer_search_criteria.property_types` (lista) manda; `property_type` guarda
su texto ("Piso, Casa") y sigue valiendo solo en los perfiles anteriores. En
el formulario son casillas `property_types`; el campo único `property_type`
de antes se sigue aceptando. Mismo entorno que tests/test_profile_elevator.py.

    cd backend && python -m pytest tests/test_profile_types.py -q
"""
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


def _new(**fields):
    from app.models.buyer_search_criteria import BuyerSearchCriteria
    return BuyerSearchCriteria(**fields)


def _titles(env, criteria):
    return sorted(p.title for p in buyer_matching.matching_properties(env.db, criteria))


# ---------------------------------------------------------------------------
# Servicio
# ---------------------------------------------------------------------------

def test_clean_types():
    assert buyer_matching.clean_types([" Piso ", "", None, "Casa", "Piso"]) == ["Piso", "Casa"]
    assert buyer_matching.clean_types(None) == [] and buyer_matching.clean_types([]) == []


def test_profile_types_lista_y_perfil_antiguo():
    assert buyer_matching.profile_types(None) == []
    assert buyer_matching.profile_types(_new()) == []
    assert buyer_matching.profile_types(_new(property_types=["Piso", "Casa"], property_type="Piso, Casa")) == ["Piso", "Casa"]
    # Perfil anterior a la lista: solo el tipo único
    assert buyer_matching.profile_types(_new(property_type="Chalet")) == ["Chalet"]


def test_apply_profile_guarda_lista_y_texto():
    criteria = _new()
    buyer_matching.apply_profile(criteria, property_types=["Piso", "Casa", "Piso", ""])
    assert criteria.property_types == ["Piso", "Casa"] and criteria.property_type == "Piso, Casa"

    # El campo único de antes sigue valiendo si no llega la lista
    buyer_matching.apply_profile(criteria, property_type="Chalet")
    assert criteria.property_types == ["Chalet"] and criteria.property_type == "Chalet"

    # La lista manda sobre el campo único
    buyer_matching.apply_profile(criteria, property_type="Chalet", property_types=["Piso"])
    assert criteria.property_types == ["Piso"]

    # Sin tipos: cualquier tipo
    buyer_matching.apply_profile(criteria)
    assert criteria.property_types is None and criteria.property_type is None


def test_cruce_con_las_propiedades(env):
    # Entorno: tres pisos (Centro, Bea, MOES) y una casa (Casa Cara)
    env.props["cara"].property_type = "Casa"
    env.db.commit()
    assert _titles(env, _new(max_price=1000000)) == ["Casa Cara", "Piso Bea", "Piso Centro", "Piso MOES"]
    assert _titles(env, _new(max_price=1000000, property_types=["Casa"])) == ["Casa Cara"]
    assert _titles(env, _new(max_price=1000000, property_types=["Piso"])) == ["Piso Bea", "Piso Centro", "Piso MOES"]
    assert len(_titles(env, _new(max_price=1000000, property_types=["Piso", "Casa"]))) == 4
    assert _titles(env, _new(max_price=1000000, property_types=["Local"])) == []
    # Perfil antiguo con el tipo único
    assert _titles(env, _new(max_price=1000000, property_type="Casa")) == ["Casa Cara"]


def test_resumen_y_minimo():
    criteria = _new(property_types=["Piso", "Casa"], property_type="Piso, Casa", max_price=150000)
    assert buyer_matching.criteria_summary(criteria) == "Piso, Casa · ≤ 150.000 €"
    labels = buyer_matching.PROFILE_MINIMUM_LABELS
    assert labels[0] not in buyer_matching.missing_profile_fields(criteria)
    assert labels[0] in buyer_matching.missing_profile_fields(_new(max_price=150000))
    assert labels[0] not in buyer_matching.missing_profile_fields(_new(property_type="Piso", max_price=150000))


# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------

def _multi(form, types):
    """Formulario con las casillas de tipo marcadas (sin el campo único)."""
    form = dict(form)
    form.pop("property_type", None)
    form["property_types"] = list(types)
    return form


def test_paso_perfil_guarda_varios_tipos(env):
    env.props["cara"].property_type = "Casa"
    env.props["cara"].price = 140000
    env.props["cara"].num_dormitorios = 3
    env.db.commit()
    alert = _property_alert(env, "ana", "ana")
    response = _save_profile(env, env.users["ana"], alert, form=_multi(CONTACT_PROFILE, ["Piso", "Casa"]))
    assert _flash(response)["category"] == "success"
    criteria = _criteria(env)
    assert criteria.property_types == ["Piso", "Casa"] and criteria.property_type == "Piso, Casa"
    [follow_up] = _reload(env, alert).follow_ups
    assert follow_up.notes.startswith("Perfil de búsqueda: Piso, Casa · ")


def test_paso_perfil_sin_tipo_falta_el_minimo(env):
    alert = _property_alert(env, "ana", "ana")
    response = _save_profile(env, env.users["ana"], alert, form=_multi(CONTACT_PROFILE, []))
    assert _flash(response)["category"] == "error"
    assert _criteria(env) is None or not buyer_matching.profile_types(_criteria(env))


def test_campo_unico_de_antes_sigue_funcionando(env):
    alert = _property_alert(env, "ana", "ana")
    response = _save_profile(env, env.users["ana"], alert, form=dict(CONTACT_PROFILE))
    assert _flash(response)["category"] == "success"
    assert _criteria(env).property_types == [CONTACT_PROFILE["property_type"]]


def test_ficha_del_comprador_guarda_varios_tipos(env):
    form = _multi(dict(CONTACT_PROFILE, business_type="Venta"), ["Casa", "Piso"])
    response = _save_buyer_profile(env, env.admin, form)
    assert _flash(response) == {"category": "success", "message": "Perfil de búsqueda guardado"}
    assert _criteria(env).property_types == ["Casa", "Piso"]


# ---------------------------------------------------------------------------
# Render y migración
# ---------------------------------------------------------------------------

def test_formulario_con_casillas_de_tipo(env):
    _complete_profile(env)
    criteria = _criteria(env)
    criteria.property_types, criteria.property_type = ["Piso", "Antiguo"], "Piso, Antiguo"
    env.db.commit()
    alert = _property_alert(env, "ana", "ana")
    _add_follow_up(env, env.users["ana"], alert, "SIN_RESPUESTA")
    response, html = _detail(env, env.users["ana"], alert, step="profile")
    assert response.status_code == 200
    group = html.split('<fieldset id="spPropertyType"')[1].split("</fieldset>")[0]
    assert 'name="property_type"' not in html                      # ya no hay desplegable
    assert 'name="property_types" value="Piso" checked' in group
    # Un tipo guardado que ya no está en el inventario sigue saliendo, marcado
    assert 'name="property_types" value="Antiguo" checked' in group
    assert "puedes marcar varios" in group and 'id="spTypesError"' in group


def test_migracion_property_types():
    path = BACKEND / "alembic" / "versions" / "o1v2a3b4c5d6_criteria_property_types.py"
    text = path.read_text(encoding="utf-8")
    assert "revision = 'o1v2a3b4c5d6'" in text and "down_revision = 'n0u1z2a3b4c5'" in text
    assert "sa.Column('property_types', sa.JSON(), nullable=True)" in text
