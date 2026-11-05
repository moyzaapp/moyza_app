"""
Números en formato español (app/core/numbers.py;
PLAN_VISITAS_INDICATIVO_HONORARIOS.md §2.2): coma decimal, punto solo de miles.

    docker exec moyza_backend python -m pytest tests/test_numbers.py -q
"""
from decimal import Decimal

import pytest

from app.core.numbers import format_es_decimal, parse_es_decimal


@pytest.mark.parametrize("text, expected", [
    ("2500", Decimal("2500")),
    ("2.500", Decimal("2500")),
    ("1.250.000", Decimal("1250000")),
    ("2500,50", Decimal("2500.50")),
    ("2.500,5", Decimal("2500.5")),
    ("1,2", Decimal("1.2")),
    ("0", Decimal("0")),
    (" 3 ", Decimal("3")),
])
def test_parse_es_decimal(text, expected):
    assert parse_es_decimal(text) == expected


@pytest.mark.parametrize("text", [
    "1.2",          # punto con dos dígitos: ambiguo
    "1.25",
    "1.2.3",
    "12.3456",      # punto con cuatro dígitos
    "1,2,3",
    "1,234",        # más de dos decimales
    ".5",
    ",5",
    "",
    None,
    "abc",
    "2.500.",
])
def test_parse_es_decimal_rechaza(text):
    with pytest.raises(ValueError):
        parse_es_decimal(text)


def test_parse_es_decimal_max_decimals():
    assert parse_es_decimal("1,234", max_decimals=3) == Decimal("1.234")


@pytest.mark.parametrize("value, kwargs, expected", [
    (Decimal("2500"), {}, "2.500"),
    (Decimal("2500.5"), {}, "2.500,5"),
    (Decimal("2500.5"), {"pad": True}, "2.500,50"),
    (Decimal("2500"), {"pad": True}, "2.500"),
    (Decimal("2500.5"), {"thousands": False}, "2500,5"),
    (Decimal("1250000.25"), {}, "1.250.000,25"),
    (Decimal("2.5"), {}, "2,5"),
    (Decimal("2.50"), {}, "2,5"),
    (Decimal("2.555"), {}, "2,56"),
    (Decimal("0"), {}, "0"),
    (Decimal("-1234.5"), {}, "-1.234,5"),
    (2500, {}, "2.500"),
    ("2500.5", {}, "2.500,5"),
])
def test_format_es_decimal(value, kwargs, expected):
    assert format_es_decimal(value, **kwargs) == expected


def test_ida_y_vuelta():
    for text in ("2500", "2.500,50", "1,2", "1.250.000"):
        assert parse_es_decimal(format_es_decimal(parse_es_decimal(text))) == parse_es_decimal(text)
