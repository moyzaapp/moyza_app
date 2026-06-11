import logging
import random
import time
from typing import Dict, Optional

import requests
from requests.exceptions import RequestException, Timeout, ConnectionError

from app.core.config import settings

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_DELAY = 2


class WhatsAppServiceError(Exception):
    """Excepción base para errores del servicio de WhatsApp."""
    pass


class WhatsAppValidationError(WhatsAppServiceError):
    """Excepción para errores de validación de datos."""
    pass


class WhatsAppConnectionError(WhatsAppServiceError):
    """Excepción para errores de conexión con la API."""
    pass


class WhatsAppConfigurationError(WhatsAppServiceError):
    """Excepción para errores de configuración del servicio."""
    pass


def _get_whatsapp_config() -> Dict[str, str]:
    """Obtiene y valida la configuración requerida para enviar mensajes."""
    config = {
        "send_media_url": settings.EVOLUTION_URL_SENDMEDIA,
        "send_presence_url": settings.EVOLUTION_URL_SENDPRESENCE,
        "api_key": settings.WHATSAPP_API_KEY,
    }

    missing_values = [
        name
        for name, value in config.items()
        if not value or not value.strip()
    ]

    if missing_values:
        missing = ", ".join(missing_values)
        raise WhatsAppConfigurationError(
            f"Configuración incompleta de WhatsApp: faltan {missing}"
        )

    return config


def human_delay(min_seconds: float = 2.0, max_seconds: float = 6.0) -> None:
    """
    Simula un retraso humano aleatorio.

    Args:
        min_seconds: Tiempo mínimo de espera en segundos
        max_seconds: Tiempo máximo de espera en segundos
    """
    time.sleep(random.uniform(min_seconds, max_seconds))


def _validate_phone(phone: str) -> None:
    """
    Valida el formato del número de teléfono.

    Args:
        phone: Número de teléfono a validar

    Raises:
        WhatsAppValidationError: Si el número no es válido
    """
    if not phone or not isinstance(phone, str):
        raise WhatsAppValidationError("El número de teléfono es requerido y debe ser una cadena")

    if not phone.strip():
        raise WhatsAppValidationError("El número de teléfono no puede estar vacío")


def _validate_file_url(file_url: str) -> None:
    """
    Valida la URL del archivo.

    Args:
        file_url: URL del archivo a validar

    Raises:
        WhatsAppValidationError: Si la URL no es válida
    """
    if not file_url or not isinstance(file_url, str):
        raise WhatsAppValidationError("La URL del archivo es requerida y debe ser una cadena")

    if not file_url.strip():
        raise WhatsAppValidationError("La URL del archivo no puede estar vacía")

    if not file_url.startswith(('http://', 'https://')):
        raise WhatsAppValidationError("La URL del archivo debe comenzar con http:// o https://")


def _send_presence(phone: str, send_presence_url: str, headers: Dict[str, str]) -> bool:
    """
    Envía el estado de 'escribiendo' al chat de WhatsApp.

    Args:
        phone: Número de teléfono destino
        headers: Headers de la petición HTTP

    Returns:
        True si se envió correctamente, False en caso contrario
    """
    try:
        payload = {
            "number": phone,
            "delay": 4500,
            "presence": "composing"
        }

        response = requests.post(
            send_presence_url,
            json=payload,
            headers=headers,
            timeout=REQUEST_TIMEOUT
        )
        response.raise_for_status()

        logger.info(f"Estado de presencia enviado correctamente a {phone}")
        return True

    except Timeout:
        logger.warning(f"Timeout al enviar presencia a {phone}")
        return False

    except ConnectionError:
        logger.warning(f"Error de conexión al enviar presencia a {phone}")
        return False

    except RequestException as e:
        logger.warning(f"Error al enviar presencia a {phone}: {str(e)}")
        return False


def _send_media_request(
    phone: str,
    file_url: str,
    caption: str,
    send_media_url: str,
    headers: Dict[str, str]
) -> requests.Response:
    """
    Realiza la petición HTTP para enviar el archivo.

    Args:
        phone: Número de teléfono destino
        file_url: URL del archivo a enviar
        caption: Texto del mensaje
        headers: Headers de la petición HTTP

    Returns:
        Respuesta HTTP de la petición

    Raises:
        WhatsAppConnectionError: Si hay un error en la conexión
    """
    payload = {
        "number": phone,
        "mediatype": "document",
        "media": file_url,
        "fileName": "reporte.pdf",
        "caption": caption
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.post(
                send_media_url,
                json=payload,
                headers=headers,
                timeout=REQUEST_TIMEOUT
            )
            response.raise_for_status()

            logger.info(f"Archivo enviado correctamente a {phone}")
            return response

        except Timeout:
            error_msg = f"Timeout al enviar archivo a {phone} (intento {attempt}/{MAX_RETRIES})"
            logger.warning(error_msg)

            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * attempt)
                continue
            raise WhatsAppConnectionError(f"Timeout después de {MAX_RETRIES} intentos")

        except ConnectionError as e:
            error_msg = f"Error de conexión al enviar archivo a {phone} (intento {attempt}/{MAX_RETRIES}): {str(e)}"
            logger.warning(error_msg)

            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * attempt)
                continue
            raise WhatsAppConnectionError(f"Error de conexión después de {MAX_RETRIES} intentos: {str(e)}")

        except RequestException as e:
            error_msg = f"Error HTTP al enviar archivo a {phone}: {str(e)}"
            logger.error(error_msg)
            raise WhatsAppConnectionError(error_msg)


def send_report(phone: str, file_url: str, caption: str) -> Optional[Dict]:
    """
    Envía un reporte PDF por WhatsApp con efecto de escritura humana.

    Args:
        phone: Número de teléfono destino (con código de país, ej: 573001234567)
        file_url: URL pública del archivo PDF a enviar
        caption: Texto del mensaje que acompaña el archivo

    Returns:
        Diccionario con la respuesta de la API si fue exitoso, None si falló

    Raises:
        WhatsAppValidationError: Si los parámetros de entrada no son válidos
        WhatsAppConnectionError: Si hay un error de conexión con la API
    """
    try:
        _validate_phone(phone)
        _validate_file_url(file_url)

        if caption is None:
            caption = ""

        config = _get_whatsapp_config()

        headers = {
            "Content-Type": "application/json",
            "apikey": config["api_key"]
        }

        logger.info(f"Iniciando envío de reporte a {phone}")

        _send_presence(phone, config["send_presence_url"], headers)
        human_delay()

        response = _send_media_request(
            phone,
            file_url,
            caption,
            config["send_media_url"],
            headers
        )

        try:
            response_data = response.json()
            logger.info(f"Reporte enviado exitosamente a {phone}: {response_data}")
            return response_data
        except ValueError as e:
            logger.error(f"Error al parsear respuesta JSON: {str(e)}")
            return {"status": "success", "raw_response": response.text}

    except WhatsAppValidationError as e:
        logger.error(f"Error de validación: {str(e)}")
        raise

    except WhatsAppConnectionError as e:
        logger.error(f"Error de conexión: {str(e)}")
        raise

    except WhatsAppConfigurationError as e:
        logger.error(f"Error de configuración: {str(e)}")
        raise

    except Exception as e:
        logger.exception(f"Error inesperado al enviar reporte a {phone}: {str(e)}")
        raise WhatsAppServiceError(f"Error inesperado: {str(e)}")
