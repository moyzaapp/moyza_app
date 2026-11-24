"""Excel de compradores para administración (PLAN_EXPORT_EXCEL_COMPRADORES.md).

`build_buyers_workbook` devuelve un `.xlsx` con tres hojas sobre la empresa
dada y un rango de días de Madrid (inclusivo):

- «Resumen»: totales y recuentos por fuente, agente y etapa actual.
- «Compradores»: compradores dados de alta en el periodo, con su perfil.
- «Alertas»: alertas creadas en el periodo, con etapa, estado y gestiones.

Es un documento de trabajo: cabecera en negrita, fila fija, autofiltro y
fechas en hora de Madrid. Sin fórmulas ni estilos corporativos.
"""
from collections import Counter
from datetime import date
from datetime import datetime
from datetime import time
from datetime import timedelta
from decimal import Decimal
from io import BytesIO

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Font
from openpyxl.styles import PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import func
from sqlalchemy.orm import Session
from sqlalchemy.orm import selectinload

from app.core.address import street_only
from app.core.business_calendar import to_madrid
from app.core.business_calendar import to_utc
from app.core.constants import AlertOrigin
from app.models.buyer import Buyer
from app.models.property_alert import PropertyAlert
from app.models.user import User
from app.services import alert_view
from app.services.alert_duplicate_service import STATUS_LABELS
from app.services.buyer_matching import profile_types

DATETIME_FORMAT = "dd/mm/yyyy hh:mm"
AMOUNT_FORMAT = "#,##0"
HEADER_FONT = Font(bold=True)
HEADER_FILL = PatternFill(fill_type="solid", start_color="FFE5E7EB", end_color="FFE5E7EB")

ORIGIN_LABELS = {
    AlertOrigin.PROPERTY: "Con referencia",
    AlertOrigin.SEARCH: "Búsqueda general",
}
NO_STAGE_LABEL = "Sin iniciar"
NO_SOURCE_LABEL = "Sin fuente"
NO_AGENT_LABEL = "Sin asignar"

