"""Perfil de búsqueda del comprador y propiedades compatibles (PLAN_ALERTA_SIN_REFERENCIA.md).

Lo usan la ficha del comprador (pestaña "Propiedades compatibles") y el
detalle de cualquier alerta (pasos "Perfil" y "Propuesta"; desde
PLAN_PERFIL_OBLIGATORIO.md también las creadas con referencia):

- `profile_is_complete` / `missing_profile_fields`: ÚNICA definición de
  "perfil completo". La usan las rutas (bloqueo de etapas, Contactado,
  Propuesta, asociar propiedad, ficha del comprador), las plantillas y los
  tests. Hay dos reglas según la fecha del perfil (PLAN_PERFIL_ZONAS.md §4-4,
  "solo perfiles nuevos"; corte `settings.PROFILE_MINIMUMS_SINCE`, 00:00 de
  Madrid, por defecto 2026-10-29):
  · Regla nueva: tipo de inmueble + precio máximo + dormitorios máximos +
    al menos una población concreta + zona (alguna zona o "Todas" marcada a propósito) si alguna
    población marcada tiene zonas registradas. Se aplica a los perfiles
    creados en el corte o después, a `criteria` None (perfil por crear) y a
    los perfiles temporales sin `created_at` con los que las rutas validan lo
    que llega del formulario: así el formulario exige SIEMPRE los mínimos
    nuevos al guardar, también al editar un perfil antiguo.
  · Regla antigua (PLAN_PERFIL_UBICACION.md, decisión 4): tipo + precio
    máximo + ubicación (provincia, o al menos una población o una zona). Solo
    para perfiles guardados con `created_at` anterior al corte: no pasan a
    incompletos ni bloquean etapas hasta que el agente los edita.
  La zona solo se puede comprobar con el árbol de ubicaciones y sabiendo si
  se marcó "Todas" (lista guardada vacía = "Todas"), así que solo se valida al
  guardar el formulario (`geo_tree` + `zones_all`); un perfil ya guardado con
  poblaciones y sin zonas se lee como "Todas".
- `profile_required` / `profile_required_for_business_type`: ÚNICA
  definición de "hace falta el perfil" (PLAN_PERFIL_SOLO_VENTA.md): solo en
  Venta y con comprador; en Alquiler el perfil es opcional (si existe, sugiere
  propiedades, pero no bloquea nada).
- `geo_options` / `geo_choices`: datos de la cascada País → Provincia →
  Población → Zona (PLAN_PERFIL_UBICACION.md) a partir de las propiedades de
  las dos empresas (PLAN_SUGERENCIAS_MULTIEMPRESA.md), en una sola consulta;
  la provincia se deduce del CP.

- `matching_properties`: propiedades activas y disponibles, de cualquier
  agente y de las DOS empresas (PLAN_SUGERENCIAS_MULTIEMPRESA.md: excepción
  consciente al aislamiento, solo para las sugerencias del perfil; con
  `company_id`, solo las de esa empresa: filtro "Solo {empresa}"), que cumplen
  el perfil. Ordenadas por precio ascendente, sin agrupar por empresa; la
  empresa de cada una se carga en la misma tanda (badge sin N+1).
  `matching_summary_by_company`: desglose por empresa para la cabecera.
  La superficie (m²) ya no filtra: salió del perfil en toda la app (decisión
  cerrada 5); las columnas `min_m2` / `max_m2` se conservan sin usarse.
- `apply_profile`: vuelca los campos del formulario del perfil en el
  `BuyerSearchCriteria` (mismo parseo para la ficha y para la alerta). No
  toca `min_m2` / `max_m2`.
- `criteria_summary`: resumen corto para listados, notas y cabeceras
  ("Piso · Jaén · 2-3 dorm · ≤ 150.000 €").
"""
from datetime import datetime
from typing import Iterable, Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core import business_calendar as bc
from app.core import geo
from app.core.config import settings
from app.core.constants import BusinessType, PropertyStatus
from app.models.buyer_search_criteria import BuyerSearchCriteria
from app.models.company import Company
from app.models.property import Property
from app.services.company_scope import scope_properties
from app.web.template_env import eur


