"""
Unifica la grafía de las poblaciones guardadas (PLAN_PERFIL_ZONAS.md, fase D).

La población de una propiedad es texto libre y "Jaen" y "Jaén" salían como
dos poblaciones distintas en el perfil del comprador. Este script pone la
grafía oficial de la tabla `app.core.geo.CITY_SPELLINGS` (poblaciones de la
provincia de Jaén más habituales) con `geo.normalize_city`, la misma función
que usa ya el formulario de propiedad al guardar. Lo que no está en la tabla
solo se limpia de espacios.

Columnas (todas las empresas):
- `properties.city`
- `buyer_search_criteria.cities` (lista JSON): cada población se normaliza y
  se quitan las repetidas que salgan ("Jaen", "Jaén" → "Jaén").

No es una migración: se ejecuta una vez tras desplegar. Por defecto solo
informa (--dry-run); con --apply escribe. No deja registro en el historial de
cambios de la propiedad (es una corrección de datos, no una edición).

    docker exec moyza_backend python scripts/normalize_city_names.py            # dry-run
    docker exec moyza_backend python scripts/normalize_city_names.py --apply
    docker exec moyza_backend python scripts/normalize_city_names.py --examples 50
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.db.base  # noqa: E402,F401  (registra todos los modelos)
from app.core import geo  # noqa: E402
from app.models.buyer_search_criteria import BuyerSearchCriteria  # noqa: E402
from app.models.property import Property  # noqa: E402


def normalized_cities(cities) -> list:
    """Lista de poblaciones con la grafía oficial, sin vacías ni repetidas (en su orden)."""
    result = []
    for city in cities or []:
        name = geo.normalize_city(city)
        if name and name not in result:
            result.append(name)
    return result


def plan_property_changes(rows) -> list:
    """[(id, antes, después)] de las propiedades cuya población cambia."""
    changes = []
    for row_id, city in rows:
        if city is None:
            continue
        new = geo.normalize_city(city)
        if new != city:
            changes.append((row_id, city, new))
    return changes


def plan_criteria_changes(rows) -> list:
    """[(id, antes, después)] de los perfiles cuya lista de poblaciones cambia."""
    changes = []
    for row_id, cities in rows:
        if not cities:
            continue
        new = normalized_cities(cities)
        if new != list(cities):
            changes.append((row_id, list(cities), new or None))
    return changes


def run(db, apply: bool = False) -> dict:
    """Calcula (y con `apply`, escribe y confirma) los cambios. Devuelve los cambios por columna."""
    property_changes = plan_property_changes(db.query(Property.id, Property.city).all())
    criteria_changes = plan_criteria_changes(db.query(BuyerSearchCriteria.id, BuyerSearchCriteria.cities).all())
    if apply:
        for row_id, _old, new in property_changes:
            db.query(Property).filter(Property.id == row_id).update({"city": new}, synchronize_session=False)
        for row_id, _old, new in criteria_changes:
            # Se asigna una lista nueva: la columna JSON detecta el cambio
            db.get(BuyerSearchCriteria, row_id).cities = new
        db.commit()
    return {"properties.city": property_changes, "buyer_search_criteria.cities": criteria_changes}


def report(changes: dict, examples: int, applied: bool) -> None:
    total = 0
    for label, rows in changes.items():
        total += len(rows)
        print(f"\n== {label} ==")
        print(f"  {'cambiadas' if applied else 'cambiarían'}: {len(rows)}")
        for row_id, old, new in rows[:examples]:
            print(f"    #{row_id}: {old!r} -> {new!r}")
        if len(rows) > examples:
            print(f"    … y {len(rows) - examples} más")
    if applied:
        print(f"\nAplicado: {total} filas actualizadas.")
    else:
        print(f"\nDry-run: {total} filas cambiarían. Nada modificado (usa --apply para escribir).")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True, help="solo informa (por defecto)")
    mode.add_argument("--apply", action="store_true", help="escribe los cambios")
    parser.add_argument("--examples", type=int, default=15, help="ejemplos a listar por columna")
    args = parser.parse_args()

    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        report(run(db, apply=args.apply), args.examples, args.apply)
    finally:
        db.close()


if __name__ == "__main__":
    main()
