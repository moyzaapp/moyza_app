"""
Grafía oficial de las poblaciones (PLAN_PERFIL_ZONAS.md, fase D): tabla
`geo.CITY_SPELLINGS`, `geo.normalize_city`, el formulario de propiedad al
guardar y el script `scripts/normalize_city_names.py` (dry-run por defecto,
`--apply`). Rutas y script en proceso contra una SQLite en memoria con los
modelos reales; mismo entorno que tests/test_alert_search.py.

    cd backend && python -m pytest tests/test_normalize_city.py -q
"""
import asyncio
import importlib.util

import pytest

from app.core import geo
from tests.test_alert_search import BACKEND, _flash, _request, env  # noqa: F401  (env es un fixture)


def _script():
    spec = importlib.util.spec_from_file_location("normalize_city_names", BACKEND / "scripts" / "normalize_city_names.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# geo.normalize_city
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("Jaen", "Jaén"), ("jaén", "Jaén"), ("  JAEN  ", "Jaén"), ("Jaén", "Jaén"),
    ("la guardia de jaen", "La Guardia de Jaén"), ("La  Guardia   de Jaen", "La Guardia de Jaén"),
    ("Ubeda", "Úbeda"), ("andujar", "Andújar"), ("Mengibar", "Mengíbar"), ("bailen", "Bailén"),
    ("Valdepenas de Jaen", "Valdepeñas de Jaén"), ("Bedmar y Garciez", "Bedmar y Garcíez"),
    ("jodar", "Jódar"), ("albanchez de magina", "Albanchez de Mágina"), ("las infantas", "Las Infantas"),
    # Fuera de la tabla: solo se limpian los espacios
    ("Madrid", "Madrid"), ("  Granada   capital ", "Granada capital"), ("Jaén Norte", "Jaén Norte"),
    ("", ""), (None, ""), ("   ", ""),
])
def test_normalize_city(raw, expected):
    assert geo.normalize_city(raw) == expected


def test_tabla_de_poblaciones():
    official = set(geo.CITY_SPELLINGS.values())
    assert len(geo.CITY_SPELLINGS) == len(official) == 32                 # claves sin choques
    for name in ("Jaén", "Mancha Real", "Torredelcampo", "Torredonjimeno", "Martos", "Los Villares",
                 "Linares", "Úbeda", "Baeza", "Alcalá la Real", "Puente del Obispo", "Torres", "Jimena"):
        assert name in official, name
    for key, name in geo.CITY_SPELLINGS.items():
        assert key == geo.city_key(name) and geo.normalize_city(name) == name


# ---------------------------------------------------------------------------
# Formulario de propiedad: se guarda con la grafía oficial
# ---------------------------------------------------------------------------

def _client(env):
    from app.models.client import Client
    client = Client(name="Propietario", phone="34600000000")
    client.companies.append(env.moyza)
    env.db.add(client)
    env.db.commit()
    return client


def test_alta_y_edicion_de_propiedad_normalizan_la_poblacion(env):
    from app.models.property import Property
    from app.web.routes.properties import create_property, update_property
    client = _client(env)
    form = {"title": "Piso Nuevo", "address": "Calle Nueva 1", "city": " jaen ", "price": "100000",
            "description": "-", "client_id": str(client.id), "agent_id": str(env.agents["ana"].id)}
    request = _request(env, env.admin, "/properties/create", "POST", form=form)
    response = asyncio.run(create_property(
        request, title="Piso Nuevo", address="Calle Nueva 1", city=" jaen ", price=100000.0,
        description="-", client_id=client.id, agent_id=env.agents["ana"].id, db=env.db,
    ))
    assert _flash(response)["category"] == "success"
    created = env.db.query(Property).filter_by(title="Piso Nuevo").one()
    assert created.city == "Jaén"

    form = dict(form, property_id=str(created.id), city="ubeda", status="Activa")
    request = _request(env, env.admin, "/properties/update", "POST", form=form)
    response = asyncio.run(update_property(
        request, property_id=created.id, title="Piso Nuevo", price=100000.0, client_id=client.id,
        agent_id=env.agents["ana"].id, address="Calle Nueva 1", city="ubeda", description="-",
        status="Activa", auto_send_report=False, report_frequency=None, report_day=None, report_hour=None,
        db=env.db,
    ))
    assert _flash(response)["category"] == "success"
    env.db.expire_all()
    assert env.db.get(Property, created.id).city == "Úbeda"