# Ubicaciones que se nombran en el resumen antes de abreviar con "+N"
SUMMARY_MAX_PLACES = 2


# ---------------------------------------------------------------------------
# Perfil completo (PLAN_PERFIL_OBLIGATORIO.md, decisión 4)
# ---------------------------------------------------------------------------

# Nombres de los mínimos tal como se leen en los mensajes ("Falta: …").
# Regla nueva (PLAN_PERFIL_ZONAS.md): la zona solo se pide si alguna población
# marcada tiene zonas (ZONE_LABEL, va la última).
PROFILE_MINIMUM_LABELS = ("tipo de inmueble", "precio máximo", "dormitorios máximos", "población")
ZONE_LABEL = "zona"
# Regla antigua (perfiles anteriores a `settings.PROFILE_MINIMUMS_SINCE`)
LEGACY_PROFILE_MINIMUM_LABELS = ("tipo de inmueble", "precio máximo", "ubicación")


def minimums_since() -> Optional[datetime]:
    """Corte de los mínimos nuevos en UTC naive (00:00 de Madrid del día del ajuste), o None.

    Se lee del ajuste en cada llamada (los tests lo cambian con monkeypatch).
    """
    since = settings.PROFILE_MINIMUMS_SINCE
    if since is None:
        return None
    return bc.to_utc(datetime(since.year, since.month, since.day))


def uses_new_minimums(criteria: Optional[BuyerSearchCriteria]) -> bool:
    """¿Se le exigen a este perfil los mínimos nuevos? (PLAN_PERFIL_ZONAS.md §4-4)

    Sí si no hay perfil (se va a crear), si es un perfil temporal sin
    `created_at` (validación del formulario), si no hay corte o si se creó en
    el corte o después. No, solo para perfiles guardados antes del corte.
    """
    if criteria is None or criteria.created_at is None:
        return True
    since = minimums_since()
    return since is None or criteria.created_at >= since


def has_location(criteria: Optional[BuyerSearchCriteria]) -> bool:
    """Mínimo de ubicación de la regla antigua (PLAN_PERFIL_UBICACION.md, decisión 4).

    Provincia elegida (aunque sea con "Todas" las poblaciones), o al menos una
    población, o al menos una zona. El país solo no basta.
    """
    if criteria is None:
        return False
    if (criteria.province or "").strip():
        return True
    return any(p for p in list(criteria.zones or []) + list(criteria.cities or []))


def zone_required(criteria: Optional[BuyerSearchCriteria], geo_tree: dict) -> bool:
    """¿Alguna población marcada del perfil tiene zonas registradas en el árbol?

    Las zonas de cada población salen del país y la provincia del perfil
    (`city_zones`, mismo criterio que el JS del formulario).
    """
    if criteria is None:
        return False
    zones_by_city = city_zones(geo_tree, criteria.country or "", criteria.province or "")
    return any(zones_by_city.get(city) for city in (criteria.cities or []) if city)


