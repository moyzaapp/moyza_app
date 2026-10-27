"""Dirección de una propiedad para mostrar en la app: solo la calle.

Petición del usuario: que no salga el número de la calle en ningún sitio de
la app. La regla acordada es sencilla y solo mira la coma: se muestra lo que
hay antes de la primera coma ("Calle Fuente del Peral, 8" → "Calle Fuente del
Peral"). Una dirección sin coma ("Calle Test 1") se muestra tal cual.

Excepciones (dirección completa): el formulario de alta/edición de la
propiedad, los PDF (ficha de visita e informes), su vista previa en pantalla
y los textos de WhatsApp. Los buscadores siguen buscando sobre la dirección
completa. En plantillas: filtro Jinja `street`; en Python, `Property.street`.
"""


def street_only(value) -> str:
    """Texto antes de la primera coma, sin espacios sobrantes; None o vacío → ""."""
    if value is None:
        return ""
    return str(value).split(",", 1)[0].strip()
