"""Cambio de nombre de un comprador (PLAN_RENOMBRAR_COMPRADOR.md).

El nombre vive en `Buyer.name` y, copiado al crear cada alerta, en
`PropertyAlert.lead_name` (es lo que pintan listado, detalle, Inicio y
resultados). Al renombrar se actualizan los dos: la ficha y **todas** las
alertas del comprador, abiertas y cerradas, para que la misma persona no salga
con dos nombres. Lo usan "Editar contacto" de la ficha y "Editar nombre" del
detalle de la alerta. No registra seguimiento: es una corrección de datos.
"""
from typing import Optional

from sqlalchemy.orm import Session

from app.models.buyer import Buyer
from app.models.property_alert import PropertyAlert

NAME_MAX_LENGTH = 150


class BuyerNameError(ValueError):
    """Nombre vacío o demasiado largo; el mensaje va al flash tal cual."""


def clean_buyer_name(name: Optional[str]) -> str:
    """Nombre recortado y validado (obligatorio, hasta `NAME_MAX_LENGTH`)."""
    value = " ".join((name or "").split())
    if not value:
        raise BuyerNameError("El nombre del comprador es obligatorio")
    if len(value) > NAME_MAX_LENGTH:
        raise BuyerNameError(f"El nombre no puede superar los {NAME_MAX_LENGTH} caracteres")
    return value


def rename_buyer(db: Session, buyer: Optional[Buyer], name: str, alert: Optional[PropertyAlert] = None) -> int:
    """Pone `name` en la ficha y en el `lead_name` de todas sus alertas (sin commit).

    `alert`: alerta desde la que se renombra; si no tiene ficha (`buyer_id`
    nulo, alertas antiguas) solo se actualiza esa alerta. Devuelve cuántas
    alertas cambiaron.
    """
    name = clean_buyer_name(name)
    if buyer is None:
        if alert is None:
            return 0
        alert.lead_name = name
        return 1

    buyer.name = name
    updated = (
        db.query(PropertyAlert)
        .filter(PropertyAlert.buyer_id == buyer.id, PropertyAlert.lead_name != name)
        .update({PropertyAlert.lead_name: name}, synchronize_session="fetch")
    )
    if alert is not None:
        alert.lead_name = name
    return updated