def missing_profile_fields(criteria: Optional[BuyerSearchCriteria], geo_tree: Optional[dict] = None,
                           zones_all: bool = False) -> list:
    """Mínimos del perfil que faltan, en el orden de los mensajes (vacío = completo).

    Regla según `uses_new_minimums` (ver el docstring del módulo):
    - Nueva: tipo de inmueble + precio máximo (mayor que 0) + dormitorios
      máximos (0 vale: estudio) + al menos una población concreta + zona si
      procede. La zona solo se comprueba con
      `geo_tree` (árbol de `geo_options`; al validar el formulario): falta si
      alguna población marcada tiene zonas y no hay ninguna zona concreta ni
      `zones_all` ("Todas" marcada a propósito). Sin `geo_tree` (perfil ya
      guardado), una lista de zonas vacía se lee como "Todas".
    - Antigua (perfiles guardados antes del corte): tipo + precio máximo +
      ubicación (`has_location`).
    Dormitorios mín., baños, precio mínimo e imprescindibles son opcionales
    (dormitorios máx. solo cuenta en la regla nueva, PLAN_PERFIL_ZONAS.md fase B).
    Sin perfil, faltan todos los de la regla nueva (la zona no: depende de la
    población).
    """
    if criteria is None:
        return list(PROFILE_MINIMUM_LABELS)
    new_rule = uses_new_minimums(criteria)
    missing = []
    if not (criteria.property_type or "").strip():
        missing.append(PROFILE_MINIMUM_LABELS[0])
    if criteria.max_price is None or criteria.max_price <= 0:
        missing.append(PROFILE_MINIMUM_LABELS[1])
    if not new_rule:
        if not has_location(criteria):
            missing.append(LEGACY_PROFILE_MINIMUM_LABELS[2])
        return missing
    bedrooms_label, city_label = PROFILE_MINIMUM_LABELS[2:]
    if criteria.max_bedrooms is None:
        missing.append(bedrooms_label)
    if not any(city for city in (criteria.cities or [])):
        missing.append(city_label)
    elif (geo_tree is not None and not zones_all and not any(z for z in (criteria.zones or []))
          and zone_required(criteria, geo_tree)):
        missing.append(ZONE_LABEL)
    return missing


def profile_is_complete(criteria: Optional[BuyerSearchCriteria]) -> bool:
    """True si el comprador tiene el perfil mínimo (ver `missing_profile_fields`)."""
    return criteria is not None and not missing_profile_fields(criteria)


def missing_profile_text(missing: Iterable[str]) -> str:
    """'tipo de inmueble, precio máximo' para los mensajes ("Falta: …")."""
    return ", ".join(missing)


# ---------------------------------------------------------------------------
# ¿Hace falta el perfil? (PLAN_PERFIL_SOLO_VENTA.md)
# ---------------------------------------------------------------------------

def profile_required_for_business_type(business_type) -> bool:
    """El perfil es obligatorio solo para la operación Venta (Alquiler o vacío: opcional).

    ÚNICO sitio que compara la operación con Venta; lo usan `profile_required`
    (alertas) y la ficha del comprador (allí no hay alerta, solo la operación
    elegida en el formulario).
    """
    return business_type == BusinessType.VENTA


def profile_required(alert, business_type: Optional[str] = None) -> bool:
    """El perfil es obligatorio solo para alertas de Venta con comprador.

    Alquiler (y cualquier otro valor) → opcional. Sin comprador no hay dónde
    guardarlo. `profile_is_complete` dice si el perfil está completo; esta
    función dice si hace falta. ÚNICA fuente de verdad para rutas, plantillas
    (vía contexto), JS (vía `profile_required_operations`) y tests.

    `business_type`: operación que se está pidiendo en la misma petición (el
    perfil de la alerta puede cambiarla, PLAN_PERFIL_UBICACION.md); sin ella,
    la de la alerta. Así la obligatoriedad cambia con la operación.
    """
    return alert.buyer_id is not None and profile_required_for_business_type(business_type or alert.business_type)


def profile_required_operations() -> list:
    """Operaciones con perfil obligatorio, en el orden de los selects (para el JS del formulario)."""
    return [bt for bt in BusinessType.values() if profile_required_for_business_type(bt)]


# ---------------------------------------------------------------------------
# ¿Se muestra el perfil? (alquiler sin perfil de comprador)
# ---------------------------------------------------------------------------

def profile_applies(business_type) -> bool:
    """¿Tiene sentido el perfil de comprador para esta operación? False solo en Alquiler.

    En Alquiler el perfil no se muestra ni se pide ni se guarda (detalle de la
    alerta, modal «Contactado», ficha del comprador solo de alquiler). Es solo
    visibilidad: los perfiles ya guardados y sus columnas se conservan. Venta
    o sin operación: como siempre (y `profile_required` decide si es obligatorio).
    ÚNICO sitio que compara la operación con Alquiler para esto.
    """
    return business_type != BusinessType.ALQUILER


