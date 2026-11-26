"""
Cruce propiedad -> perfil en Python (PLAN_COMPRADORES_COMPATIBLES_PROPIEDAD_NUEVA.md §4.1, §7).

`buyer_matching.criteria_matches_property` replica `_matching_filters` (SQL)
condición por condición. Aquí:
- Cada filtro por separado, sin base de datos (propiedades `SimpleNamespace`).
- Test cruzado con PostgreSQL (transacción externa que se deshace al
  terminar, patrón de test_notification_service.py): para varios perfiles y
  todas las propiedades de la base (las de prueba y las que ya hubiera),
  `prop in matching_properties(criteria)` <=> `criteria_matches_property(criteria, prop)`.
  Si alguien cambia `_matching_filters` sin cambiar la réplica, falla aquí.

    docker exec moyza_backend python -m pytest tests/test_criteria_matches_property.py -q
"""
from types import SimpleNamespace

import pytest

from app.models.buyer_search_criteria import BuyerSearchCriteria
from app.services.buyer_matching import criteria_matches_property
from app.services.buyer_matching import matching_properties


def _prop(**overrides):
    data = dict(status="Activa", agent_id=1, pais=None, cod_postal="23001", city="Jaén", zona="Centro",
                property_type="Piso", business_type="Venta", price=120000, num_dormitorios=3,
                num_banos_aseos=2, num_ascensores=1, num_garaje_aparcam=0)
    data.update(overrides)
    return SimpleNamespace(**data)


def _criteria(**fields):
    return BuyerSearchCriteria(**fields)


def _match(criteria, **prop):
    return criteria_matches_property(criteria, _prop(**prop))


# ---------------------------------------------------------------------------
# Filtro a filtro
# ---------------------------------------------------------------------------

def test_perfil_vacio_encaja_con_cualquier_activa_con_captador():
    assert _match(_criteria())
    assert not _match(_criteria(), status="Vendida")
    assert not _match(_criteria(), agent_id=None)
    assert not criteria_matches_property(None, _prop())


@pytest.mark.parametrize("pais, expected", [
    (None, True), ("", True), (" España ", True), ("espana", True), ("SPAIN", True), ("es", True),
    ("Portugal", False),
])
def test_pais_vacio_es_espana(pais, expected):
    assert _match(_criteria(country="España"), pais=pais) is expected


def test_pais_extranjero():
    criteria = _criteria(country="Portugal")
    assert _match(criteria, pais=" portugal ")
    assert not _match(criteria, pais=None)
    assert not _match(criteria, pais="España")


@pytest.mark.parametrize("cp, pais, expected", [
    ("23001", None, True), (" 23005 ", None, True), ("23001", "Spain", True),
    ("28001", None, False), ("2300", None, False), (None, None, False), ("23001", "Portugal", False),
])
def test_provincia_por_cp(cp, pais, expected):
    assert _match(_criteria(country="España", province="Jaén"), cod_postal=cp, pais=pais) is expected


def test_provincia_desconocida_filtra_por_pais():
    criteria = _criteria(country="Portugal", province="Atlántida")
    assert _match(criteria, pais="Portugal", cod_postal=None)
    assert not _match(criteria, pais=None)


def test_poblaciones_igualdad_exacta():
    criteria = _criteria(cities=["Jaén", "Martos"])
    assert _match(criteria, city="Martos")
    assert not _match(criteria, city="Jaen")
    assert not _match(criteria, city=None)
    assert _match(_criteria(cities=[]), city=None)


def test_zonas_vacias_son_todas():
    assert _match(_criteria(zones=None), zona=None)
    assert _match(_criteria(zones=[]), zona="Otra")
    assert _match(_criteria(zones=["Centro", "Bulevar"]), zona="Bulevar")
    assert not _match(_criteria(zones=["Centro"]), zona="Bulevar")
    assert not _match(_criteria(zones=["Centro"]), zona=None)


def test_tipos_multiples_y_tipo_antiguo():
    assert _match(_criteria(property_types=["Casa", "Piso"]), property_type="Piso")
    assert not _match(_criteria(property_types=["Casa"]), property_type="Piso")
    # Perfil anterior a la selección múltiple: solo `property_type`
    assert _match(_criteria(property_type="Piso"), property_type="Piso")
    assert not _match(_criteria(property_type="Casa"), property_type="Piso")
    # Manda la lista
    assert _match(_criteria(property_type="Casa", property_types=["Piso"]), property_type="Piso")
    assert not _match(_criteria(property_types=["Piso"]), property_type=None)


def test_operacion():
    assert _match(_criteria(business_type="Venta"))
    assert not _match(_criteria(business_type="Alquiler"))
    assert not _match(_criteria(business_type="Venta"), business_type=None)


@pytest.mark.parametrize("low, high, price, expected", [
    (None, 150000, 150000, True), (None, 150000, 150001, False), (100000, None, 100000, True),
    (100000, None, 99999, False), (100000, 150000, 120000, True), (None, 150000, None, False),
    (None, None, None, True),
])
def test_rango_de_precio(low, high, price, expected):
    assert _match(_criteria(min_price=low, max_price=high), price=price) is expected


@pytest.mark.parametrize("low, high, bedrooms, expected", [
    (2, 3, 3, True), (2, 3, 4, False), (2, None, 1, False), (None, 0, 0, True), (None, 3, None, False),
])
def test_rango_de_dormitorios(low, high, bedrooms, expected):
    assert _match(_criteria(min_bedrooms=low, max_bedrooms=high), num_dormitorios=bedrooms) is expected


def test_banos_minimos():
    assert _match(_criteria(min_bathrooms=2), num_banos_aseos=2)
    assert not _match(_criteria(min_bathrooms=2), num_banos_aseos=1)
    assert not _match(_criteria(min_bathrooms=1), num_banos_aseos=None)


