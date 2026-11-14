"""Enlace público de una propiedad y mensaje para enviarla al comprador.

PLAN_ENVIO_PROPIEDAD_COMPRADOR.md §4.1 y §4.3. El enlace a la ficha en la web
de la inmobiliaria es `Property.public_url`: lo trae la ETL del CRM y se puede
corregir en el formulario. La app no lo calcula: si la columna está vacía no
hay enlace (ni botón de enviar). El patrón por referencia que se usó al
principio se retiró porque fallaba en parte de los inmuebles de MOYZA.

`property_public_url` se registra como filtro Jinja (`{{ prop | public_url }}`)
en app/web/template_env.py.
"""
from urllib.parse import urlparse

from app.core.numbers import format_es_decimal

# Longitud máxima del enlace manual (columna String(500))
PUBLIC_URL_MAX_LENGTH = 500

PUBLIC_URL_ERROR = "El enlace en la web debe empezar por http:// o https://"
PUBLIC_URL_LENGTH_ERROR = f"El enlace en la web no puede tener más de {PUBLIC_URL_MAX_LENGTH} caracteres"


def property_public_url(prop) -> str | None:
    """Enlace público de la propiedad (`prop.public_url` recortado) o None si
    no tiene."""
    return (getattr(prop, "public_url", None) or "").strip() or None


def clean_public_url(value) -> str | None:
    """Normaliza lo que llega del formulario: recorta; vacío → None; exige
    http:// o https:// y un máximo de 500 caracteres (ValueError si no)."""
    text = str(value or "").strip()
    if not text:
        return None
    if len(text) > PUBLIC_URL_MAX_LENGTH:
        raise ValueError(PUBLIC_URL_LENGTH_ERROR)
    parsed = urlparse(text)
    if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc or any(ch.isspace() for ch in text):
        raise ValueError(PUBLIC_URL_ERROR)
    return text


# ---------------------------------------------------------------------------
# Mensaje de WhatsApp
# ---------------------------------------------------------------------------

def _first_name(name) -> str:
    parts = str(name or "").split()
    return parts[0] if parts else ""


def _price(value) -> str:
    if value is None or value == "":
        return ""
    try:
        return format_es_decimal(value, max_decimals=0) + " €"
    except (ArithmeticError, TypeError, ValueError):
        return ""


def _place(prop) -> str:
    """Zona y población ("Bulevar, Jaén"), o la que haya. Nunca la dirección."""
    zona = (getattr(prop, "zona", None) or "").strip()
    city = (getattr(prop, "city", None) or "").strip()
    if zona and city and zona.lower() != city.lower():
        return f"{zona}, {city}"
    return zona or city


def share_message(prop, buyer_name, agent_name) -> str:
    """Texto prellenado para enviar la propiedad por WhatsApp (texto fijo, §4.3):

        Hola {nombre}, soy {agente} de {empresa}. Te envío este inmueble que puede encajar con lo que buscas:

        {tipo} en {zona o ciudad} · {dormitorios} dorm. · {precio}
        {enlace}

    - {nombre}: primer nombre del comprador; sin nombre, "Hola,".
    - {empresa}: la de la propiedad.
    - Se omiten los datos vacíos. Nunca la dirección ni el propietario.
    """
    first = _first_name(buyer_name)
    greeting = f"Hola {first}," if first else "Hola,"

    agent = str(agent_name or "").strip()
    company = getattr(getattr(prop, "company", None), "name", None) or ""
    if agent and company:
        intro = f" soy {agent} de {company}."
    elif agent:
        intro = f" soy {agent}."
    elif company:
        intro = f" te escribo de {company}."
    else:
        intro = ""
    if intro:
        lead = f"{greeting}{intro} Te envío este inmueble que puede encajar con lo que buscas:"
    else:
        lead = f"{greeting} te envío este inmueble que puede encajar con lo que buscas:"

    kind = (getattr(prop, "property_type", None) or "").strip()
    place = _place(prop)
    if kind and place:
        what = f"{kind} en {place}"
    elif place:
        what = f"Inmueble en {place}"
    else:
        what = kind
    bedrooms = getattr(prop, "num_dormitorios", None)
    details = [
        what,
        f"{bedrooms} dorm." if bedrooms else "",
        _price(getattr(prop, "price", None)),
    ]
    data_line = " · ".join(part for part in details if part)

    lines = [lead, ""]
    if data_line:
        lines.append(data_line)
    link = property_public_url(prop)
    if link:
        lines.append(link)
    return "\n".join(lines).rstrip()