def no_profile_operations() -> list:
    """Operaciones sin perfil de comprador (hoy, Alquiler), en el orden de los selects (para el JS)."""
    return [bt for bt in BusinessType.values() if not profile_applies(bt)]


def buyer_profile_applies(alert_operations: Iterable, criteria_operation=None) -> bool:
    """¿Se muestra el perfil en la ficha del comprador?

    Sí si tiene alguna alerta de Venta. No si todas sus alertas son de
    Alquiler. En otro caso (sin alertas, o alertas sin operación), según la
    operación de su perfil guardado: no si es Alquiler; sin perfil, sí (como hoy).
    """
    operations = list(alert_operations)
    if any(op == BusinessType.VENTA for op in operations):
        return True
    if operations and not any(profile_applies(op) for op in operations):
        return False
    return profile_applies(criteria_operation)


# ---------------------------------------------------------------------------
# Propiedades compatibles
# ---------------------------------------------------------------------------

def country_clause(country: str):
    """Condición SQL: la propiedad es de `country` (país vacío o variante de España = España)."""
    normalized = func.lower(func.trim(func.coalesce(Property.pais, "")))
    if geo.is_spain(country):
        return or_(Property.pais.is_(None), normalized.in_(("",) + geo.SPAIN_ALIASES))
    return normalized == country.strip().lower()


def province_clause(province: str):
    """Condición SQL: el CP (cinco caracteres) empieza por el prefijo de la provincia.

    Mismo criterio que `geo.provincia_from_cp` (CP de cinco dígitos). Una
    provincia que no está en la tabla no filtra nada (no debería llegar:
    `apply_profile` solo guarda provincias conocidas).
    """
    prefix = geo.cp_prefix_for_provincia(province)
    if prefix is None:
        return Property.id.isnot(None)
    return func.trim(Property.cod_postal).like(prefix + "___")


def _matching_filters(query, criteria: BuyerSearchCriteria, company_id: Optional[int] = None):
    """Filtros del perfil sobre una consulta de `Property` (sin opciones de carga ni orden).

    Propiedades activas y disponibles, de cualquier agente (decisión cerrada
    3), con captador (las que no lo tienen quedan fuera, como siempre en la
    ficha del comprador). De las dos empresas salvo que se pida `company_id`
    (PLAN_SUGERENCIAS_MULTIEMPRESA.md).
    """
    query = query.filter(
        Property.status == PropertyStatus.ACTIVE,
        Property.available_clause(),
        Property.agent_id.isnot(None),
    )
    if company_id is not None:
        query = scope_properties(query, company_id)

    # Ubicación en cascada (PLAN_PERFIL_UBICACION.md): país (vacío = España),
    # provincia por prefijo del CP (implica España) y, solo si no están
    # vacías, poblaciones y zonas (lista vacía = "Todas")
    if criteria.province and geo.cp_prefix_for_provincia(criteria.province):
        query = query.filter(country_clause(geo.SPAIN), province_clause(criteria.province))
    elif criteria.country:
        query = query.filter(country_clause(criteria.country))
    if criteria.zones:
        query = query.filter(Property.zona.in_(criteria.zones))
    if criteria.cities:
        query = query.filter(Property.city.in_(criteria.cities))
    if criteria.property_type:
        query = query.filter(Property.property_type == criteria.property_type)
    if criteria.business_type:
        query = query.filter(Property.business_type == criteria.business_type)
    if criteria.min_price is not None:
        query = query.filter(Property.price >= criteria.min_price)
    if criteria.max_price is not None:
        query = query.filter(Property.price <= criteria.max_price)
    if criteria.min_bedrooms is not None:
        query = query.filter(Property.num_dormitorios >= criteria.min_bedrooms)
    if criteria.max_bedrooms is not None:
        query = query.filter(Property.num_dormitorios <= criteria.max_bedrooms)
    if criteria.min_bathrooms is not None:
        query = query.filter(Property.num_banos_aseos >= criteria.min_bathrooms)
    return query


