"""
Servicio para manejo y validación de firmas digitales.

Proporciona funciones para:
- Guardar firmas como archivos en disco
- Validar que las firmas no estén vacías
- Procesar datos base64 de firmas
"""

import base64
import logging
from pathlib import Path
from typing import Tuple, Optional
from uuid import uuid4

from PIL import Image
from io import BytesIO


logger = logging.getLogger(__name__)


def validate_signature_not_empty(signature_base64: str, min_variance: float = 10.0) -> Tuple[bool, Optional[str]]:
    """
    Valida que la firma no sea un canvas vacío o casi vacío.

    Args:
        signature_base64: Firma en formato base64 (con o sin prefijo data:image)
        min_variance: Varianza mínima de píxeles para considerar la firma válida (default: 10.0)

    Returns:
        Tuple (is_valid, error_message)
        - is_valid: True si la firma es válida
        - error_message: Mensaje de error si no es válida, None si es válida
    """
    try:
        # Extraer datos base64 (remover prefijo si existe)
        if "," in signature_base64:
            img_data = signature_base64.split(",")[1]
        else:
            img_data = signature_base64

        # Decodificar imagen
        img_bytes = base64.b64decode(img_data)

        # Verificar tamaño mínimo (reducido de 500 a 200 para ser más permisivo)
        if len(img_bytes) < 200:
            logger.warning(f"Signature too small: {len(img_bytes)} bytes")
            return False, "La firma es demasiado pequeña. Por favor, dibuje su firma de forma más clara."

        # Usar Pillow para analizar la imagen
        img = Image.open(BytesIO(img_bytes))

        # Convertir a escala de grises
        grayscale = img.convert('L')
        pixels = list(grayscale.getdata())

        # Calcular varianza de píxeles
        mean = sum(pixels) / len(pixels)
        variance = sum((p - mean) ** 2 for p in pixels) / len(pixels)

        # Log para debugging
        logger.info(f"Signature validation - Size: {len(img_bytes)} bytes, Variance: {variance:.2f}, Threshold: {min_variance}")

        # Si varianza muy baja = canvas vacío o casi vacío
        if variance < min_variance:
            logger.warning(f"Signature variance too low: {variance:.2f} < {min_variance}")
            return False, f"La firma parece estar vacía (varianza: {variance:.2f}). Por favor, firme con trazos más definidos."

        logger.info(f"Signature validated successfully - Variance: {variance:.2f}")
        return True, None

    except Exception as e:
        logger.error(f"Error validating signature: {e}")
        return False, f"Error al validar la firma: {str(e)}"


def save_signature_to_file(
    signature_base64: str,
    visit_id: int,
    output_dir: str = "storage/signatures"
) -> Tuple[str, str]:
    """
    Guarda la firma como archivo PNG en disco.

    Args:
        signature_base64: Firma en formato base64 (con o sin prefijo data:image)
        visit_id: ID de la visita asociada
        output_dir: Directorio donde guardar las firmas

    Returns:
        Tuple (filename, filepath)
        - filename: Nombre del archivo generado
        - filepath: Ruta completa del archivo guardado
    """
    # Crear directorio si no existe
    signatures_dir = Path(output_dir)
    signatures_dir.mkdir(parents=True, exist_ok=True)

    # Extraer datos base64 (remover prefijo si existe)
    if "," in signature_base64:
        img_data = signature_base64.split(",")[1]
    else:
        img_data = signature_base64

    # Decodificar imagen
    signature_bytes = base64.b64decode(img_data)

    # Generar nombre único
    filename = f"signature_{visit_id}_{uuid4().hex[:8]}.png"
    filepath = signatures_dir / filename

    # Guardar archivo
    with open(filepath, 'wb') as f:
        f.write(signature_bytes)

    logger.info(f"Signature saved: {filepath}")

    return filename, str(filepath)


def load_signature_from_file(filepath: str) -> Optional[bytes]:
    """
    Carga una firma desde un archivo.

    Args:
        filepath: Ruta del archivo de firma

    Returns:
        Bytes de la imagen o None si el archivo no existe
    """
    file_path = Path(filepath)

    if not file_path.exists():
        logger.warning(f"Signature file not found: {filepath}")
        return None

    with open(file_path, 'rb') as f:
        return f.read()


def delete_signature_file(filepath: str) -> bool:
    """
    Elimina un archivo de firma del disco.

    Args:
        filepath: Ruta del archivo a eliminar

    Returns:
        True si se eliminó correctamente, False si hubo error
    """
    try:
        file_path = Path(filepath)

        if file_path.exists():
            file_path.unlink()
            logger.info(f"Signature file deleted: {filepath}")
            return True
        else:
            logger.warning(f"Signature file not found for deletion: {filepath}")
            return False

    except Exception as e:
        logger.error(f"Error deleting signature file {filepath}: {e}")
        return False


def get_signature_dimensions(signature_base64: str) -> Tuple[int, int]:
    """
    Obtiene las dimensiones de una firma.

    Args:
        signature_base64: Firma en formato base64

    Returns:
        Tuple (width, height)
    """
    try:
        # Extraer datos base64
        if "," in signature_base64:
            img_data = signature_base64.split(",")[1]
        else:
            img_data = signature_base64

        # Decodificar y obtener dimensiones
        img_bytes = base64.b64decode(img_data)
        img = Image.open(BytesIO(img_bytes))

        return img.size  # Retorna (width, height)

    except Exception as e:
        logger.error(f"Error getting signature dimensions: {e}")
        return (0, 0)
