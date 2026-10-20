"""Geografía del perfil de búsqueda (PLAN_PERFIL_UBICACION.md).

Las propiedades no tienen columna de provincia: se deduce del código postal
español (los dos primeros dígitos, 01–52). Un CP que no sea de cinco dígitos
o cuyo prefijo no esté en la tabla no tiene provincia ("Sin provincia").

El país vacío de una propiedad se trata como España (la gran mayoría no lo
tiene relleno); `normalize_country` unifica además las variantes habituales
("españa", "Spain", "ES"…) para que no salgan repetidas en la cascada.
"""
import unicodedata
from typing import Optional

# País por defecto: el de las propiedades sin país
SPAIN = "España"

# Variantes (en minúsculas, sin espacios alrededor) que se leen como España
SPAIN_ALIASES = ("españa", "espana", "spain", "es", "esp")

# Agrupación de las poblaciones de propiedades sin CP válido (no es una provincia)
NO_PROVINCE = "Sin provincia"

# Provincias por prefijo de código postal (nombres en castellano)
PROVINCIAS_POR_CP = {
    "01": "Álava",
    "02": "Albacete",
    "03": "Alicante",
    "04": "Almería",
    "05": "Ávila",
    "06": "Badajoz",
    "07": "Baleares",
    "08": "Barcelona",
    "09": "Burgos",
    "10": "Cáceres",
    "11": "Cádiz",
    "12": "Castellón",
    "13": "Ciudad Real",
    "14": "Córdoba",
    "15": "A Coruña",
    "16": "Cuenca",
    "17": "Girona",
    "18": "Granada",
    "19": "Guadalajara",
    "20": "Guipúzcoa",
    "21": "Huelva",
    "22": "Huesca",
    "23": "Jaén",
    "24": "León",
    "25": "Lleida",
    "26": "La Rioja",
    "27": "Lugo",
    "28": "Madrid",
    "29": "Málaga",
    "30": "Murcia",
    "31": "Navarra",
    "32": "Ourense",
    "33": "Asturias",
    "34": "Palencia",
    "35": "Las Palmas",
    "36": "Pontevedra",
    "37": "Salamanca",
    "38": "Santa Cruz de Tenerife",
    "39": "Cantabria",
    "40": "Segovia",
    "41": "Sevilla",
    "42": "Soria",
    "43": "Tarragona",
    "44": "Teruel",
    "45": "Toledo",
    "46": "Valencia",
    "47": "Valladolid",
    "48": "Vizcaya",
    "49": "Zamora",
    "50": "Zaragoza",
    "51": "Ceuta",
    "52": "Melilla",
}

_PREFIJO_POR_PROVINCIA = {nombre: prefijo for prefijo, nombre in PROVINCIAS_POR_CP.items()}


def sort_key(text: str) -> str:
    """Clave de orden alfabético sin acentos ni mayúsculas ('Álava' junto a 'Albacete')."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def is_spain(country: Optional[str]) -> bool:
    """True si el país está vacío o es una variante de España."""
    return (country or "").strip().lower() in ("",) + SPAIN_ALIASES


def normalize_country(country: Optional[str]) -> str:
    """País de una propiedad tal como se agrupa: vacío o variante de España → 'España'."""
    return SPAIN if is_spain(country) else country.strip()


def provincia_from_cp(cp: Optional[str]) -> Optional[str]:
    """'23004' → 'Jaén'. None si el CP no tiene cinco dígitos o el prefijo no existe."""
    value = str(cp or "").strip()
    if len(value) != 5 or not value.isdigit():
        return None
    return PROVINCIAS_POR_CP.get(value[:2])


def provincia_for(pais: Optional[str], cp: Optional[str]) -> Optional[str]:
    """Provincia de una propiedad: la del CP si el país es España (vacío cuenta como España)."""
    return provincia_from_cp(cp) if is_spain(pais) else None


def cp_prefix_for_provincia(nombre: Optional[str]) -> Optional[str]:
    """'Jaén' → '23'. None si el nombre no es una provincia de la tabla."""
    return _PREFIJO_POR_PROVINCIA.get((nombre or "").strip())
