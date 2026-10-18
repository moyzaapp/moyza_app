"""Perfil de búsqueda del comprador y propiedades compatibles (PLAN_ALERTA_SIN_REFERENCIA.md).

Lo usan la ficha del comprador (pestaña "Propiedades compatibles") y el
detalle de una alerta sin referencia (paso "Propuesta"):

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

from sqlalchemy.orm import Session, joinedload

from app.core.constants import PropertyStatus
from app.models.buyer_search_criteria import BuyerSearchCriteria
from app.models.property import Property
from app.services.company_scope import scope_properties
from app.web.template_env import eur


# Ubicaciones que se nombran en el resumen antes de abreviar con "+N"
SUMMARY_MAX_PLACES = 2


# ---------------------------------------------------------------------------
# Propiedades compatibles
# ---------------------------------------------------------------------------

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
    """Vuelca el formulario del perfil en `criteria` (sin m²: se conservan tal cual)."""
    criteria.agent_id = agent_id or None
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


def criteria_parts(criteria: Optional[BuyerSearchCriteria]) -> list:
    """Trozos del resumen, en el orden en que se leen. Vacío si no hay perfil."""
    if criteria is None:
        return []
    parts = []
    if criteria.property_type:
        parts.append(criteria.property_type)
    places = list(criteria.zones or []) + list(criteria.cities or [])
    if places:
        extra = len(places) - SUMMARY_MAX_PLACES
        shown = ", ".join(places[:SUMMARY_MAX_PLACES])
        parts.append(f"{shown} +{extra}" if extra > 0 else shown)
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
    """Nota del seguimiento automático CALIFICADO al guardar el perfil desde la alerta."""
    summary = criteria_summary(criteria) or "sin filtros"
    note = f"Perfil de búsqueda: {summary}."
    if criteria.notes:
        note += f" Imprescindibles: {criteria.notes}"
    return note
