"""Acceso a las empresas internas (MOYZA / MOES PREMIUM) y su identidad de marca.

- Lectura de la tabla `companies`.
- `branding_for(company)`: datos legales y de marca con valores por defecto,
  para que PDFs, emails y plantillas nunca dependan de un campo NULL.
"""
import os
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.constants import CompanyCode
from app.models.company import Company


# Valores por defecto: la identidad histórica de MOYZA, que es lo que
# mostraba la app antes de la separación por empresa.
_DEFAULT_NAME = "MOYZA"
_DEFAULT_LEGAL_NAME = "Moyza 2012 S.L."
_DEFAULT_TAX_ID = "B16914012"
_DEFAULT_FISCAL_ADDRESS = "Avda. Doctor Eduardo García Triviño López 9, 23009 (Jaén)"
_DEFAULT_PHONE = "642 497 955 / 953 940 956"
_DEFAULT_LOGO_URL = "/static/logo_moyza.png"
_DEFAULT_COLOR = "#000000"

_DEFAULT_RGPD_TEMPLATE = (
    "En nombre de la empresa Inmobiliaria {name} tratamos la información que nos facilita "
    "con el fin de prestarles el servicio solicitado y realizar la facturación del mismo. "
    "Los datos proporcionados se conservarán mientras se mantenga la relación comercial o "
    "durante los meses necesarios para cumplir con las obligaciones legales. Los datos no se "
    "cederán a terceros salvo en los casos en que exista una obligación legal. Usted tiene "
    "derecho a obtener confirmación sobre si en Inmobiliaria {name} estamos tratando sus datos "
    "personales, por tanto tiene derecho a acceder a sus datos personales, rectificar los datos "
    "inexactos o solicitar su supresión cuando los datos ya no sean necesarios."
)


@dataclass(frozen=True)
class CompanyBranding:
    """Identidad de una empresa lista para usar en documentos y comunicaciones."""

    code: str
    name: str
    legal_name: str
    tax_id: str
    fiscal_address: str
    phone: str
    rgpd_text: str
    logo_url: str
    primary_color: str
    document_prefix: str
    email_sender_name: str
    whatsapp_phone: str | None

    @property
    def logo_fs_path(self) -> str | None:
        """Ruta en disco del logo (la URL `/static/x.png` vive en `app/static/x.png`)."""
        relative = self.logo_url.lstrip("/")
        if relative.startswith("static/"):
            relative = "app/" + relative
        for candidate in (relative, os.path.join("backend", relative)):
            if os.path.exists(candidate):
                return candidate
        return None

    @property
    def rgpd_consent_text(self) -> str:
        """Frase de autorización RGPD que firma el interesado."""
        return (
            f"Autorizo a que mis datos sean tratados por Inmobiliaria {self.name} hasta que "
            "finalice la operación o se comunique por mi parte rescindir la misma."
        )

    def document_id(self, *parts) -> str:
        """ID de documento legal: PREFIJO-VISIT-<visita>-<propiedad>."""
        return "-".join([self.document_prefix, *[str(p) for p in parts]])

    @property
    def system_name(self) -> str:
        """Nombre del sistema en los pies de email: 'sistema MOYZA'."""
        return f"sistema {self.name}"


def branding_for(company: Company | None) -> CompanyBranding:
    """Marca de la empresa con valores por defecto para los campos vacíos.

    Acepta None para que el código que aún no conoce la empresa (o datos
    antiguos) siga generando documentos con la identidad de MOYZA.
    """
    name = (company.name if company and company.name else _DEFAULT_NAME)

    return CompanyBranding(
        code=(company.code if company else CompanyCode.DEFAULT),
        name=name,
        legal_name=(company.legal_name if company and company.legal_name else _DEFAULT_LEGAL_NAME),
        tax_id=(company.tax_id if company and company.tax_id else _DEFAULT_TAX_ID),
        fiscal_address=(
            company.fiscal_address if company and company.fiscal_address else _DEFAULT_FISCAL_ADDRESS
        ),
        phone=(company.phone if company and company.phone else _DEFAULT_PHONE),
        rgpd_text=(
            company.rgpd_text if company and company.rgpd_text
            else _DEFAULT_RGPD_TEMPLATE.format(name=name)
        ),
        logo_url=(company.logo_path if company and company.logo_path else _DEFAULT_LOGO_URL),
        primary_color=(
            company.primary_color if company and company.primary_color else _DEFAULT_COLOR
        ),
        document_prefix=(
            company.document_prefix if company and company.document_prefix
            else f"{(company.code if company else CompanyCode.DEFAULT)}-VISIT"
        ),
        email_sender_name=(
            company.email_sender_name if company and company.email_sender_name
            else f"Sistema {name}"
        ),
        whatsapp_phone=(company.whatsapp_phone if company else None),
    )


def get_company_by_code(db: Session, code: str) -> Company | None:
    return db.query(Company).filter(Company.code == code).first()


def get_default_company(db: Session) -> Company:
    """Empresa por defecto (MOYZA). Debe existir siempre: la crea la migración."""
    company = get_company_by_code(db, CompanyCode.DEFAULT)

    if company is None:
        raise RuntimeError(
            f"La empresa por defecto '{CompanyCode.DEFAULT}' no existe en la tabla companies. "
            "Ejecuta las migraciones (alembic upgrade head)."
        )

    return company


def get_default_company_id(db: Session) -> int:
    return get_default_company(db).id


def list_active_companies(db: Session) -> list[Company]:
    return (
        db.query(Company)
        .filter(Company.is_active.is_(True))
        .order_by(Company.id)
        .all()
    )


def resolve_companies(db: Session, company_ids: list[int], fallback: list[Company] | None = None) -> list[Company]:
    """Empresas activas a partir de los ids de un formulario (checkboxes).

    Si no se indica ninguna válida se devuelve `fallback` o, en su defecto,
    la empresa por defecto, para que nadie quede sin acceso ni invisible.
    """
    companies: list[Company] = []
    if company_ids:
        companies = (
            db.query(Company)
            .filter(Company.id.in_(company_ids), Company.is_active.is_(True))
            .order_by(Company.id)
            .all()
        )
    return companies or list(fallback or []) or [get_default_company(db)]


def companies_label(companies: list[Company]) -> str:
    """Texto para las columnas heredadas `company`: 'MOYZA, MOES PREMIUM'."""
    return ", ".join(c.name for c in companies)


def company_ids_from_form(form) -> list[int]:
    """Lee los checkboxes `company_ids` de un formulario, ignorando valores no numéricos."""
    ids: list[int] = []
    for raw in form.getlist("company_ids"):
        try:
            ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    return ids
