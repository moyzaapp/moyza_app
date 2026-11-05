"""
Números escritos y mostrados en formato español
(PLAN_VISITAS_INDICATIVO_HONORARIOS.md §2.2).

Regla única: la coma es el separador decimal y el punto solo separa miles,
siempre seguido de tres dígitos. "1.2" no se interpreta: se rechaza para que
nadie guarde 1,2 creyendo que son 1.200 ni al revés.

    parse_es_decimal("2.500,50")  -> Decimal("2500.50")
    parse_es_decimal("1,2")       -> Decimal("1.2")
    parse_es_decimal("1.2")       -> ValueError
    format_es_decimal(Decimal("2500.5"), pad=True)        -> "2.500,50"
    format_es_decimal(Decimal("2.5"))                     -> "2,5"
    format_es_decimal(Decimal("2500.5"), thousands=False) -> "2500,5"
"""
import re
from decimal import Decimal

# Entero con o sin puntos de miles (cada punto seguido de tres dígitos) y
# parte decimal opcional tras la coma
ES_DECIMAL_PATTERN = re.compile(r"(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d+)?")

# Mensaje para el usuario cuando un número no cumple la regla
ES_DECIMAL_HINT = "usa la coma para los decimales (1,2) y el punto solo para los miles (2.500)"


def parse_es_decimal(text, max_decimals: int = 2) -> Decimal:
    """Decimal a partir de un número en formato español; ValueError si no lo
    cumple o tiene más de `max_decimals` decimales. Admite espacios alrededor."""
    raw = str(text or "").strip()
    if not ES_DECIMAL_PATTERN.fullmatch(raw):
        raise ValueError(ES_DECIMAL_HINT)
    integer, _, fraction = raw.partition(",")
    if len(fraction) > max_decimals:
        raise ValueError(f"como mucho {max_decimals} decimales")
    return Decimal(integer.replace(".", "") + (f".{fraction}" if fraction else ""))


def format_es_decimal(value, max_decimals: int = 2, pad: bool = False, thousands: bool = True) -> str:
    """Número en formato español: miles con punto (salvo `thousands=False`) y
    decimales con coma, redondeado a `max_decimals`. Sin ceros a la derecha;
    con `pad=True` una parte decimal distinta de cero se completa hasta
    `max_decimals` ("2.500,50")."""
    quantum = Decimal(1).scaleb(-max_decimals) if max_decimals else Decimal(1)
    number = Decimal(value).quantize(quantum)
    sign = "-" if number < 0 else ""
    integer, _, fraction = f"{abs(number):f}".partition(".")
    fraction = fraction.rstrip("0")
    if fraction and pad:
        fraction = fraction.ljust(max_decimals, "0")
    if thousands:
        integer = f"{int(integer):,}".replace(",", ".")
    return f"{sign}{integer},{fraction}" if fraction else f"{sign}{integer}"
