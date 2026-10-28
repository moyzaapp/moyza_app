import os
import logging
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

from app.core.business_calendar import fmt_madrid
from app.services.company_service import branding_for


logger = logging.getLogger(__name__)


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


# Visita conjunta: tres columnas de firma de 150 pt con separadores de 15 pt
# (480 pt). El ancho útil de A4 con márgenes de 50 y el padding del marco es
# ~483 pt, así que no caben las columnas de 155 con separadores de 20.
JOINT_SIGNATURE_COL_WIDTHS = [150, 15, 150, 15, 150]
JOINT_SIGNATURE_LABELS = ("COMPRADOR", "AGENTE INMOBILIARIO", "AGENTE ACOMPAÑANTE")


def _signature_image(path, who):
    """Imagen de firma para la tabla, o "" (línea vacía) si no hay archivo."""
    if not path or not os.path.exists(path):
        return ""
    try:
        image = Image(path)
        image.drawHeight = 40
        image.drawWidth = 140
        return image
    except Exception as e:
        logger.error(f"Error loading {who} signature image: {e}")
        return ""


def _signature_date(value, style):
    if not value:
        return ""
    return Paragraph(f"<font size=7>Firmado digitalmente el {fmt_madrid(value)}</font>", style)


def _joint_signature_table(visit, agent, agent_name, companion_agent, body_style):
    """Tabla de firmas de tres columnas con el nombre de cada firmante.

    `agent_name` llega ya escapado (es el del texto legal). La firma de cada
    agente es su firma registrada; si el archivo no existe, la línea queda
    vacía (PDFs regenerados de visitas antiguas).
    """
    name_style = ParagraphStyle(
        "SignerNameStyle",
        parent=body_style,
        fontSize=8,
        leading=10,
        alignment=TA_CENTER,
    )

    signers = [
        (_safe_text(visit.visitor_name), visit.signature_filepath, visit.signature_captured_at, "buyer"),
        (
            agent_name,
            agent.signature_filepath if agent else None,
            agent.signature_uploaded_at if agent else None,
            "agent",
        ),
        (
            _safe_text(companion_agent.name),
            companion_agent.signature_filepath,
            companion_agent.signature_uploaded_at,
            "companion agent",
        ),
    ]

    def row(cells):
        # Columnas de firma en 0, 2 y 4; separadores vacíos en 1 y 3
        return [cells[0], "", cells[1], "", cells[2]]

    signature_data = [
        row(["", "", ""]),                                   # Espaciado
        row(list(JOINT_SIGNATURE_LABELS)),                   # Etiquetas
        row([Paragraph(f"<font size=8>{name}</font>", name_style) for name, _, _, _ in signers]),
        row([_signature_image(path, who) for _, path, _, who in signers]),
        row(["", "", ""]),                                   # Línea de firma
        row([_signature_date(date, body_style) for _, _, date, _ in signers]),
    ]

    signature_table = Table(
        signature_data,
        colWidths=JOINT_SIGNATURE_COL_WIDTHS,
        rowHeights=[15, 15, None, 50, 5, 20]
    )

    commands = [
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 4), (-1, 4), 0),
        ("GRID", (0, 0), (-1, -1), 0, colors.white),
    ]
    for col in (0, 2, 4):
        commands += [
            ("FONTNAME", (col, 1), (col, 1), "Helvetica-Bold"),
            ("ALIGN", (col, 0), (col, -1), "CENTER"),
            ("LINEABOVE", (col, 4), (col, 4), 1, colors.black),
        ]
    signature_table.setStyle(TableStyle(commands))

    return signature_table