def matching_properties_query(db: Session, criteria: BuyerSearchCriteria, company_id: Optional[int] = None):
    """Consulta de propiedades activas y disponibles que cumplen el perfil.

    PLAN_SUGERENCIAS_MULTIEMPRESA.md: de las DOS empresas (las sugerencias son
    la única excepción al aislamiento); con `company_id`, solo las de esa
    empresa (filtro "Solo {empresa activa}"). De cualquier agente (decisión
    cerrada 3). El agente (JOIN) y la empresa (una consulta más para todas,
    `selectinload`) se cargan en la misma tanda: las tarjetas pintan ambos.
    Orden por precio ascendente, sin agrupar por empresa.
    """
    query = _matching_filters(
        db.query(Property).options(joinedload(Property.agent), selectinload(Property.company)),
        criteria,
        company_id,
    )
    return query.order_by(Property.price.asc(), Property.id.asc())


def matching_properties(db: Session, criteria: BuyerSearchCriteria, company_id: Optional[int] = None,
                        limit: Optional[int] = None) -> list:
    """Lista de propiedades compatibles (todas, o las primeras `limit`); ver `matching_properties_query`."""
    query = matching_properties_query(db, criteria, company_id)
    if limit:
        query = query.limit(limit)
    return query.all()


def matching_summary_by_company(db: Session, criteria: BuyerSearchCriteria,
                                first_company_id: Optional[int] = None) -> list:
    """Desglose de las sugerencias por empresa: `[{"company": Company, "count": n}, …]`.

    Una consulta agrupada (más la de las empresas). Solo empresas con alguna
    sugerencia; primero `first_company_id` (la activa) y después por nombre.
    La suma de `count` es el total de sugerencias de las dos empresas
    ("12 sugerencias · 8 MOYZA · 4 MOES PREMIUM").
    """
    counts = dict(
        _matching_filters(db.query(Property.company_id, func.count(Property.id)), criteria)
        .group_by(Property.company_id)
        .all()
    )
    if not counts:
        return []
    companies = db.query(Company).filter(Company.id.in_(counts)).all()
    companies.sort(key=lambda c: (c.id != first_company_id, geo.sort_key(c.name or ""), c.id))
    return [{"company": c, "count": counts[c.id]} for c in companies]


# ---------------------------------------------------------------------------
# Cascada de ubicación (PLAN_PERFIL_UBICACION.md)
# ---------------------------------------------------------------------------

def _sorted(values) -> list:
    """Orden alfabético sin acentos; a igualdad ('Jaen' / 'Jaén'), el texto exacto (estable)."""
    return sorted(values, key=lambda value: (geo.sort_key(value), value))


def geo_options(db: Session, company_id: Optional[int] = None) -> dict:
    """Árbol `{país: {provincia: {población: [zonas]}}}` de las propiedades.

    Propiedades no archivadas de las DOS empresas (PLAN_SUGERENCIAS_MULTIEMPRESA.md:
    se puede elegir una población donde solo tenga inmuebles la otra, porque
    las sugerencias salen de ambas); con `company_id`, solo las de esa
    empresa. De cualquier agente, en UNA consulta
    `DISTINCT (pais, cod_postal, city, zona)`. País vacío (o
    variante de España) = "España"; provincia deducida del CP
    (`geo.provincia_for`); las poblaciones de propiedades sin CP válido van
    bajo "Sin provincia" (última, y no es una provincia elegible). Sin
    población no hay dónde colgar la zona: esas filas no entran. España va
    primero; el resto, en orden alfabético sin acentos.
    """
    query = (
        db.query(Property.pais, Property.cod_postal, Property.city, Property.zona)
        .filter(Property.status != PropertyStatus.ARCHIVED)
    )
    if company_id is not None:
        query = scope_properties(query, company_id)
    rows = query.distinct().all()

    tree: dict = {}
    for pais, cod_postal, city, zona in rows:
        if not (city or "").strip():
            continue
        country = geo.normalize_country(pais)
        province = geo.provincia_for(country, cod_postal) or geo.NO_PROVINCE
        zones = tree.setdefault(country, {}).setdefault(province, {}).setdefault(city, set())
        if (zona or "").strip():
            zones.add(zona)

    countries = _sorted(c for c in tree if c != geo.SPAIN)
    if geo.SPAIN in tree:
        countries.insert(0, geo.SPAIN)
    result = {}
    for country in countries:
        provinces = _sorted(p for p in tree[country] if p != geo.NO_PROVINCE)
        if geo.NO_PROVINCE in tree[country]:
            provinces.append(geo.NO_PROVINCE)
        result[country] = {
            province: {city: _sorted(tree[country][province][city])
                       for city in _sorted(tree[country][province])}
            for province in provinces
        }
    return result