# ---------------------------------------------------------------------------
# scripts/normalize_city_names.py
# ---------------------------------------------------------------------------

def _messy_data(env):
    """Las propiedades del entorno están en "Jaen"; se añaden variantes y perfiles."""
    from app.models.buyer import Buyer
    from app.models.buyer_search_criteria import BuyerSearchCriteria
    env.props["bea"].city = " jaén "
    env.props["cara"].city = "Madrid"
    env.props["moes"].city = None
    other = Buyer(name="Otro", phone="34600333444", company_id=env.moyza.id, created_by=env.admin.id)
    third = Buyer(name="Tercero", phone="34600555666", company_id=env.moyza.id, created_by=env.admin.id)
    env.db.add_all([other, third])
    env.db.flush()
    profiles = {
        "mixed": BuyerSearchCriteria(buyer_id=env.buyer.id, cities=["Jaen", "Jaén", "martos ", "Madrid"]),
        "clean": BuyerSearchCriteria(buyer_id=other.id, cities=["Úbeda"]),
        "empty": BuyerSearchCriteria(buyer_id=third.id, cities=None),
    }
    env.db.add_all(profiles.values())
    env.db.commit()
    return profiles


def test_normalized_cities():
    script = _script()
    assert script.normalized_cities(["Jaen", "Jaén", " ", "martos", None]) == ["Jaén", "Martos"]
    assert script.normalized_cities(None) == []


def test_script_dry_run_no_toca_nada_y_apply_escribe(env):
    from app.models.buyer_search_criteria import BuyerSearchCriteria
    from app.models.property import Property
    script = _script()
    profiles = _messy_data(env)

    changes = script.run(env.db)
    assert sorted(old for _id, old, _new in changes["properties.city"]) == [" jaén ", "Jaen"]
    assert all(new == "Jaén" for _id, _old, new in changes["properties.city"])
    assert [(old, new) for _id, old, new in changes["buyer_search_criteria.cities"]] == [
        (["Jaen", "Jaén", "martos ", "Madrid"], ["Jaén", "Martos", "Madrid"]),
    ]
    env.db.expire_all()
    assert env.db.get(Property, env.props["ana"].id).city == "Jaen"                 # dry-run: sin cambios
    assert env.db.get(BuyerSearchCriteria, profiles["mixed"].id).cities[0] == "Jaen"

    script.run(env.db, apply=True)
    env.db.expire_all()
    cities = {key: env.db.get(Property, prop.id).city for key, prop in env.props.items()}
    assert cities == {"ana": "Jaén", "bea": "Jaén", "cara": "Madrid", "moes": None}
    assert env.db.get(BuyerSearchCriteria, profiles["mixed"].id).cities == ["Jaén", "Martos", "Madrid"]
    assert env.db.get(BuyerSearchCriteria, profiles["clean"].id).cities == ["Úbeda"]
    assert env.db.get(BuyerSearchCriteria, profiles["empty"].id).cities is None

    # Segunda pasada: nada que cambiar
    again = script.run(env.db)
    assert again == {"properties.city": [], "buyer_search_criteria.cities": []}


def test_script_informe(env, capsys):
    script = _script()
    _messy_data(env)
    script.report(script.run(env.db), examples=1, applied=False)
    out = capsys.readouterr().out
    assert "== properties.city ==" in out and "cambiarían: 2" in out and "… y 1 más" in out
    assert "Dry-run: 3 filas cambiarían. Nada modificado (usa --apply para escribir)." in out
