import os

from reportlab.platypus import (
    SimpleDocTemplate,
    Image,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import A4
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus.flowables import HRFlowable

from reportlab.platypus import PageBreak

from reportlab.lib.units import cm
from xml.sax.saxutils import escape


def _safe_text(value, default="No disponible"):
    """Escapa texto dinámico antes de pasarlo a Paragraph de ReportLab."""
    if value is None:
        return default

    return escape(str(value))


def _money(value, default="$0.00"):
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return default


def _first_existing_path(*paths):
    for path in paths:
        if os.path.exists(path):
            return path

    return None


def generate_property_report(
    property_item,
    report_data,
    output_path
):

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=40,
        leftMargin=40,
        topMargin=40,
        bottomMargin=40
    )

    styles = getSampleStyleSheet()

    elements = []

    # =========================
    # CUSTOM STYLES
    # =========================

    title_style = ParagraphStyle(
        "TitleStyle",
        parent=styles["Heading1"],
        fontSize=22,
        leading=28,
        textColor=colors.HexColor("#444444"),
        alignment=TA_CENTER,
        spaceAfter=20,
    )

    section_style = ParagraphStyle(
        "SectionStyle",
        parent=styles["Heading2"],
        fontSize=14,
        # textColor=colors.white,
        # backColor=colors.HexColor("#444444"),
        textColor=colors.HexColor("#333333"),
        leftIndent=10,
        spaceBefore=20,
        spaceAfter=10,
        leading=20,
    )

    body_style = ParagraphStyle(
        "BodyStyle",
        parent=styles["BodyText"],
        fontSize=11,
        leading=18,
    )

    highlight_style = ParagraphStyle(
        "HighlightStyle",
        parent=styles["BodyText"],
        fontSize=12,
        leading=20,
        textColor=colors.HexColor("#0B6E4F"),
    )

    # =========================
    # HEADER
    # =========================

    logo_path = _first_existing_path(
        "app/static/logo_moyza.png",
        "backend/app/static/logo_moyza.png"
    )
    if logo_path:
        logo = Image(logo_path)
        logo_height = 2.5 * cm
        logo_width = logo.drawWidth * (logo_height / logo.drawHeight)
        logo.drawWidth = logo_width
        logo.drawHeight = logo_height
        logo.hAlign = "LEFT"
        elements.append(logo)
        elements.append(Spacer(1, 8))

    elements.append(
        Paragraph(
            "INFORME DE SEGUIMIENTO COMERCIAL",
            title_style
        )
    )

    elements.append(
        Paragraph(
            f"""
            <b>Propiedad:</b> {property_item.title}<br/>
            <b>Dirección:</b> {property_item.address}<br/>
            <b>Profesional:</b> {property_item.agent.name}<br/>
            <b>Fecha:</b> {property_item.market_entry_date.strftime("%d/%m/%Y")}
            """,
            body_style
        )
    )

    elements.append(Spacer(1, 15))

    elements.append(
        HRFlowable(
            width="100%",
            thickness=0.7,
            color=colors.HexColor("#D3D3D3")
        )
    )

    # =========================
    # ESTADO DE COMERCIALIZACIÓN
    # =========================

    elements.append(
        Paragraph(
            "ESTADO DE COMERCIALIZACIÓN",
            section_style
        )
    )

    commercialization_data = [
        ["Concepto", "Valor"],
        ["Precio actual", f"${property_item.price}"],
        ["Días en mercado", report_data["days_on_market"]],
        ["Bajadas de precio", report_data["reductions"]],
        ["Tipo de promoción", "tipo promocionnnn"],
    ]

    table = Table(
        commercialization_data,
        colWidths=[220, 250]
    )

    table.setStyle(
        TableStyle([
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 10),

            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#222222")),

            ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor("#BDBDBD")),

            ("GRID", (0, 1), (-1, -1), 0.5, colors.HexColor("#DDDDDD")),

            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 1), (-1, -1), 10),

            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 8),

            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F5F5F5")),
        ])
    )

    elements.append(table)

    # =========================
    # INTERÉS GENERADO
    # =========================

    elements.append(
        Paragraph(
            "INTERÉS GENERADO",
            section_style
        )
    )

    interest_data = [
        ["Métrica", "Cantidad"],
        ["Consultas", report_data["consultas"]],
        ["Visitas", report_data["visitas"]],
        ["Interesados", report_data["interesados"]],
        ["Ofertas", report_data["ofertas"]],
    ]

    interest_table = Table(
        interest_data,
        colWidths=[220, 250]
    )

    interest_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0B6E4F")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),

            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),

            ("GRID", (0, 0), (-1, -1), 1, colors.lightgrey),

            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [
                colors.HexColor("#F6FFF8"),
                colors.whitesmoke
            ]),
        ])
    )

    elements.append(interest_table)

    # =========================
    # IA - VALORACIÓN
    # =========================

    elements.append(
        Paragraph(
            "VALORACIÓN COMERCIAL (IA)",
            section_style
        )
    )

    ai_valuation = report_data.get("ai_valuation")

    if ai_valuation:
        price_range = ai_valuation.get('price_range') or {}

        # Tabla de valuación
        valuation_data = [
            ["Concepto", "Valor"],
            ["Valor estimado de mercado", _money(ai_valuation.get('estimated_value'))],
            ["Rango de precio sugerido",
             f"{_money(price_range.get('min'))} - "
             f"{_money(price_range.get('max'))}"],
            ["Nivel de confianza", str(ai_valuation.get('confidence', 'N/A')).capitalize()],
        ]

        valuation_table = Table(
            valuation_data,
            colWidths=[220, 250]
        )

        valuation_table.setStyle(
            TableStyle([
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 10),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#222222")),
                ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor("#BDBDBD")),
                ("GRID", (0, 1), (-1, -1), 0.5, colors.HexColor("#DDDDDD")),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 1), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F5F5F5")),
            ])
        )

        elements.append(valuation_table)
        elements.append(Spacer(1, 10))

        # Análisis del valor
        elements.append(
            Paragraph(
                "<b>Análisis del Tasador IA:</b>",
                body_style
            )
        )

        elements.append(
            Paragraph(
                _safe_text(ai_valuation.get('reasoning')),
                body_style
            )
        )
    else:
        elements.append(
            Paragraph(
                "El análisis de IA no está disponible para este reporte. "
                "Verifique la configuración de la API de OpenAI.",
                body_style
            )
        )

    # =========================
    # IA - OBSERVACIONES
    # =========================

    elements.append(
        Paragraph(
            "OBSERVACIONES Y RECOMENDACIONES",
            section_style
        )
    )

    ai_observations = report_data.get("ai_observations")

    if ai_observations:
        # Análisis de mercado
        elements.append(
            Paragraph(
                "<b>Análisis de Mercado:</b>",
                body_style
            )
        )

        elements.append(
            Paragraph(
                _safe_text(ai_observations.get('market_analysis')),
                body_style
            )
        )

        elements.append(Spacer(1, 10))

        # Nivel de riesgo
        risk_level = str(ai_observations.get('risk_level', 'N/A')).upper()
        risk_colors = {
            'BAJO': "#0B6E4F",
            'MEDIO': "#FFA500",
            'ALTO': "#DC143C"
        }
        risk_color = risk_colors.get(risk_level, "#808080")

        elements.append(
            Paragraph(
                f"<b>Nivel de Riesgo Comercial:</b> <font color='{risk_color}'>{_safe_text(risk_level)}</font>",
                body_style
            )
        )

        elements.append(Spacer(1, 10))

        # Recomendaciones
        elements.append(
            Paragraph(
                "<b>Recomendaciones Estratégicas:</b>",
                body_style
            )
        )

        recommendations = ai_observations.get('recommendations', [])
        if not isinstance(recommendations, list):
            recommendations = [recommendations]

        for idx, rec in enumerate(recommendations, 1):
            elements.append(
                Paragraph(
                    f"{idx}. {_safe_text(rec)}",
                    body_style
                )
            )

        elements.append(Spacer(1, 10))

        # Oportunidades
        elements.append(
            Paragraph(
                "<b>Oportunidades Identificadas:</b>",
                body_style
            )
        )

        elements.append(
            Paragraph(
                _safe_text(ai_observations.get('opportunities')),
                body_style
            )
        )
    else:
        elements.append(
            Paragraph(
                "Las observaciones de IA no están disponibles para este reporte. "
                "Verifique la configuración de la API de OpenAI.",
                body_style
            )
        )

    # =========================
    # FOOTER
    # =========================

    elements.append(Spacer(1, 40))

    elements.append(
        HRFlowable(
            width="100%",
            thickness=0.7,
            color=colors.HexColor("#D3D3D3")
        )
    )

    elements.append(Spacer(1, 10))

    elements.append(
        Paragraph(
            "Documento generado automáticamente por MOYZA",
            ParagraphStyle(
                "Footer",
                parent=styles["BodyText"],
                fontSize=9,
                alignment=TA_CENTER,
                textColor=colors.grey
            )
        )
    )

    doc.build(elements)

    return output_path
