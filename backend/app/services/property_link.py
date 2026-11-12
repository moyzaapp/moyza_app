"""Enlace público de una propiedad y mensaje para enviarla al comprador.

PLAN_ENVIO_PROPIEDAD_COMPRADOR.md §4.1 y §4.3. Único punto de verdad del
enlace a la ficha en la web de la inmobiliaria:

1. `Property.public_url`, si alguien lo pegó a mano (manda siempre: cubre las
   excepciones del patrón y las empresas sin plantilla, como MOES hoy).
2. La plantilla de la empresa **de la propiedad** (no la activa: las
   sugerencias mezclan las dos), `Company.property_url_template`, con el
   marcador `{referencia}` sustituido por la referencia recortada y
   codificada con `urllib.parse.quote`.
3. None: no se puede saber.

No se comprueba en vivo contra la web (lento y frágil; además responde 200
también cuando el inmueble no existe): el agente puede abrir el enlace antes
de enviarlo.

`property_public_url` se registra como filtro Jinja (`{{ prop | public_url }}`)
en app/web/template_env.py.
"""
from urllib.parse import quote
from urllib.parse import urlparse

from app.core.numbers import format_es_decimal

# Marcador de la plantilla de la empresa
REFERENCE_PLACEHOLDER = "{referencia}"

# Longitud máxima del enlace manual (columna String(500))
PUBLIC_URL_MAX_LENGTH = 500

PUBLIC_URL_ERROR = "El enlace en la web debe empezar por http:// o https://"
PUBLIC_URL_LENGTH_ERROR = f"El enlace en la web no puede tener más de {PUBLIC_URL_MAX_LENGTH} caracteres"

# Origen del enlace (nota discreta en el detalle de la propiedad)
SOURCE_MANUAL = "manual"
SOURCE_TEMPLATE = "template"


def build_public_url(manual_url, referencia, template) -> str | None:
    """Regla del módulo a partir de los datos sueltos (filas de solo lectura
    que no cargan el modelo). Ver `property_public_url`."""
    manual = (manual_url or "").strip()
    if manual:
        return manual
    reference = str(referencia or "").strip()
    if not template or not reference or REFERENCE_PLACEHOLDER not in template:
        return None
    return template.replace(REFERENCE_PLACEHOLDER, quote(reference, safe=""))


def property_public_url(prop) -> str | None:
    """Enlace público de la propiedad o None si no se puede saber.

    1. prop.public_url si está relleno.
    2. Plantilla de su empresa (prop.company.property_url_template) con la
       referencia recortada, si hay plantilla y referencia.
    3. None.
    """
    if prop is None:
        return None
    company = getattr(prop, "company", None)
    template = getattr(company, "property_url_template", None) if company is not None else None
    return build_public_url(getattr(prop, "public_url", None), getattr(prop, "referencia", None), template)


def public_url_source(prop) -> str | None:
    """SOURCE_MANUAL si el enlace es el pegado a mano, SOURCE_TEMPLATE si sale
    de la plantilla de la empresa, None si no hay enlace."""
    if (getattr(prop, "public_url", None) or "").strip():
        return SOURCE_MANUAL
    return SOURCE_TEMPLATE if property_public_url(prop) else None


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
