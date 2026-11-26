"""Excel de compradores para administración (PLAN_EXPORT_EXCEL_COMPRADORES.md).

`build_buyers_workbook` devuelve un `.xlsx` con una sola hoja, «Compradores»
(§6, D6: las hojas «Resumen» y «Alertas» se retiraron el 2026-11-24), con los
compradores de la empresa dada dados de alta en un rango de días de Madrid
(inclusivo), su perfil y los agentes a los que pertenecen (D10: sin las
columnas «Creado por», «Alertas» ni «Última alerta»; «Agentes» va tras «Email»).

Un comprador «es» de un agente (§6.1, D8) si lo creó el usuario del agente
(`Buyer.created_by`, usuario con el email del agente), si el agente es el del
perfil (`BuyerSearchCriteria.agent_id`) o si tiene alguna alerta de la
empresa asignada a él (cualquier estado y fecha). Esa regla filtra con
`agent_ids` y rellena la columna «Agentes» (D9).

«Tipo de negocio» (2026-11-26): operación de las alertas del comprador en la
empresa más la del perfil, «Venta, Alquiler» si tiene de los dos. En Alquiler
no hay perfil, así que antes salía vacía; el resto de columnas de perfil
siguen vacías para un comprador solo de alquiler.

Es un documento de trabajo: cabecera en negrita, fila fija, autofiltro y
fechas en hora de Madrid. Sin fórmulas ni estilos corporativos.
"""
from datetime import date
from datetime import datetime
from datetime import time
from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from typing import Iterable
from typing import Optional

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Font
from openpyxl.styles import PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm import selectinload

from app.core.business_calendar import to_madrid
from app.core.business_calendar import to_utc
from app.core.constants import BusinessType
from app.models.agent import Agent
from app.models.buyer import Buyer
from app.models.buyer_search_criteria import BuyerSearchCriteria
from app.models.property_alert import PropertyAlert
from app.models.user import User
from app.services.buyer_matching import profile_types
from app.services.company_scope import scope_agents

DATETIME_FORMAT = "dd/mm/yyyy hh:mm"
AMOUNT_FORMAT = "#,##0"
HEADER_FONT = Font(bold=True)
HEADER_FILL = PatternFill(fill_type="solid", start_color="FFE5E7EB", end_color="FFE5E7EB")

# (cabecera, ancho) de la hoja
BUYER_COLUMNS = [
    ("Fecha de alta", 17), ("Nombre", 28), ("Teléfono", 16), ("Email", 28),
    ("Agentes", 28),
    ("Tipo de negocio", 15), ("Tipo de inmueble", 22), ("Provincia", 14),
    ("Zonas/ciudades", 32), ("Presupuesto mín.", 16), ("Presupuesto máx.", 16), ("Notas", 40),
]


def utc_range(start: date, end: date) -> tuple:
    """Días de Madrid [start, end] -> (desde, hasta) en UTC naive, hasta exclusivo."""
    return (
        to_utc(datetime.combine(start, time.min)),
        to_utc(datetime.combine(end + timedelta(days=1), time.min)),
    )


def _madrid(value):
    """UTC naive -> datetime de Madrid para la celda (None se queda vacío)."""
    return to_madrid(value) if value is not None else None


def _amount(value):
    """Importe como número para Excel (Numeric llega como Decimal)."""
    if value is None:
        return None
    return float(value) if isinstance(value, Decimal) else value


def _join(*lists) -> str:
    """Une listas JSON (cities, zones) en un texto «a, b», sin vacíos."""
    items = []
    for values in lists:
        for value in values or []:
            text = str(value or "").strip()
            if text:
                items.append(text)
    return ", ".join(items)


def _append(ws, row):
    """Añade una fila tratando todo texto como texto literal.

    Los textos los escriben los agentes (nombres, notas, fuente…): se quitan
    los caracteres de control que openpyxl rechaza (p. ej. el salto manual
    `\\x0b` pegado desde Word) y un valor que empiece por «=» no se guarda
    como fórmula (openpyxl lo haría por defecto).
    """
    ws.append([
        ILLEGAL_CHARACTERS_RE.sub("", value) if isinstance(value, str) else value
        for value in row
    ])
    for cell in ws[ws.max_row]:
        if cell.data_type == "f":
            cell.data_type = "s"


def _write_sheet(ws, columns, rows, date_cols=(), amount_cols=()):
    """Cabecera con formato, filas, formatos de fecha/importe, fila fija y autofiltro."""
    ws.append([header for header, _ in columns])
    for cell in ws[1]:
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
    for index, (_, width) in enumerate(columns, start=1):
        ws.column_dimensions[get_column_letter(index)].width = width
    for row in rows:
        _append(ws, row)
    for row_cells in ws.iter_rows(min_row=2):
        for cell in row_cells:
            if cell.column in date_cols:
                cell.number_format = DATETIME_FORMAT
            elif cell.column in amount_cols:
                cell.number_format = AMOUNT_FORMAT
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions


def _agent_filter(company_id: int, agent_ids: list):
    """Cláusula D8: el comprador es de alguno de `agent_ids`.

    Misma regla que `alerts.visible_buyers_query` para el agente, pero con
    alertas de cualquier estado: lo creó el usuario del agente (por email),
    el agente es el de su perfil o tiene alguna alerta de la empresa suya.
    """
    by_alert = select(PropertyAlert.buyer_id).where(
        PropertyAlert.company_id == company_id,
        PropertyAlert.buyer_id.isnot(None),
        PropertyAlert.agent_id.in_(agent_ids),
    )
    by_profile = select(BuyerSearchCriteria.buyer_id).where(BuyerSearchCriteria.agent_id.in_(agent_ids))
    by_creator = select(User.id).join(Agent, Agent.email == User.email).where(Agent.id.in_(agent_ids))
    return or_(
        Buyer.id.in_(by_alert),
        Buyer.id.in_(by_profile),
        Buyer.created_by.in_(by_creator),
    )