def _add_missing(options: list, saved) -> list:
    """Opciones más los valores guardados que ya no salen (para no perderlos al guardar)."""
    return options + [v for v in (saved or []) if v and v not in options]


def city_zones(tree: dict, country: str = "", province: str = "") -> dict:
    """`{población: [zonas]}` del país (vacío = todos) y la provincia (vacía = todas).

    Mismo criterio que `cityZones()` de static/js/search-profile.js; lo usan
    el estado inicial del formulario (`geo_choices`) y la validación de la
    zona (`zone_required`). Una población con el mismo nombre en dos
    provincias junta sus zonas.
    """
    scope = [tree.get(country, {})] if country else list(tree.values())
    result: dict = {}
    for branch in scope:
        for name, cities in branch.items():
            if province and name != province:
                continue
            for city, zones in cities.items():
                result.setdefault(city, [])
                result[city] += [z for z in zones if z not in result[city]]
    return result


# Título del grupo de zonas guardadas que ya no salen en las propiedades
SAVED_ZONES_GROUP = "Otras zonas guardadas"


def geo_choices(tree: dict, criteria: Optional[BuyerSearchCriteria] = None) -> dict:
    """Estado inicial de la cascada para pintar el formulario (el JS hace lo mismo al cambiar).

    - País: el guardado; si no hay, España si existe o el único que haya.
    - Provincias: las del país (sin "Sin provincia"). Provincia vacía = todas
      las poblaciones del país.
    - Poblaciones (PLAN_PERFIL_ZONAS.md): las de la provincia (o del país),
      sin casilla "Todas"; marcadas las del perfil (un perfil antiguo con la
      lista vacía sale sin ninguna marcada).
    - Zonas: solo con alguna población marcada (`show_zones`). `zone_groups`:
      las zonas de cada población marcada que tenga, en el orden de las
      poblaciones (`[{"city": …, "zones": […]}]`; el formulario pone título a
      cada grupo cuando hay más de uno). `zones`: todas juntas, sin repetir.
      `zones_all` ("Todas" marcada) solo al editar un perfil guardado con
      poblaciones y la lista de zonas vacía (así se guarda "Todas"); un
      perfil nuevo sale sin marcar: el agente elige zonas o "Todas" a propósito.
    Los valores guardados que ya no existen en las propiedades se añaden al
    final (las zonas, en el grupo `SAVED_ZONES_GROUP`) para que guardar de
    nuevo no los pierda.
    """
    saved_country = geo.normalize_country(criteria.country) if criteria is not None and criteria.country else None
    province = (criteria.province or "") if criteria is not None else ""
    saved_cities = list(criteria.cities or []) if criteria is not None else []
    saved_zones = list(criteria.zones or []) if criteria is not None else []

    countries = list(tree)
    if saved_country:
        country = saved_country
    elif geo.SPAIN in tree:
        country = geo.SPAIN
    else:
        country = countries[0] if len(countries) == 1 else ""
    if country and country not in countries:
        countries.append(country)

    scope = [tree.get(country, {})] if country else list(tree.values())
    provinces = []
    for branch in scope:
        provinces += [p for p in branch if p != geo.NO_PROVINCE and p not in provinces]
    provinces = _add_missing(provinces, [province])

    zones_by_city = city_zones(tree, country, province)

    cities = _add_missing(_sorted(zones_by_city), saved_cities)
    zone_groups = [
        {"city": city, "zones": _sorted(zones_by_city[city])}
        for city in cities if city in saved_cities and zones_by_city.get(city)
    ]
    zones = []
    for group in zone_groups:
        zones += [z for z in group["zones"] if z not in zones]
    lost = [z for z in _add_missing(zones, saved_zones) if z not in zones]
    if lost:
        zone_groups.append({"city": SAVED_ZONES_GROUP, "zones": lost})
        zones += lost

    return {
        "no_province": geo.NO_PROVINCE,
        "countries": countries,
        "country": country,
        "provinces": provinces,
        "province": province,
        "cities": cities,
        "selected_cities": saved_cities,
        "show_zones": bool(saved_cities),
        "zone_groups": zone_groups,
        "zones": zones,
        "selected_zones": saved_zones,
        "zones_all": criteria is not None and bool(saved_cities) and not saved_zones and bool(zones),
    }