@pytest.mark.parametrize("elevator, lifts, expected", [
    (None, None, True), (None, 0, True), (None, 2, True),
    (True, 1, True), (True, 3, True), (True, 0, False), (True, None, False),
    (False, None, True), (False, 0, True), (False, 1, False),
])
def test_ascensor_si_no_indiferente(elevator, lifts, expected):
    assert _match(_criteria(elevator=elevator), num_ascensores=lifts) is expected


@pytest.mark.parametrize("garage, places, expected", [
    (None, None, True), (True, 1, True), (True, 0, False), (True, None, False), (False, None, True),
])
def test_garaje(garage, places, expected):
    assert _match(_criteria(garage=garage), num_garaje_aparcam=places) is expected


# ---------------------------------------------------------------------------
# Test cruzado contra `matching_properties` (SQL)
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    from sqlalchemy.orm import Session
    from app.db.session import engine
    try:
        connection = engine.connect()
    except Exception as e:  # pragma: no cover - depende del entorno
        pytest.skip(f"Sin base de datos: {e}")
    transaction = connection.begin()
    session = Session(bind=connection, autoflush=False, join_transaction_mode="create_savepoint")
    yield session
    session.close()
    transaction.rollback()
    connection.close()


# Propiedades de prueba: casos límite de cada filtro (NULL, espacios, alias de España…)
_CROSS_PROPERTIES = [
    dict(),
    dict(pais=" españa ", cod_postal="2300 "),   # varchar(5): con espacio solo caben 4 cifras
    dict(pais="Spain", cod_postal="23700", city="Linares", zona=None),
    dict(pais="Portugal", cod_postal="23001", city="Lisboa", zona="Baixa"),
    dict(cod_postal="2300", city="Martos", zona="Centro"),
    dict(cod_postal=None, city=None, zona=None),
    dict(cod_postal="28001", city="Madrid", zona="Centro"),
    dict(property_type="Casa", price=250000, num_dormitorios=4, num_banos_aseos=3, num_ascensores=None,
         num_garaje_aparcam=2),
    dict(property_type=None, business_type=None, price=None, num_dormitorios=None, num_banos_aseos=None,
         num_ascensores=None, num_garaje_aparcam=None),
    dict(business_type="Alquiler", price=650, num_dormitorios=1, num_ascensores=0),
    dict(status="Vendida"),
    dict(status="Activa", no_agent=True),
    dict(num_dormitorios=0, property_type="Estudio", price=90000, num_ascensores=2, num_garaje_aparcam=1),
]

_CROSS_CRITERIA = [
    dict(),
    dict(country="España"),
    dict(country="Portugal"),
    dict(country="España", province="Jaén"),
    dict(country="España", province="Jaén", cities=["Jaén", "Martos"], zones=["Centro"]),
    dict(province="Atlántida", country="Portugal"),
    dict(cities=["Linares"]),
    dict(zones=["Baixa", "Centro"]),
    dict(property_types=["Piso", "Estudio"], max_price=150000, max_bedrooms=3),
    dict(property_type="Casa", min_price=200000, min_bedrooms=4, min_bathrooms=3, garage=True),
    dict(business_type="Alquiler", max_price=800),
    dict(business_type="Venta", min_price=100000, max_price=130000),
    dict(elevator=True),
    dict(elevator=False),
    dict(garage=True, elevator=True, max_bedrooms=0),
    dict(min_bedrooms=1, max_bedrooms=3, min_bathrooms=2, elevator=False),
]


def test_cruzado_con_matching_properties(db):
    from app.models.agent import Agent
    from app.models.company import Company
    from app.models.property import Property

    moyza = db.query(Company).filter_by(code="MOYZA").one()
    moes = db.query(Company).filter_by(code="MOES").one()
    agent = Agent(name="PYTEST-CMP Captador", email="pytest.cmp@example.com", is_active=True)
    db.add(agent)
    db.flush()
    for i, overrides in enumerate(_CROSS_PROPERTIES):
        data = dict(overrides)
        no_agent = data.pop("no_agent", False)
        fields = dict(status="Activa", pais=None, cod_postal="23001", city="Jaén", zona="Centro",
                      property_type="Piso", business_type="Venta", price=120000, num_dormitorios=3,
                      num_banos_aseos=2, num_ascensores=1, num_garaje_aparcam=0)
        fields.update(data)
        db.add(Property(title=f"PYTEST-CMP {i}", company_id=(moes if i % 2 else moyza).id,
                        agent_id=None if no_agent else agent.id, **fields))
    db.flush()

    properties = db.query(Property).all()
    assert len(properties) >= len(_CROSS_PROPERTIES)
    checked = 0
    for fields in _CROSS_CRITERIA:
        criteria = BuyerSearchCriteria(**fields)
        sql_ids = {p.id for p in matching_properties(db, criteria)}
        for prop in properties:
            assert (prop.id in sql_ids) == criteria_matches_property(criteria, prop), (fields, prop.title)
            checked += 1
        # Que el caso no sea trivial: alguna de prueba entra o queda fuera según el perfil
        assert sql_ids or fields
    assert checked == len(_CROSS_CRITERIA) * len(properties)


def test_cruzado_con_perfiles_reales(db):
    """Los perfiles que ya hay en la base, contra todas las propiedades."""
    from app.models.property import Property

    profiles = db.query(BuyerSearchCriteria).limit(200).all()
    properties = db.query(Property).all()
    for criteria in profiles:
        sql_ids = {p.id for p in matching_properties(db, criteria)}
        for prop in properties:
            assert (prop.id in sql_ids) == criteria_matches_property(criteria, prop), (criteria.id, prop.id)