# (cabecera, ancho) de cada hoja
SUMMARY_COLUMNS = [("Concepto", 34), ("Valor", 40)]
BUYER_COLUMNS = [
    ("Fecha de alta", 17), ("Nombre", 28), ("Teléfono", 16), ("Email", 28),
    ("Creado por", 22), ("Alertas", 9), ("Última alerta", 17), ("Tipo de negocio", 15),
    ("Tipo de inmueble", 22), ("Provincia", 14), ("Zonas/ciudades", 32),
    ("Presupuesto mín.", 16), ("Presupuesto máx.", 16), ("Notas", 40),
]
ALERT_COLUMNS = [
    ("Fecha", 17), ("Comprador", 28), ("Teléfono", 16), ("Email", 28), ("Origen", 17),
    ("Referencia", 14), ("Propiedad", 36), ("Fuente", 18), ("Agente", 22),
    ("Etapa actual", 20), ("Estado", 13), ("Última gestión", 17), ("Nº gestiones", 12),
    ("Fecha de cierre", 17), ("Cedida", 9),
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


def _user_names(db: Session, user_ids) -> dict:
    """{user_id: nombre (o email)} de quienes crearon los compradores."""
    ids = {uid for uid in user_ids if uid}
    if not ids:
        return {}
    rows = db.query(User.id, User.full_name, User.email).filter(User.id.in_(ids)).all()
    return {row.id: (row.full_name or row.email or "") for row in rows}


def _alert_counts(db: Session, company_id: int, buyer_ids) -> dict:
    """{buyer_id: (nº de alertas, fecha de la última)} en la empresa, de cualquier fecha."""
    if not buyer_ids:
        return {}
    rows = (
        db.query(PropertyAlert.buyer_id, func.count(PropertyAlert.id), func.max(PropertyAlert.created_at))
        .filter(PropertyAlert.company_id == company_id, PropertyAlert.buyer_id.in_(buyer_ids))
        .group_by(PropertyAlert.buyer_id)
        .all()
    )
    return {buyer_id: (count, last) for buyer_id, count, last in rows}


def _property_text(prop) -> str:
    """Título y calle de la propiedad («Piso en el Centro · Calle Mayor 3»)."""
    if prop is None:
        return ""
    street = street_only(prop.address)
    return " · ".join(part for part in (prop.title, street) if part)


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


def _buyer_rows(db: Session, company_id: int, since: datetime, until: datetime) -> list:
    buyers = (
        db.query(Buyer)
        .options(selectinload(Buyer.search_criteria))
        .filter(Buyer.company_id == company_id, Buyer.created_at >= since, Buyer.created_at < until)
        .order_by(Buyer.created_at.asc(), Buyer.id.asc())
        .all()
    )
    counts = _alert_counts(db, company_id, [b.id for b in buyers])
    creators = _user_names(db, [b.created_by for b in buyers])
    rows = []
    for buyer in buyers:
        criteria = buyer.search_criteria
        count, last = counts.get(buyer.id, (0, None))
        rows.append([
            _madrid(buyer.created_at),
            buyer.name,
            buyer.phone or "",
            buyer.email or "",
            creators.get(buyer.created_by, ""),
            count,
            _madrid(last),
            (criteria.business_type or "") if criteria else "",
            ", ".join(profile_types(criteria)),
            (criteria.province or "") if criteria else "",
            _join(criteria.cities, criteria.zones) if criteria else "",
            _amount(criteria.min_price) if criteria else None,
            _amount(criteria.max_price) if criteria else None,
            buyer.notes or "",
        ])
    return rows


def _alerts(db: Session, company_id: int, since: datetime, until: datetime) -> list:
    return (
        db.query(PropertyAlert)
        .options(
            selectinload(PropertyAlert.buyer),
            selectinload(PropertyAlert.property),
            selectinload(PropertyAlert.agent),
            selectinload(PropertyAlert.follow_ups),
        )
        .filter(
            PropertyAlert.company_id == company_id,
            PropertyAlert.created_at >= since,
            PropertyAlert.created_at < until,
        )
        .order_by(PropertyAlert.created_at.asc(), PropertyAlert.id.asc())
        .all()
    )


def _alert_row(alert, stage_label: str) -> list:
    real = alert_view.real_follow_ups_since(alert.follow_ups, None)
    last_managed = max((f.created_at for f in real if f.created_at is not None), default=None)
    buyer = alert.buyer
    prop = alert.property
    return [
        _madrid(alert.created_at),
        (buyer.name if buyer else None) or alert.lead_name or "",
        alert.lead_phone or (buyer.phone if buyer else None) or "",
        alert.lead_email or (buyer.email if buyer else None) or "",
        ORIGIN_LABELS.get(alert.origin, alert.origin or ""),
        (prop.referencia or "") if prop else "",
        _property_text(prop),
        (alert.source or "").strip(),
        alert.agent.name if alert.agent else NO_AGENT_LABEL,
        stage_label,
        STATUS_LABELS.get(alert.status, alert.status or ""),
        _madrid(last_managed),
        len(real),
        _madrid(alert.completed_at),
        "Sí" if alert.ceded_at else "No",
    ]


def _summary_rows(company, start: date, end: date, buyers_total: int, alerts, stages: dict) -> list:
    origins = Counter(alert.origin for alert in alerts)
    sources = Counter((alert.source or "").strip() or NO_SOURCE_LABEL for alert in alerts)
    agents = Counter(alert.agent.name if alert.agent else NO_AGENT_LABEL for alert in alerts)
    stage_counts = Counter(stages[alert.id] for alert in alerts)

    rows = [
        ["Empresa", company.name],
        ["Periodo", f"{start.strftime('%d/%m/%Y')} – {end.strftime('%d/%m/%Y')}"],
        ["Generado el", to_madrid(datetime.utcnow()).strftime("%d/%m/%Y %H:%M")],
        [None, None],
        ["Compradores nuevos", buyers_total],
        ["Alertas nuevas", len(alerts)],
        ["Alertas con referencia", origins.get(AlertOrigin.PROPERTY, 0)],
        ["Alertas de búsqueda general", origins.get(AlertOrigin.SEARCH, 0)],
    ]
    for title, counter in (
        ("Alertas por fuente", sources),
        ("Alertas por agente", agents),
        ("Alertas por etapa actual", stage_counts),
    ):
        rows.append([None, None])
        rows.append([title, None])
        # Por cantidad desc. y, a igualdad, por nombre
        for label, count in sorted(counter.items(), key=lambda item: (-item[1], item[0])):
            rows.append([label, count])
    return rows


def build_buyers_workbook(db: Session, company, start: date, end: date) -> bytes:
    """Libro `.xlsx` de compradores y alertas de `company` dados de alta entre
    `start` y `end` (días de Madrid, ambos incluidos)."""
    since, until = utc_range(start, end)

    buyer_rows = _buyer_rows(db, company.id, since, until)
    alerts = _alerts(db, company.id, since, until)
    # Etapa con todo el historial, como la ve el admin en el listado
    stages = {}
    for alert in alerts:
        stage = alert_view.current_stage(alert.follow_ups, None)
        stages[alert.id] = stage["label"] if stage else NO_STAGE_LABEL

    wb = Workbook()
    summary = wb.active
    summary.title = "Resumen"
    summary.append([header for header, _ in SUMMARY_COLUMNS])
    for cell in summary[1]:
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
    for index, (_, width) in enumerate(SUMMARY_COLUMNS, start=1):
        summary.column_dimensions[get_column_letter(index)].width = width
    for row in _summary_rows(company, start, end, len(buyer_rows), alerts, stages):
        _append(summary, row)
        # Títulos de bloque en negrita
        if row[0] and row[1] is None:
            summary.cell(row=summary.max_row, column=1).font = HEADER_FONT
    summary.freeze_panes = "A2"

    _write_sheet(wb.create_sheet("Compradores"), BUYER_COLUMNS, buyer_rows,
                 date_cols={1, 7}, amount_cols={12, 13})
    _write_sheet(wb.create_sheet("Alertas"), ALERT_COLUMNS,
                 [_alert_row(alert, stages[alert.id]) for alert in alerts],
                 date_cols={1, 12, 14})

    output = BytesIO()
    wb.save(output)
    return output.getvalue()