# ---------------------------------------------------------------------------
# Formulario del perfil
# ---------------------------------------------------------------------------

def to_int(value) -> Optional[int]:
    try:
        return int(value) if value is not None and str(value).strip() else None
    except (ValueError, TypeError):
        return None


def to_decimal(value) -> Optional[float]:
    try:
        return float(value) if value is not None and str(value).strip() else None
    except (ValueError, TypeError):
        return None


def apply_profile(
    criteria: BuyerSearchCriteria,
    *,
    country=None,
    province=None,
    zones: Iterable[str] = (),
    cities: Iterable[str] = (),
    property_type=None,
    business_type=None,
    min_price=None,
    max_price=None,
    min_bedrooms=None,
    max_bedrooms=None,
    min_bathrooms=None,
    notes=None,
    agent_id=None,
    now: Optional[datetime] = None,
) -> BuyerSearchCriteria:
    """Vuelca el formulario del perfil en `criteria` (sin m²: se conservan tal cual).

    Ubicación (PLAN_PERFIL_UBICACION.md): el país se normaliza (variantes de
    España → "España"); la provincia solo se guarda si es una de la tabla de
    `app/core/geo.py` y el país es España (si no hay país, queda España).
    Zonas vacías = "Todas" (PLAN_PERFIL_ZONAS.md: con la regla nueva hay que
    marcar al menos una población; la lista vacía de poblaciones solo queda
    en perfiles antiguos, donde sigue significando "Todas").
    """
    criteria.agent_id = agent_id or None
    country = (country or "").strip()
    criteria.country = geo.normalize_country(country) if country else None
    province = (province or "").strip()
    if not geo.cp_prefix_for_provincia(province) or (criteria.country and criteria.country != geo.SPAIN):
        province = ""
    criteria.province = province or None
    if criteria.province and not criteria.country:
        criteria.country = geo.SPAIN
    # Sin repetir: una zona con el mismo nombre en dos poblaciones sale en los
    # dos grupos del formulario (PLAN_PERFIL_ZONAS.md) y llega dos veces
    criteria.zones = list(dict.fromkeys(z for z in zones if z)) or None
    criteria.cities = list(dict.fromkeys(c for c in cities if c)) or None
    criteria.property_type = (property_type or "").strip() or None
    criteria.business_type = (business_type or "").strip() or None
    criteria.min_price = to_decimal(min_price)
    criteria.max_price = to_decimal(max_price)
    criteria.min_bedrooms = to_int(min_bedrooms)
    criteria.max_bedrooms = to_int(max_bedrooms)
    criteria.min_bathrooms = to_int(min_bathrooms)
    criteria.notes = (notes or "").strip() or None
    criteria.updated_at = now or datetime.utcnow()
    return criteria


