from fastapi import APIRouter
from fastapi import Request
from fastapi import Depends
from fastapi import UploadFile
from fastapi import File
from fastapi import Form

from fastapi.responses import HTMLResponse
from fastapi.responses import RedirectResponse
from fastapi.responses import FileResponse

from fastapi.templating import Jinja2Templates

from sqlalchemy.orm import Session

from uuid import uuid4

import shutil
import os

from app.db.deps import get_db

from app.models.report import Report
from app.models.property import Property
from app.services.whatsapp import send_report
from app.web.utils.flash import set_flash


router = APIRouter()

templates = Jinja2Templates(
    directory="app/web/templates"
)

@router.get("/reports", response_class=HTMLResponse)
async def reports_page(
    request: Request,
    db: Session = Depends(get_db)
):

    reports = db.query(Report).all()

    properties = db.query(Property).all()

    current_user = request.state.user

    return templates.TemplateResponse(
        request=request,
        name="reports/home.html",
        context={
            "request": request,
            "reports": reports,
            "properties": properties,
            "current_user": current_user
        }
    )


@router.post("/reports/upload")
async def upload_report(
    request: Request,
    property_id: int = Form(...),
    report_type: str = Form(...),
    notes: str = Form(...),
    report_file: UploadFile = File(...),
    send_whatsapp: str = Form(None),
    db: Session = Depends(get_db)
):

    current_user = request.state.user

    extension = report_file.filename.split(".")[-1]

    unique_filename = f"{uuid4()}.{extension}"

    file_path = f"storage/reports/{unique_filename}"

    os.makedirs(
        "storage/reports",
        exist_ok=True
    )

    with open(file_path, "wb") as buffer:

        shutil.copyfileobj(
            report_file.file,
            buffer
        )

    report = Report(
        property_id=property_id,
        uploaded_by=current_user.id,
        report_type=report_type,
        filename=report_file.filename,
        filepath=file_path,
        notes=notes
    )

    db.add(report)

    db.commit()

    response = RedirectResponse(url="/reports", status_code=302)

    if send_whatsapp:
        try:
            property_item = db.query(Property).filter(Property.id == property_id).first()

            if not property_item or not property_item.client or not property_item.client.phone:
                set_flash(response, "warning", "Informe subido, pero no se pudo enviar por WhatsApp: cliente sin teléfono")
                return response

            client_phone = property_item.client.phone

            print(report.filepath, report.filename, client_phone)

            file_url = f"https://evomoyza.duckdns.org/{report.filepath}"

            send_report(
                phone=client_phone,
                file_url=file_url,
                caption="Reporte generado automáticamente"
            )

            set_flash(response, "success", "Informe subido y enviado por WhatsApp correctamente")
        except Exception as e:
            print(f"Error enviando WhatsApp: {e}")
            set_flash(response, "warning", "Informe subido, pero ocurrió un error al enviar por WhatsApp")
    else:
        set_flash(response, "success", "Informe subido correctamente")

    return response

@router.get("/reports/download/{report_id}")
async def download_report(
    report_id: int,
    db: Session = Depends(get_db)
):

    report = db.query(Report).filter(
        Report.id == report_id
    ).first()

    if not report:
        response = RedirectResponse(url="/reports", status_code=302)
        set_flash(response, "error", "Informe no encontrado")
        return response

    if not os.path.exists(report.filepath):
        response = RedirectResponse(url="/reports", status_code=302)
        set_flash(response, "error", "Archivo del informe no encontrado en el servidor")
        return response

    return FileResponse(
        path=report.filepath,
        filename=report.filename,
        media_type="application/octet-stream"
    )

@router.post("/reports/delete/")
async def delete_report(
    request: Request,
    report_id: int = Form(...),
    db: Session = Depends(get_db)
):

    report = db.query(Report).filter(
        Report.id == report_id
    ).first()

    response = RedirectResponse(url="/reports", status_code=302)

    if not report:
        set_flash(response, "error", "Informe no encontrado")
        return response

    try:
        if os.path.exists(report.filepath):
            os.remove(report.filepath)

        db.delete(report)
        db.commit()

        set_flash(response, "success", "Informe eliminado correctamente")
    except Exception as e:
        print(f"Error eliminando informe: {e}")
        set_flash(response, "error", "Ocurrió un error al eliminar el informe")

    return response


@router.post("/reports/{report_id}/send-whatsapp")
async def send_report_whatsapp(
    request: Request,
    report_id: int,
    db: Session = Depends(get_db)
):

    redirect_url = request.headers.get("referer") or "/reports"
    response = RedirectResponse(url=redirect_url, status_code=302)

    report = db.query(Report).filter(
        Report.id == report_id
    ).first()

    if not report:
        set_flash(response, "error", "Informe no encontrado")
        return response

    property_item = db.query(Property).filter(Property.id == report.property_id).first()

    if not property_item:
        set_flash(response, "error", "Propiedad asociada no encontrada")
        return response

    if not property_item.client or not property_item.client.phone:
        set_flash(response, "error", "El cliente no tiene un número de teléfono registrado")
        return response

    client_phone = property_item.client.phone

    file_url = f"https://evomoyza.duckdns.org/{report.filepath}"
    # file_url = "https://moyza.duckdns.org/storage/reports/b89da4b7-1407-4205-891a-c26faa33c746.pdf"

    print(report.filepath, report.filename, client_phone, property_item.id)

    try:
        send_report(
            phone=client_phone,
            file_url=file_url,
            caption="Reporte generado automáticamente"
        )
        set_flash(response, "success", f"Informe enviado por WhatsApp a {client_phone}")
    except Exception as e:
        print(f"Error enviando WhatsApp: {e}")
        set_flash(response, "error", "Ocurrió un error al enviar el informe por WhatsApp")

    return response
