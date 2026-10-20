"""Perfil de búsqueda del comprador y propiedades compatibles (PLAN_ALERTA_SIN_REFERENCIA.md).

Lo usan la ficha del comprador (pestaña "Propiedades compatibles") y el
detalle de cualquier alerta (pasos "Perfil" y "Propuesta"; desde
PLAN_PERFIL_OBLIGATORIO.md también las creadas con referencia):

- `profile_is_complete` / `missing_profile_fields`: ÚNICA definición de
  "perfil completo" (tipo de inmueble + precio máximo + ubicación: provincia,
  o al menos una población o una zona; PLAN_PERFIL_UBICACION.md, decisión 4).
  La usan las rutas (bloqueo de etapas, Contactado, Propuesta, asociar
  propiedad, ficha del comprador), las plantillas y los tests.
- `geo_options` / `geo_choices`: datos de la cascada País → Provincia →
  Población → Zona (PLAN_PERFIL_UBICACION.md) a partir de las propiedades de
  la empresa, en una sola consulta; la provincia se deduce del CP.

- `matching_properties`: propiedades activas y disponibles de la empresa,
  de cualquier agente, que cumplen el perfil. Ordenadas por precio ascendente.
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
from sqlalchemy.orm import Session, joinedload

from app.core import geo
from app.core.constants import PropertyStatus
from app.models.buyer_search_criteria import BuyerSearchCriteria
from app.models.property import Property
from app.services.company_scope import scope_properties
from app.web.template_env import eur


# Ubicaciones que se nombran en el resumen antes de abreviar con "+N"
SUMMARY_MAX_PLACES = 2


# ---------------------------------------------------------------------------
# Perfil completo (PLAN_PERFIL_OBLIGATORIO.md, decisión 4)
# ---------------------------------------------------------------------------

# Nombres de los mínimos tal como se leen en los mensajes ("Falta: …")
PROFILE_MINIMUM_LABELS = ("tipo de inmueble", "precio máximo", "ubicación")


def has_location(criteria: Optional[BuyerSearchCriteria]) -> bool:
    """Mínimo de ubicación (PLAN_PERFIL_UBICACION.md, decisión 4).

    Provincia elegida (aunque sea con "Todas" las poblaciones), o al menos una
    población, o al menos una zona. El país solo no basta.
    """
    if criteria is None:
        return False
    if (criteria.province or "").strip():
        return True
    return any(p for p in list(criteria.zones or []) + list(criteria.cities or []))


def missing_profile_fields(criteria: Optional[BuyerSearchCriteria]) -> list:
    """Mínimos del perfil que faltan, en el orden del formulario (vacío = completo).

    Perfil mínimo = tipo de inmueble + precio máximo (mayor que 0) + ubicación
    (`has_location`: provincia, o al menos una población o una zona).
    Dormitorios, baños, precio mínimo e imprescindibles son opcionales.
    Sin perfil, faltan todos.
    """
    if criteria is None:
        return list(PROFILE_MINIMUM_LABELS)
    property_type_label, max_price_label, location_label = PROFILE_MINIMUM_LABELS
    missing = []
    if not (criteria.property_type or "").strip():
        missing.append(property_type_label)
    if criteria.max_price is None or criteria.max_price <= 0:
        missing.append(max_price_label)
    if not has_location(criteria):
        missing.append(location_label)
    return missing


def profile_is_complete(criteria: Optional[BuyerSearchCriteria]) -> bool:
    """True si el comprador tiene el perfil mínimo (ver `missing_profile_fields`)."""
    return criteria is not None and not missing_profile_fields(criteria)


def missing_profile_text(missing: Iterable[str]) -> str:
    """'tipo de inmueble, precio máximo' para los mensajes ("Falta: …")."""
    return ", ".join(missing)


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


def matching_properties_query(db: Session, criteria: BuyerSearchCriteria, company_id: int):
    """Consulta de propiedades activas y disponibles de la empresa que cumplen el perfil.

    De cualquier agente (decisión cerrada 3). Las propiedades sin captador
    quedan fuera, como hasta ahora en la ficha del comprador. El agente de
    cada propiedad se carga en la misma consulta (las tarjetas lo muestran).
    """
    query = scope_properties(
        db.query(Property)
        .options(joinedload(Property.agent))
        .filter(
            Property.status == PropertyStatus.ACTIVE,
            Property.available_clause(),
            Property.agent_id.isnot(None),
        ),
        company_id,
    )

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

    return query.order_by(Property.price.asc(), Property.id.asc())


def matching_properties(db: Session, criteria: BuyerSearchCriteria, company_id: int,
                        limit: Optional[int] = None) -> list:
    """Lista de propiedades compatibles (todas, o las primeras `limit`)."""
    query = matching_properties_query(db, criteria, company_id)
    if limit:
        query = query.limit(limit)
    return query.all()


# ---------------------------------------------------------------------------
# Cascada de ubicación (PLAN_PERFIL_UBICACION.md)
# ---------------------------------------------------------------------------

def _sorted(values) -> list:
    """Orden alfabético sin acentos; a igualdad ('Jaen' / 'Jaén'), el texto exacto (estable)."""
    return sorted(values, key=lambda value: (geo.sort_key(value), value))


def geo_options(db: Session, company_id: int) -> dict:
    """Árbol `{país: {provincia: {población: [zonas]}}}` de las propiedades de la empresa.

    Propiedades no archivadas de la empresa activa (de cualquier agente), en
    UNA consulta `DISTINCT (pais, cod_postal, city, zona)`. País vacío (o
    variante de España) = "España"; provincia deducida del CP
    (`geo.provincia_for`); las poblaciones de propiedades sin CP válido van
    bajo "Sin provincia" (última, y no es una provincia elegible). Sin
    población no hay dónde colgar la zona: esas filas no entran. España va
    primero; el resto, en orden alfabético sin acentos.
    """
    rows = (
        scope_properties(
            db.query(Property.pais, Property.cod_postal, Property.city, Property.zona)
            .filter(Property.status != PropertyStatus.ARCHIVED),
            company_id,
        )
        .distinct()
        .all()
    )

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


def geo_choices(tree: dict, criteria: Optional[BuyerSearchCriteria] = None) -> dict:
    """Estado inicial de la cascada para pintar el formulario (el JS hace lo mismo al cambiar).

    - País: el guardado; si no hay, España si existe o el único que haya.
    - Provincias: las del país (sin "Sin provincia"). Provincia vacía = todas
      las poblaciones del país.
    - Poblaciones: las de la provincia (o del país); `cities_all` si el perfil
      no tiene ninguna marcada ("Todas").
    - Zonas: las de las poblaciones marcadas (o de todas las mostradas).
    Los valores guardados que ya no existen en las propiedades se añaden al
    final para que guardar de nuevo no los pierda.
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

    city_zones: dict = {}
    for branch in scope:
        for name, cities in branch.items():
            if province and name != province:
                continue
            for city, zones in cities.items():
                city_zones.setdefault(city, [])
                city_zones[city] += [z for z in zones if z not in city_zones[city]]

    cities = _add_missing(_sorted(city_zones), saved_cities)
    zone_source = [c for c in saved_cities if c in city_zones] if saved_cities else list(city_zones)
    zones = []
    for city in zone_source:
        zones += [z for z in city_zones[city] if z not in zones]
    zones = _add_missing(_sorted(zones), saved_zones)

    return {
        "no_province": geo.NO_PROVINCE,
        "countries": countries,
        "country": country,
        "provinces": provinces,
        "province": province,
        "cities": cities,
        "selected_cities": saved_cities,
        "cities_all": not saved_cities,
        "zones": zones,
        "selected_zones": saved_zones,
        "zones_all": not saved_zones,
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
    Poblaciones y zonas vacías = "Todas".
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
    criteria.zones = [z for z in zones if z] or None
    criteria.cities = [c for c in cities if c] or None
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
