from pathlib import Path

from reportlab.platypus import SimpleDocTemplate
from reportlab.platypus import Paragraph
from reportlab.platypus import Spacer

from reportlab.lib.styles import getSampleStyleSheet


def generate_property_report(
    property_item,
    report_data,
    output_path
):

    doc = SimpleDocTemplate(output_path)

    styles = getSampleStyleSheet()

    elements = []

    elements.append(
        Paragraph(
            f"Informe Comercial - {property_item.title}",
            styles["Title"]
        )
    )

    elements.append(Spacer(1, 20))

    elements.append(
        Paragraph(
            "ESTADO DE COMERCIALIZACIÓN",
            styles["Heading2"]
        )
    )

    elements.append(
        Paragraph(
            f"Precio actual: {property_item.price}",
            styles["BodyText"]
        )
    )

    elements.append(
        Paragraph(
            f"Días en mercado: {report_data['days_on_market']}",
            styles["BodyText"]
        )
    )

    elements.append(
        Paragraph(
            f"Bajadas de precio: {report_data['reductions']}",
            styles["BodyText"]
        )
    )

    elements.append(Spacer(1, 20))

    elements.append(
        Paragraph(
            "INTERÉS GENERADO",
            styles["Heading2"]
        )
    )

    elements.append(
        Paragraph(
            f"Consultas: {report_data['consultas']}",
            styles["BodyText"]
        )
    )

    elements.append(
        Paragraph(
            f"Visitas: {report_data['visitas']}",
            styles["BodyText"]
        )
    )

    elements.append(
        Paragraph(
            f"Interesados: {report_data['interesados']}",
            styles["BodyText"]
        )
    )

    elements.append(
        Paragraph(
            f"Ofertas: {report_data['ofertas']}",
            styles["BodyText"]
        )
    )

    doc.build(elements)

    return output_path