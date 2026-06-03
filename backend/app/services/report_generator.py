from reportlab.platypus import (
    SimpleDocTemplate,
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

    elements.append(
        Paragraph(
            """
            Aquí irá posteriormente el análisis generado por IA
            sobre el valor comercial estimado de la propiedad,
            comparativas de mercado y recomendaciones estratégicas.
            """,
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

    elements.append(
        Paragraph(
            """
            Aquí se agregarán observaciones automáticas generadas
            mediante IA según el comportamiento del mercado,
            interés generado y tendencias inmobiliarias.
            """,
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