def generate_visit_sheet(
    property_item,
    visit,
    agent,
    output_path,
    company=None,
    companion_agent=None
):
    """
    Genera la Ficha de Visita Inmobiliaria en PDF con la identidad de la
    empresa propietaria del inmueble (MOYZA o MOES PREMIUM).

    `agent` es el agente que realizó la visita: figura como emisor y firma.
    `companion_agent` (opcional) aparece en el texto legal y firma en una
    tercera columna con su firma registrada (PLAN_FIRMA_AGENTES_VISITA.md §3.4).
    Sin acompañante, la tabla de firmas es la de siempre (dos columnas).
    `company` es opcional: por defecto se usa la empresa de la propiedad.
    """

    brand = branding_for(company or getattr(property_item, "company", None))

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

    logo_path = brand.logo_fs_path
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
            f"FICHA DE VISITA INMOBILIARIA {_safe_text(brand.name)}",
            title_style
        )
    )

    elements.append(Spacer(1, 10))

    # Fecha y horas de la ficha en hora de España: en base de datos van en UTC
    # naive (PLAN_CEDER_COMPRADORES.md §4)
    visit_date = fmt_madrid(visit.created_at or datetime.utcnow(), "%d/%m/%Y")
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
        ["Teléfono de contacto:", _safe_text(f"+{visit.phone}" if visit.phone else None)],
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
        ["Honorarios en caso de compra:", _safe_text(visit.purchase_fees_display, "Según condiciones establecidas")],
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

    # Las observaciones (`visit.notes`) son internas: solo se ven en la app y
    # no salen en la ficha que firma el cliente (PLAN_CEDER_COMPRADORES.md §3)

    elements.append(Spacer(1, 20))

    # =========================
    # TEXTO LEGAL
    # =========================

    agent_name = _safe_text(agent.name) if agent else f"Agente {_safe_text(brand.name)}"
    visit_time = fmt_madrid(visit.created_at or datetime.utcnow(), "%H:%M")

    # Debe coincidir con templates/visits/preview.html (lo que se firma)
    if companion_agent:
        accompanied_by = (
            f"acompañado por los agentes de la inmobiliaria <b>{agent_name}</b> "
            f"y <b>{_safe_text(companion_agent.name)}</b>"
        )
    else:
        accompanied_by = "acompañado por el agente de la inmobiliaria"

    legal_text = f"""
    El presente documento es emitido por el asesor inmobiliario <b>{agent_name}</b>
    en calidad de representante de la agencia inmobiliaria {_safe_text(brand.name)} con domicilio fiscal en
    {_safe_text(brand.fiscal_address)}.
    <br/><br/>
    El interesado declara que ha visitado el inmueble con fecha <b>{visit_date}</b> a las <b>{visit_time}</b> horas
    con esta agencia y que no lo había visitado antes, {accompanied_by}.
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
    # FIRMAS CON FIRMA DIGITAL
    # =========================

    if companion_agent is not None:
        # Visita conjunta: COMPRADOR · AGENTE INMOBILIARIO · AGENTE ACOMPAÑANTE
        signature_table = _joint_signature_table(
            visit=visit,
            agent=agent,
            agent_name=agent_name,
            companion_agent=companion_agent,
            body_style=body_style,
        )
    else:
        signature_data = []

        # Fila 1: Espaciado
        signature_data.append(["", "", "", "", "", ""])

        # Fila 2: Etiquetas
        signature_data.append(["", "COMPRADOR", "", "", "AGENTE INMOBILIARIO", ""])

        # Fila 3: Imágenes de firma
        buyer_signature = ""
        agent_signature = ""

        # Firma del comprador
        if visit.signature_filepath and os.path.exists(visit.signature_filepath):
            try:
                buyer_signature = Image(visit.signature_filepath)
                buyer_signature.drawHeight = 40
                buyer_signature.drawWidth = 140
            except Exception as e:
                logger.error(f"Error loading buyer signature image: {e}")
                buyer_signature = ""

        # Firma del agente
        if agent and agent.signature_filepath and os.path.exists(agent.signature_filepath):
            try:
                agent_signature = Image(agent.signature_filepath)
                agent_signature.drawHeight = 40
                agent_signature.drawWidth = 140
            except Exception as e:
                logger.error(f"Error loading agent signature image: {e}")
                agent_signature = ""

        signature_data.append(["", buyer_signature, "", "", agent_signature, ""])

        # Fila 4: Línea de firma
        signature_data.append(["", "", "", "", "", ""])

        # Fila 5: Metadatos de firma
        buyer_signature_date = ""
        agent_signature_date = ""

        if visit.signature_captured_at:
            signature_date = fmt_madrid(visit.signature_captured_at)
            buyer_signature_date = Paragraph(f"<font size=7>Firmado digitalmente el {signature_date}</font>", body_style)

        if agent and agent.signature_uploaded_at:
            agent_sig_date = fmt_madrid(agent.signature_uploaded_at)
            agent_signature_date = Paragraph(f"<font size=7>Firmado digitalmente el {agent_sig_date}</font>", body_style)

        signature_data.append([
            "",
            buyer_signature_date,
            "",
            "",
            agent_signature_date,
            ""
        ])

        signature_table = Table(
            signature_data,
            colWidths=[40, 155, 40, 40, 155, 40],
            rowHeights=[15, 15, 50, 5, 20]
        )

        signature_table.setStyle(
            TableStyle([
                ("FONTNAME", (1, 1), (1, 1), "Helvetica-Bold"),
                ("FONTNAME", (4, 1), (4, 1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("ALIGN", (1, 0), (1, -1), "CENTER"),
                ("ALIGN", (4, 0), (4, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                # Línea de firma para comprador
                ("LINEABOVE", (1, 3), (1, 3), 1, colors.black),
                # Línea de firma para agente
                ("LINEABOVE", (4, 3), (4, 3), 1, colors.black),
                ("TOPPADDING", (0, 3), (-1, 3), 0),
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

    footer_text = f"""
    <b>Responsable:</b> {_safe_text(brand.legal_name)}<br/>
    <b>C.I.F.:</b> {_safe_text(brand.tax_id)}<br/>
    <b>Dirección postal:</b> {_safe_text(brand.fiscal_address)}<br/>
    <b>Tlf:</b> {_safe_text(brand.phone)}
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

    rgpd_text = f"""
    <b>AUTORIZACIÓN DE USO DE DATOS PERSONALES CONFORME AL REGLAMENTO GENERAL DE PROTECCIÓN DE DATOS (RGPD)</b>
    <br/><br/>
    {_safe_text(brand.rgpd_text)}
    <br/><br/>
    Asimismo solicito su autorización para ofrecerle productos y servicios relacionados con los solicitados y
    fidelizarle como cliente.
    <br/><br/>
    <b>{_safe_text(brand.rgpd_consent_text)}</b>
    """

    elements.append(
        Paragraph(
            rgpd_text,
            small_style
        )
    )

    elements.append(Spacer(1, 20))

    # =========================
    # PIE DE PÁGINA CON METADATOS DE VALIDACIÓN LEGAL
    # =========================

    elements.append(
        HRFlowable(
            width="100%",
            thickness=1,
            color=colors.HexColor("#CCCCCC")
        )
    )

    elements.append(Spacer(1, 10))

    validation_metadata = f"""
    <b>METADATOS DE VALIDACIÓN LEGAL</b><br/>
    Documento generado electrónicamente el {fmt_madrid(datetime.utcnow(), "%d/%m/%Y a las %H:%M")} (hora de España)<br/>
    """

    if visit.data_consent_accepted_at:
        consent_date = fmt_madrid(visit.data_consent_accepted_at)
        validation_metadata += f"Consentimiento RGPD aceptado el {consent_date}<br/>"

    if visit.signature_captured_at:
        sig_date = fmt_madrid(visit.signature_captured_at)
        validation_metadata += f"Firma digital capturada el {sig_date}<br/>"

    agent_signatures_confirmed_at = getattr(visit, "agent_signatures_confirmed_at", None)
    if agent_signatures_confirmed_at:
        confirmed_date = fmt_madrid(agent_signatures_confirmed_at)
        validation_metadata += f"Firmas de agentes confirmadas el {confirmed_date}<br/>"

    if visit.data_consent_ip:
        # Ofuscar IP por privacidad (mostrar solo primeros 2 octetos)
        ip_parts = visit.data_consent_ip.split('.')
        if len(ip_parts) == 4:
            ip_masked = f"{ip_parts[0]}.{ip_parts[1]}.xxx.xxx"
            validation_metadata += f"IP de validación: {ip_masked}<br/>"

    validation_metadata += f"ID de documento: {_safe_text(brand.document_id(visit.id, property_item.id))}<br/>"

    validation_style = ParagraphStyle(
        "ValidationStyle",
        parent=styles["BodyText"],
        fontSize=7,
        leading=10,
        textColor=colors.HexColor("#666666"),
        alignment=TA_LEFT,
    )

    elements.append(Paragraph(validation_metadata, validation_style))

    # =========================
    # BUILD PDF
    # =========================

    doc.build(elements)

    return output_path