# ---------------------------------------------------------------------------
# Resumen
# ---------------------------------------------------------------------------

def format_eur(value) -> str:
    """120000 -> '120.000 €' (formato de España, sin decimales; mismo filtro `eur` de las plantillas)."""
    return eur(value)


def _range(low, high, unit: str) -> Optional[str]:
    if low is not None and high is not None:
        return f"{low}-{high} {unit}" if low != high else f"{low} {unit}"
    if low is not None:
        return f"≥ {low} {unit}"
    if high is not None:
        return f"≤ {high} {unit}"
    return None


def _price_range(low, high) -> Optional[str]:
    if low is not None and high is not None:
        return f"{format_eur(low)} - {format_eur(high)}"
    if low is not None:
        return f"≥ {format_eur(low)}"
    if high is not None:
        return f"≤ {format_eur(high)}"
    return None


def _places_text(places: list) -> str:
    """'Centro, Jaén' o 'Centro, Jaén +1' (máximo SUMMARY_MAX_PLACES nombres)."""
    extra = len(places) - SUMMARY_MAX_PLACES
    shown = ", ".join(places[:SUMMARY_MAX_PLACES])
    return f"{shown} +{extra}" if extra > 0 else shown


def _location_parts(criteria: BuyerSearchCriteria) -> list:
    """Ubicación del resumen (PLAN_PERFIL_UBICACION.md).

    Con provincia: 'Jaén · Todas las poblaciones' o 'Jaén · Jaén, Martos ·
    Zona Centro'. Sin provincia, como antes: zonas y poblaciones juntas
    ('Centro, Jaén +1'). El país solo se nombra si no es España.
    """
    parts = []
    if criteria.country and criteria.country != geo.SPAIN:
        parts.append(criteria.country)
    zones = [z for z in (criteria.zones or []) if z]
    cities = [c for c in (criteria.cities or []) if c]
    if criteria.province:
        parts.append(criteria.province)
        parts.append(_places_text(cities) if cities else "Todas las poblaciones")
        if zones:
            parts.append("Zona " + _places_text(zones))
    elif zones or cities:
        parts.append(_places_text(zones + cities))
    return parts


def criteria_parts(criteria: Optional[BuyerSearchCriteria]) -> list:
    """Trozos del resumen, en el orden en que se leen. Vacío si no hay perfil."""
    if criteria is None:
        return []
    parts = []
    if criteria.property_type:
        parts.append(criteria.property_type)
    parts += _location_parts(criteria)
    bedrooms = _range(criteria.min_bedrooms, criteria.max_bedrooms, "dorm")
    if bedrooms:
        parts.append(bedrooms)
    if criteria.min_bathrooms is not None:
        parts.append(f"≥ {criteria.min_bathrooms} {'baño' if criteria.min_bathrooms == 1 else 'baños'}")
    price = _price_range(criteria.min_price, criteria.max_price)
    if price:
        parts.append(price)
    return parts


def criteria_summary(criteria: Optional[BuyerSearchCriteria]) -> str:
    """'Piso · Jaén · 2-3 dorm · ≤ 150.000 €' (cadena vacía si no hay datos)."""
    return " · ".join(criteria_parts(criteria))


def profile_note(criteria: BuyerSearchCriteria) -> str:
    """Resumen del perfil para la nota del seguimiento que lo registra.

    CONTACTADO la primera vez que el perfil queda completo (paso Perfil o
    seguimiento Contactado) y PERFIL_GUARDADO en las ediciones posteriores
    (PLAN_PERFIL_OBLIGATORIO.md, decisión 5).
    """
    summary = criteria_summary(criteria) or "sin filtros"
    note = f"Perfil de búsqueda: {summary}."
    if criteria.notes:
        note += f" Imprescindibles: {criteria.notes}"
    return note