def _buyer_agents(db: Session, company_id: int, buyer_ids: list) -> dict:
    """{buyer_id: «nombre, nombre»} con los agentes de la empresa que cumplen D8.

    Tres consultas agrupadas (alertas, perfiles y creador por email), sin N+1.
    Cuenta también a los agentes dados de baja: el dato es histórico.
    """
    if not buyer_ids:
        return {}
    names = dict(scope_agents(db.query(Agent.id, Agent.name), company_id).all())
    if not names:
        return {}
    agent_ids = list(names)
    pairs = set()
    pairs.update(
        db.query(PropertyAlert.buyer_id, PropertyAlert.agent_id)
        .filter(
            PropertyAlert.company_id == company_id,
            PropertyAlert.buyer_id.in_(buyer_ids),
            PropertyAlert.agent_id.in_(agent_ids),
        )
        .distinct()
        .all()
    )
    pairs.update(
        db.query(BuyerSearchCriteria.buyer_id, BuyerSearchCriteria.agent_id)
        .filter(
            BuyerSearchCriteria.buyer_id.in_(buyer_ids),
            BuyerSearchCriteria.agent_id.in_(agent_ids),
        )
        .all()
    )
    pairs.update(
        db.query(Buyer.id, Agent.id)
        .join(User, User.id == Buyer.created_by)
        .join(Agent, Agent.email == User.email)
        .filter(Buyer.id.in_(buyer_ids), Agent.id.in_(agent_ids))
        .all()
    )
    # Ids, no nombres: dos agentes con el mismo nombre salen los dos
    by_buyer = {}
    for buyer_id, agent_id in pairs:
        by_buyer.setdefault(buyer_id, set()).add(agent_id)
    return {
        buyer_id: ", ".join(sorted((names[a] for a in agents), key=str.lower))
        for buyer_id, agents in by_buyer.items()
    }


def _business_types(db: Session, company_id: int, buyer_ids: list, buyers: list) -> dict:
    """{buyer_id: «Venta, Alquiler»} con la operación de las alertas de la empresa y la del perfil.

    En Alquiler el perfil no se guarda (`buyer_matching.profile_applies`), así
    que la operación vive en la alerta: se unen las de las alertas del comprador
    en la empresa con la del perfil, en el orden de `BusinessType.values()`.
    """
    if not buyer_ids:
        return {}
    by_buyer = {}
    pairs = (
        db.query(PropertyAlert.buyer_id, PropertyAlert.business_type)
        .filter(
            PropertyAlert.company_id == company_id,
            PropertyAlert.buyer_id.in_(buyer_ids),
            PropertyAlert.business_type.isnot(None),
            PropertyAlert.business_type != "",
        )
        .distinct()
        .all()
    )
    for buyer_id, business_type in pairs:
        by_buyer.setdefault(buyer_id, set()).add(business_type)
    for buyer in buyers:
        criteria = buyer.search_criteria
        if criteria is not None and criteria.business_type:
            by_buyer.setdefault(buyer.id, set()).add(criteria.business_type)
    order = {value: index for index, value in enumerate(BusinessType.values())}
    return {
        buyer_id: ", ".join(sorted(types, key=lambda t: (order.get(t, len(order)), t)))
        for buyer_id, types in by_buyer.items()
    }


def _buyer_rows(db: Session, company_id: int, since: datetime, until: datetime,
                agent_ids: Optional[list] = None) -> list:
    query = (
        db.query(Buyer)
        .options(selectinload(Buyer.search_criteria))
        .filter(Buyer.company_id == company_id, Buyer.created_at >= since, Buyer.created_at < until)
    )
    if agent_ids:
        query = query.filter(_agent_filter(company_id, agent_ids))
    buyers = query.order_by(Buyer.created_at.asc(), Buyer.id.asc()).all()
    buyer_ids = [b.id for b in buyers]
    agents = _buyer_agents(db, company_id, buyer_ids)
    business_types = _business_types(db, company_id, buyer_ids, buyers)
    rows = []
    for buyer in buyers:
        criteria = buyer.search_criteria
        rows.append([
            _madrid(buyer.created_at),
            buyer.name,
            buyer.phone or "",
            buyer.email or "",
            agents.get(buyer.id, ""),
            business_types.get(buyer.id, ""),
            ", ".join(profile_types(criteria)),
            (criteria.province or "") if criteria else "",
            _join(criteria.cities, criteria.zones) if criteria else "",
            _amount(criteria.min_price) if criteria else None,
            _amount(criteria.max_price) if criteria else None,
            buyer.notes or "",
        ])
    return rows


def build_buyers_workbook(db: Session, company, start: date, end: date,
                          agent_ids: Optional[Iterable[int]] = None) -> bytes:
    """Libro `.xlsx` con la hoja «Compradores» de `company`: los dados de alta
    entre `start` y `end` (días de Madrid, ambos incluidos).

    Con `agent_ids` (no vacío), solo los compradores de alguno de esos agentes
    (D8); sin ellos, todos. La ruta ya descarta los que no son agentes activos
    de la empresa.
    """
    since, until = utc_range(start, end)
    ids = sorted(set(agent_ids or ()))

    wb = Workbook()
    ws = wb.active
    ws.title = "Compradores"
    _write_sheet(ws, BUYER_COLUMNS, _buyer_rows(db, company.id, since, until, ids),
                 date_cols={1}, amount_cols={10, 11})

    output = BytesIO()
    wb.save(output)
    return output.getvalue()
