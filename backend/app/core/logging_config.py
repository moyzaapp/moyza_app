"""
Configuración centralizada de logging para la aplicación.
"""
import logging
import sys

def setup_logging():
    """
    Configura el sistema de logging de la aplicación.
    """
    # Formato del log
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    # Configuración del root logger
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        datefmt=date_format,
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )

    # Reducir verbosidad de librerías externas
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    logging.getLogger("apscheduler.scheduler").setLevel(logging.INFO)
    logging.getLogger("apscheduler.executors").setLevel(logging.WARNING)

    logger = logging.getLogger(__name__)
    logger.info("Sistema de logging configurado")
