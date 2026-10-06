import logging
from typing import Optional

from app.core.config import settings
from app.services.gmail_service import GmailService

logger = logging.getLogger(__name__)

# Marca por defecto de los correos de cuenta cuando no se indica empresa
DEFAULT_COMPANY_NAME = "MOYZA"


def _build_welcome_email_body(
    full_name: str,
    email: str,
    password: str,
    login_url: str,
    role_name: Optional[str] = None,
    company_name: str = DEFAULT_COMPANY_NAME,
) -> str:

    role_row = ""
    if role_name:
        role_row = f"""
        <tr>
            <td style="padding:8px 12px;border-bottom:1px solid #eee;color:#888;">Rol</td>
            <td style="padding:8px 12px;border-bottom:1px solid #eee;">{role_name}</td>
        </tr>"""

    return f"""
    <html><body style="font-family:Arial,sans-serif;color:#333;max-width:680px;margin:auto;">
      <h2 style="color:#0E567B;">Bienvenido a {company_name}</h2>
      <p>Hola <strong>{full_name}</strong>,</p>
      <p>Se ha creado tu cuenta en el sistema {company_name}. Estos son tus datos de acceso:</p>
      <table style="width:100%;border-collapse:collapse;margin-top:16px;background:#f7f9fa;">
        <tbody>
          <tr>
            <td style="padding:8px 12px;border-bottom:1px solid #eee;color:#888;width:35%;">Usuario</td>
            <td style="padding:8px 12px;border-bottom:1px solid #eee;font-weight:bold;">{email}</td>
          </tr>
          <tr>
            <td style="padding:8px 12px;border-bottom:1px solid #eee;color:#888;">Contraseña</td>
            <td style="padding:8px 12px;border-bottom:1px solid #eee;font-family:monospace;font-weight:bold;">{password}</td>
          </tr>{role_row}
        </tbody>
      </table>
      <p style="margin-top:24px;">
        <a href="{login_url}"
           style="background:#0E567B;color:#fff;padding:12px 24px;text-decoration:none;
                  border-radius:4px;display:inline-block;">
          Iniciar sesión
        </a>
      </p>
      <p style="margin-top:24px;padding:12px;background:#fff6e5;border-left:4px solid #e0a04a;font-size:13px;">
        <strong>Importante:</strong> por seguridad, cambia tu contraseña después del primer acceso
        y no compartas este correo con nadie.
      </p>
      <p style="margin-top:24px;font-size:13px;color:#888;">
        Este es un correo automático del sistema {company_name}.
      </p>
    </body></html>
    """


def send_welcome_email(
    email: str,
    full_name: str,
    password: str,
    role_name: Optional[str] = None,
    gmail_service: Optional[GmailService] = None,
    company_name: Optional[str] = None,
) -> bool:
    """Envía al usuario recién creado sus credenciales de acceso.

    `company_name` es la empresa desde la que el admin crea al usuario
    (MOYZA o MOES PREMIUM); por defecto MOYZA.

    Nunca lanza: cualquier fallo se registra y se devuelve False, de modo que
    un problema de correo no interrumpa la creación del usuario.
    """

    if not settings.WELCOME_EMAIL_ENABLED:
        logger.info(f"Correo de bienvenida deshabilitado; no se envía a {email}")
        return False

    try:
        service = gmail_service or GmailService(
            settings.GMAIL_CREDENTIALS_PATH,
            settings.GMAIL_TOKEN_PATH
        )

        body = _build_welcome_email_body(
            full_name=full_name,
            email=email,
            password=password,
            login_url=settings.public_url("/"),
            role_name=role_name,
            company_name=company_name or DEFAULT_COMPANY_NAME,
        )

        return service.send_email(
            to=email,
            subject=f"Bienvenido a {company_name or DEFAULT_COMPANY_NAME} — Datos de acceso",
            html_body=body,
        )

    except Exception as e:
        logger.error(f"Error al enviar el correo de bienvenida a {email}: {e}")
        return False


def _build_password_changed_email_body(
    full_name: str,
    email: str,
    password: str,
    login_url: str,
    company_name: str = DEFAULT_COMPANY_NAME,
) -> str:

    return f"""
    <html><body style="font-family:Arial,sans-serif;color:#333;max-width:680px;margin:auto;">
      <h2 style="color:#0E567B;">Tu contraseña ha sido actualizada</h2>
      <p>Hola <strong>{full_name}</strong>,</p>
      <p>Un administrador ha restablecido la contraseña de tu cuenta en {company_name}.
         Estos son tus nuevos datos de acceso:</p>
      <table style="width:100%;border-collapse:collapse;margin-top:16px;background:#f7f9fa;">
        <tbody>
          <tr>
            <td style="padding:8px 12px;border-bottom:1px solid #eee;color:#888;width:35%;">Usuario</td>
            <td style="padding:8px 12px;border-bottom:1px solid #eee;font-weight:bold;">{email}</td>
          </tr>
          <tr>
            <td style="padding:8px 12px;border-bottom:1px solid #eee;color:#888;">Nueva contraseña</td>
            <td style="padding:8px 12px;border-bottom:1px solid #eee;font-family:monospace;font-weight:bold;">{password}</td>
          </tr>
        </tbody>
      </table>
      <p style="margin-top:24px;">
        <a href="{login_url}"
           style="background:#0E567B;color:#fff;padding:12px 24px;text-decoration:none;
                  border-radius:4px;display:inline-block;">
          Iniciar sesión
        </a>
      </p>
      <p style="margin-top:24px;padding:12px;background:#fff6e5;border-left:4px solid #e0a04a;font-size:13px;">
        <strong>Importante:</strong> si no esperabas este cambio, avisa de inmediato al
        administrador del sistema. No compartas este correo con nadie.
      </p>
      <p style="margin-top:24px;font-size:13px;color:#888;">
        Este es un correo automático del sistema {company_name}.
      </p>
    </body></html>
    """


def send_password_changed_email(
    email: str,
    full_name: str,
    password: str,
    gmail_service: Optional[GmailService] = None,
    company_name: Optional[str] = None,
) -> bool:
    """Notifica al usuario su nueva contraseña tras un cambio administrativo.

    Nunca lanza: cualquier fallo se registra y se devuelve False.
    """

    if not settings.WELCOME_EMAIL_ENABLED:
        logger.info(f"Correo de credenciales deshabilitado; no se envía a {email}")
        return False

    try:
        service = gmail_service or GmailService(
            settings.GMAIL_CREDENTIALS_PATH,
            settings.GMAIL_TOKEN_PATH
        )

        body = _build_password_changed_email_body(
            full_name=full_name,
            email=email,
            password=password,
            login_url=settings.public_url("/"),
            company_name=company_name or DEFAULT_COMPANY_NAME,
        )

        return service.send_email(
            to=email,
            subject=f"{company_name or DEFAULT_COMPANY_NAME} — Tu contraseña ha sido actualizada",
            html_body=body,
        )

    except Exception as e:
        logger.error(f"Error al enviar el correo de cambio de contraseña a {email}: {e}")
        return False
