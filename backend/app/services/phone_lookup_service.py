"""
Consulta de teléfono de propietario (pestaña "Consultar teléfono" de
Propiedades).

Un agente escribe el teléfono COMPLETO de un propietario y la app responde qué
propiedades en cartera tiene, para no llamar ni volver a publicar un inmueble
ya captado. Reglas:

- Solo coincidencia de número completo: se comparan teléfonos canónicos
  (`app.core.phone.canonical_phone`), nunca fragmentos.
- En cartera = status Activa, Reservada o Pausada (PORTFOLIO_STATUSES). No se
  mira `estado_inmueble`: una "No disponible" con status Activa sigue captada.
- Solo responde con propiedades de las empresas del usuario (`company_ids`:
  las de `request.state.allowed_companies`; el admin, todas). Un agente de
  MOYZA no ve si el propietario tiene inmuebles con MOES PREMIUM, y al revés.
  No depende de la empresa activa: quien trabaja en las dos ve las dos.
- Del propietario solo sale el nombre enmascarado ("Mar*** Na***"). El nombre
  real, el email, el teléfono guardado y el id del cliente no salen del
  servicio: no están en los dicts devueltos.
"""
import re

from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.core.address import street_only
from app.core.constants import PropertyStatus
from app.core.phone import canonical_phone
from app.models.agent import Agent
from app.models.client import Client
from app.models.company import Company
from app.models.property import Property

# Estados en los que una propiedad sigue en cartera
PORTFOLIO_STATUSES = (PropertyStatus.ACTIVE, PropertyStatus.RESERVED, PropertyStatus.PAUSED)

# Asteriscos fijos de la máscara: siempre los mismos para no revelar la longitud
MASK = "***"
# Letras visibles como mucho: primera palabra y resto
_VISIBLE_FIRST_WORD = 3
_VISIBLE_OTHER_WORDS = 2

# Separadores entre dos teléfonos escritos en el mismo campo: / , ; | y la palabra " y "
_PHONE_SEPARATORS = re.compile(r"[/,;|]|\s+y\s+", re.IGNORECASE)


def mask_name(name) -> str:
    """Nombre enmascarado por palabras: "María Navarro López" → "Mar*** Na*** Ló***".

    De la primera palabra se ven hasta 3 letras y del resto hasta 2, seguidas
    de `***` fijo. Nunca se muestra la palabra entera (como mucho, todas sus
    letras menos una; una palabra de una letra queda como esa letra + `***`).
    Vacío o None → "".
    """
    words = str(name or "").split()
    masked = []
    for index, word in enumerate(words):
        limit = _VISIBLE_FIRST_WORD if index == 0 else _VISIBLE_OTHER_WORDS
        visible = max(1, min(limit, len(word) - 1))
        masked.append(word[:visible] + MASK)
    return " ".join(masked)


def phone_candidates(raw) -> set[str]:
    """Teléfonos canónicos contenidos en un valor guardado en texto libre.

    Lo normal es uno ("600 11 22 33", "+34 600-112-233", "0034600112233" →
    {"34600112233"}). Con dos teléfonos en el mismo campo ("600112233 /
    953112233") el valor completo no es canónico: se trocea por `/ , ; |` y la
    palabra " y " y se canoniza cada trozo.

    Si hay separador, los trozos se añaden aunque el valor completo también
    sea canónico ("600112233 / 12" son 11 dígitos seguidos, un número posible):
    aquí lo caro es no reconocer a un propietario ya captado.
    """
    text = str(raw or "").strip()
    if not text:
        return set()

    values = [text]
    pieces = _PHONE_SEPARATORS.split(text)
    if len(pieces) > 1:
        values += pieces

    candidates = (canonical_phone(value) for value in values)
    return {candidate for candidate in candidates if candidate}


def lookup_properties_by_phone(db: Session, phone, company_ids) -> list[dict]:
    """Propiedades en cartera del propietario con ese teléfono, en las empresas `company_ids`.

    `phone` es cualquier valor que `canonical_phone` acepte; si no es
    canónico (incompleto, vacío) devuelve []. Solo coincide el número completo.

    Los teléfonos antiguos de clientes están en texto libre, así que no se
    compara en SQL: se cargan (id, teléfono) de los clientes con alguna
    propiedad en cartera y se comparan en Python con `phone_candidates`.

    `company_ids` (ids de empresa que el usuario puede usar) es obligatorio:
    sin empresas no hay resultados. Las
    filas se construyen con `with_entities` sobre columnas explícitas y el
    nombre del propietario se enmascara aquí: el dict no lleva nombre real,
    email, teléfono ni id del cliente.

    Claves: id, title, referencia, address (solo la calle, `street_only`),
    city, zona, property_type, business_type, price, moneda, status,
    agent_name, company ({"name", "primary_color"} o None) y owner_masked.
    Orden: empresa, título.
    """
    target = canonical_phone(phone)
    company_ids = [company_id for company_id in (company_ids or []) if company_id is not None]
    if not target or not company_ids:
        return []

    # En cartera y de una empresa del usuario: vale para buscar al propietario
    # y para listar sus propiedades (las de otra empresa no cuentan ni salen)
    in_portfolio = and_(
        Property.status.in_(PORTFOLIO_STATUSES),
        Property.company_id.in_(company_ids),
    )

    owners = (
        db.query(Client.id, Client.phone)
        .filter(
            Client.id.in_(
                db.query(Property.client_id).filter(in_portfolio, Property.client_id.isnot(None))
            )
        )
        .all()
    )
    client_ids = [client_id for client_id, stored in owners if target in phone_candidates(stored)]
    if not client_ids:
        return []

    rows = (
        db.query(Property)
        .join(Client, Client.id == Property.client_id)
        .outerjoin(Agent, Agent.id == Property.agent_id)
        .outerjoin(Company, Company.id == Property.company_id)
        .filter(Property.client_id.in_(client_ids), in_portfolio)
        .with_entities(
            Property.id,
            Property.title,
            Property.referencia,
            Property.address,
            Property.city,
            Property.zona,
            Property.property_type,
            Property.business_type,
            Property.price,
            Property.moneda,
            Property.status,
            Agent.name.label("agent_name"),
            Company.id.label("company_id"),
            Company.name.label("company_name"),
            Company.primary_color.label("company_color"),
            Client.name.label("owner_name"),
        )
        .order_by(Company.id.asc(), Property.title.asc(), Property.id.asc())
        .all()
    )

    results = []
    for row in rows:
        company = None
        if row.company_id is not None:
            company = {"name": row.company_name, "primary_color": row.company_color}
        results.append({
            "id": row.id,
            "title": row.title,
            "referencia": row.referencia,
            "address": street_only(row.address) or None,
            "city": row.city,
            "zona": row.zona,
            "property_type": row.property_type,
            "business_type": row.business_type,
            "price": row.price,
            "moneda": row.moneda,
            "status": row.status,
            "agent_name": row.agent_name,
            "company": company,
            "owner_masked": mask_name(row.owner_name),
        })
    return results
