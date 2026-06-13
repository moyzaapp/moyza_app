import os
from datetime import datetime

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
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus.flowables import HRFlowable

from reportlab.lib.units import cm
from xml.sax.saxutils import escape


def _safe_text(value, default=""):
    """Escapa texto dinámico antes de pasarlo a Paragraph de ReportLab."""
    if value is None or value == "":
        return default

    return escape(str(value))


def _first_existing_path(*paths):
    for path in paths:
        if os.path.exists(path):
            return path

    return None


def generate_visit_sheet(
    property_item,
    visit,
    agent,
    output_path
):
    """
    Genera la Ficha de Visita Inmobiliaria en PDF según el formato oficial de MOYZA
    """

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=50,
        leftMargin=50,
        topMargin=30,
        bottomMargin=30
    )

    styles = getSampleStyleSheet()

    elements = []

    # =========================
    # CUSTOM STYLES
    # =========================

    title_style = ParagraphStyle(
        "TitleStyle",
        parent=styles["Heading1"],
        fontSize=16,
        leading=20,
        textColor=colors.HexColor("#000000"),
        alignment=TA_CENTER,
        spaceAfter=10,
        fontName="Helvetica-Bold"
    )

    section_style = ParagraphStyle(
        "SectionStyle",
        parent=styles["Heading2"],
        fontSize=11,
        textColor=colors.HexColor("#000000"),
        fontName="Helvetica-Bold",
        spaceAfter=5,
        spaceBefore=10,
    )

    body_style = ParagraphStyle(
        "BodyStyle",
        parent=styles["BodyText"],
        fontSize=9,
        leading=14,
        alignment=TA_JUSTIFY,
    )

    small_style = ParagraphStyle(
        "SmallStyle",
        parent=styles["BodyText"],
        fontSize=7,
        leading=10,
        alignment=TA_LEFT,
    )

    # =========================
    # HEADER CON LOGO
    # =========================

    logo_path = _first_existing_path(
        "app/static/logo_moyza.png",
        "backend/app/static/logo_moyza.png"
    )
    if logo_path:
        logo = Image(logo_path)
        logo_height = 2 * cm
        logo_width = logo.drawWidth * (logo_height / logo.drawHeight)
        logo.drawWidth = logo_width
        logo.drawHeight = logo_height
        logo.hAlign = "CENTER"
        elements.append(logo)
        elements.append(Spacer(1, 5))

    # =========================
    # TÍTULO
    # =========================

    elements.append(
        Paragraph(
            "FICHA DE VISITA INMOBILIARIA MOYZA",
            title_style
        )
    )

    elements.append(Spacer(1, 10))

    # Fecha
    visit_date = visit.created_at.strftime("%d/%m/%Y") if visit.created_at else datetime.now().strftime("%d/%m/%Y")
    elements.append(
        Paragraph(
            f"<b>FECHA:</b> {visit_date}",
            body_style
        )
    )

    elements.append(Spacer(1, 5))

    # Dirección del inmueble
    elements.append(
        Paragraph(
            f"<b>DIRECCIÓN DEL INMUEBLE VISITADO:</b> {_safe_text(property_item.address)}",
            body_style
        )
    )

    elements.append(Spacer(1, 15))

    # =========================
    # DATOS DEL COMPRADOR
    # =========================

    elements.append(
        Paragraph(
            "DATOS DEL COMPRADOR",
            section_style
        )
    )

    buyer_data = [
        ["Nombre:", _safe_text(visit.visitor_name)],
        ["DNI:", _safe_text(visit.dni)],
        ["Teléfono de contacto:", _safe_text(visit.phone)],
        ["E-mail:", _safe_text(visit.email)],
    ]

    buyer_table = Table(
        buyer_data,
        colWidths=[150, 320]
    )

    buyer_table.setStyle(
        TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ])
    )

    elements.append(buyer_table)

    elements.append(Spacer(1, 15))

    # =========================
    # DATOS DEL INMUEBLE VISITADO
    # =========================

    elements.append(
        Paragraph(
            "DATOS DEL INMUEBLE VISITADO",
            section_style
        )
    )

    property_data = [
        ["Tipo de vivienda:", _safe_text(property_item.title)],
        ["Precio de venta:", f"€{property_item.price:,.2f}" if property_item.price else "No especificado"],
        ["Honorarios en caso de compra:", "Según condiciones establecidas"],
    ]

    property_table = Table(
        property_data,
        colWidths=[150, 320]
    )

    property_table.setStyle(
        TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ])
    )

    elements.append(property_table)

    elements.append(Spacer(1, 15))

    # =========================
    # FEEDBACK DE LA VISITA (NUEVO)
    # =========================

    elements.append(
        Paragraph(
            "FEEDBACK DE LA VISITA",
            section_style
        )
    )

    feedback_data = [
        ["Nivel de interés:", f"{visit.interest_level}/5" if visit.interest_level else "No especificado"],
        ["Feedback precio:", _safe_text(visit.price_feedback, "No especificado")],
        ["Feedback ubicación:", _safe_text(visit.location_feedback, "No especificado")],
        ["Feedback estado:", _safe_text(visit.condition_feedback, "No especificado")],
        ["Feedback luminosidad:", _safe_text(visit.lighting_feedback, "No especificado")],
        ["Ascensor:", _safe_text(visit.elevator_feedback, "No especificado")],
        ["Garaje:", _safe_text(visit.garage_feedback, "No especificado")],
    ]

    feedback_table = Table(
        feedback_data,
        colWidths=[150, 320]
    )

    feedback_table.setStyle(
        TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#DDDDDD")),
        ])
    )

    elements.append(feedback_table)

    if visit.notes:
        elements.append(Spacer(1, 10))
        elements.append(
            Paragraph(
                f"<b>Observaciones:</b> {_safe_text(visit.notes)}",
                body_style
            )
        )

    elements.append(Spacer(1, 20))

    # =========================
    # TEXTO LEGAL
    # =========================

    agent_name = agent.name if agent else "Agente MOYZA"
    visit_time = visit.created_at.strftime("%H:%M") if visit.created_at else datetime.now().strftime("%H:%M")

    legal_text = f"""
    El presente documento es emitido por el asesor inmobiliario <b>{agent_name}</b>
    en calidad de representante de la agencia inmobiliaria MOYZA con domicilio fiscal en
    Avda. Doctor Eduardo García Triviño López 9, 23009 (Jaén).
    <br/><br/>
    El interesado declara que ha visitado el inmueble con fecha <b>{visit_date}</b> a las <b>{visit_time}</b> horas
    con esta agencia y que no lo había visitado antes, acompañado por el agente de la inmobiliaria.
    Asimismo, reconoce que ha conocido dicho inmueble gracias a la intermediación de la empresa inmobiliaria mencionada,
    la cual actúa como mediadora en la operación de compraventa. Durante dicha visita "El agente" ha proporcionado
    información fidedigna y detalles generales sobre el inmueble, condiciones de adquisición, resolviendo todas
    las dudas y consultas presentadas por el interesado.
    <br/><br/>
    La visita del inmueble no tiene ningún costo ni honorario para el mismo, pero si el cliente desea comprarla
    (directamente o a través de familiares, otras inmobiliarias, corredores o empresas relacionadas) se compromete
    a realizarlo a través de esta agencia y reconoce los honorarios anteriormente reseñados. Los honorarios se
    abonarán de la siguiente manera: El 50%+IVA a la firma del contrato de compraventa y el 50%+IVA a la firma
    de Escritura Pública de Compraventa.
    <br/><br/>
    En caso de interés por parte de "El interesado", en la adquisición del inmueble, este podrá llevar a cabo
    negociaciones directamente con el propietario, siempre bajo la mediación y asesoramiento de la Inmobiliaria
    a través del personal correspondiente. Si "El interesado" decide presentar una oferta formal para la adquisición
    del inmueble, se compromete a gestionar y comunicar dicha intención a través de La Inmobiliaria, reconociendo
    la relevancia de su intervención en el proceso de visita e información proporcionada.
    <br/><br/>
    En caso de incumplimiento, acepta abonar a la inmobiliaria los honorarios establecidos por su intermediación.
    """

    elements.append(
        Paragraph(
            legal_text,
            body_style
        )
    )

    elements.append(Spacer(1, 25))

    # =========================
    # FIRMAS
    # =========================

    # Tabla con 6 columnas para tener líneas de firma separadas y centradas
    signature_data = [
        ["", "", "", "", "", ""],
        ["", "COMPRADOR", "", "", "AGENTE INMOBILIARIO", ""],
        ["", "", "", "", "", ""],
        ["", "", "", "", "", ""],
    ]

    signature_table = Table(
        signature_data,
        colWidths=[40, 155, 40, 40, 155, 40],
        rowHeights=[15, 15, 35, 5]
    )

    signature_table.setStyle(
        TableStyle([
            ("FONTNAME", (1, 0), (1, 0), "Helvetica"),
            ("FONTNAME", (4, 0), (4, 0), "Helvetica"),
            ("FONTNAME", (1, 1), (1, 1), "Helvetica-Bold"),
            ("FONTNAME", (4, 1), (4, 1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("ALIGN", (1, 0), (1, 1), "CENTER"),
            ("ALIGN", (4, 0), (4, 1), "CENTER"),
            # Línea corta solo para el comprador (columna 1, fila 3)
            ("LINEABOVE", (1, 3), (1, 3), 1, colors.black),
            # Línea corta solo para el agente (columna 4, fila 3)
            ("LINEABOVE", (4, 3), (4, 3), 1, colors.black),
            ("TOPPADDING", (0, 3), (-1, 3), 0),
            # Sin bordes visibles
            ("GRID", (0, 0), (-1, -1), 0, colors.white),
        ])
    )

    elements.append(signature_table)

    elements.append(Spacer(1, 20))

    # =========================
    # FOOTER - DATOS DE CONTACTO
    # =========================

    elements.append(
        HRFlowable(
            width="100%",
            thickness=1,
            color=colors.HexColor("#333333")
        )
    )

    elements.append(Spacer(1, 5))

    footer_text = """
    <b>Responsable:</b> Moyza 2012 S.L.<br/>
    <b>C.I.F.:</b> B16914012<br/>
    <b>Dirección postal:</b> Avda. Doctor Eduardo García Triviño López 9, 23009 (Jaén)<br/>
    <b>Tlf:</b> 642 497 955 / 953 940 956
    """

    elements.append(
        Paragraph(
            footer_text,
            small_style
        )
    )

    elements.append(Spacer(1, 10))

    # =========================
    # AUTORIZACIÓN RGPD
    # =========================

    rgpd_text = """
    <b>AUTORIZACIÓN DE USO DE DATOS PERSONALES CONFORME AL REGLAMENTO GENERAL DE PROTECCIÓN DE DATOS (RGPD)</b>
    <br/><br/>
    En nombre de la empresa Inmobiliaria MOYZA tratamos la información que nos facilita con el fin de prestarles
    el servicio solicitado y realizar la facturación del mismo. Los datos proporcionados se conservarán mientras
    se mantenga la relación comercial o durante los meses necesarios para cumplir con las obligaciones legales.
    Los datos no se cederán a terceros salvo en los casos en que exista una obligación legal. Usted tiene derecho
    a obtener confirmación sobre si en Inmobiliaria MOYZA estamos tratando sus datos personales, por tanto tiene
    derecho a acceder a sus datos personales, rectificar los datos inexactos o solicitar su supresión cuando los
    datos ya no sean necesarios.
    <br/><br/>
    Asimismo solicito su autorización para ofrecerle productos y servicios relacionados con los solicitados y
    fidelizarle como cliente.
    <br/><br/>
    <b>Autorizo a que mis datos sean tratados por Inmobiliaria MOYZA hasta que finalice la operación o se
    comunique por mi parte rescindir la misma.</b>
    """

    elements.append(
        Paragraph(
            rgpd_text,
            small_style
        )
    )

    # =========================
    # BUILD PDF
    # =========================

    doc.build(elements)

    return output_path
