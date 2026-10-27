"""
Normaliza los teléfonos guardados de compradores y alertas al formato canónico
(PLAN_TELEFONO_COMPRADOR.md §2.5): dígitos con el indicativo y sin `+`
("34600112233"), el mismo que guardan ya los formularios; con `+` delante si
el indicativo no es del selector ("+41791234567", `app.core.phone.storage_phone`).

Opcional: la app lee bien los valores antiguos (split_phone, phone_display,
whatsapp_url). Por defecto solo informa (--dry-run); con --apply reescribe
únicamente los valores con resultado inequívoco:

- `storage_phone` no es None (los mismos que tienen botón de WhatsApp), y
- el indicativo es explícito (`+`, `00` o un indicativo conocido al inicio) o,
  si no lo hay, el número parece español (9 dígitos que empiezan por 6-9).
  Un "3134808723" sin indicativo (móvil colombiano, por ejemplo) se queda
  como está aunque WhatsApp le anteponga 34: hay que revisarlo a mano.

Los demás se listan y se dejan como están.

Columnas: buyers.phone y property_alerts.lead_phone (todas las empresas).

    docker exec moyza_backend python scripts/normalize_buyer_phones.py            # dry-run
    docker exec moyza_backend python scripts/normalize_buyer_phones.py --apply
    docker exec moyza_backend python scripts/normalize_buyer_phones.py --examples 50
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.db.base  # noqa: E402,F401  (registra todos los modelos)
from app.core.constants import PhoneCountryCodes  # noqa: E402
from app.core.phone import _has_plus_prefix, storage_phone  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.buyer import Buyer  # noqa: E402
from app.models.property_alert import PropertyAlert  # noqa: E402


SPANISH_LOCAL_DIGITS = 9
SPANISH_FIRST_DIGITS = "6789"


def is_unambiguous(value) -> bool:
    """True si el indicativo es explícito o el número parece español."""
    text = str(value).strip()
    digits = "".join(ch for ch in text if ch.isdigit())
    if _has_plus_prefix(text) or digits.startswith("00"):
        return True
    _code, local = PhoneCountryCodes.split(digits)
    if local != digits:
        return True
    return len(digits) == SPANISH_LOCAL_DIGITS and digits[0] in SPANISH_FIRST_DIGITS


def plan_changes(rows):
    """Clasifica (id, valor) en sin cambios, a cambiar y a revisar a mano."""
    unchanged, changes, unusable = 0, [], []
    for row_id, value in rows:
        if value is None or not str(value).strip():
            continue
        canonical = storage_phone(value)
        if canonical is None or not is_unambiguous(value):
            unusable.append((row_id, value))
        elif canonical == value:
            unchanged += 1
        else:
            changes.append((row_id, value, canonical))
    return unchanged, changes, unusable


def report(label, unchanged, changes, unusable, examples):
    print(f"\n== {label} ==")
    print(f"  ya canónicos:      {unchanged}")
    print(f"  cambiarían:        {len(changes)}")
    print(f"  a revisar a mano:  {len(unusable)} (se dejan como están)")
    for row_id, old, new in changes[:examples]:
        print(f"    #{row_id}: {old!r} -> {new!r}")
    if len(changes) > examples:
        print(f"    … y {len(changes) - examples} más")
    for row_id, old in unusable[:examples]:
        print(f"    #{row_id}: {old!r} (sin cambio)")
    if len(unusable) > examples:
        print(f"    … y {len(unusable) - examples} más")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True, help="solo informa (por defecto)")
    mode.add_argument("--apply", action="store_true", help="reescribe los valores inequívocos")
    parser.add_argument("--examples", type=int, default=15, help="ejemplos a listar por tabla")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        targets = [
            ("buyers.phone", Buyer, Buyer.phone, "phone"),
            ("property_alerts.lead_phone", PropertyAlert, PropertyAlert.lead_phone, "lead_phone"),
        ]
        total = 0
        for label, model, column, attr in targets:
            rows = db.query(model.id, column).filter(column.isnot(None)).all()
            unchanged, changes, unusable = plan_changes(rows)
            report(label, unchanged, changes, unusable, args.examples)
            total += len(changes)

            if args.apply and changes:
                for row_id, _old, new in changes:
                    db.query(model).filter(model.id == row_id).update(
                        {attr: new}, synchronize_session=False
                    )

        if args.apply:
            db.commit()
            print(f"\nAplicado: {total} valores reescritos.")
        else:
            print(f"\nDry-run: {total} valores cambiarían. Nada modificado (usa --apply para escribir).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
