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

    if send_whatsapp:
        property_item = db.query(Property).filter(Property.id == property_id).first()
        client_phone = property_item.client.phone

        print(report.filepath, report.filename, client_phone)

        file_url = f"https://moyza.duckdns.org/{report.filepath}"
        # file_url = f"https://moyza.duckdns.org/storage/reports/fc6d4a93-78e7-424b-8110-90e1e4761121.pdf"

        send_report(
            phone=client_phone,
            file_url=file_url,
            caption="Reporte generado automáticamente"
        )

    return RedirectResponse(
        url="/reports",
        status_code=302
    )

@router.get("/reports/download/{report_id}")
async def download_report(
    report_id: int,
    db: Session = Depends(get_db)
):

    report = db.query(Report).filter(
        Report.id == report_id
    ).first()

    if not report:
        return {"error": "Report not found"}

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

    if not report:
        return {"error": "Report not found"}

    if os.path.exists(report.filepath):
        os.remove(report.filepath)

    db.delete(report)

    db.commit()

    return RedirectResponse(
        url="/reports",
        status_code=302
    )
