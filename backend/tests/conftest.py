"""Configuración común de pytest.

Los modelos se registran en `app.db.base`; importar un modelo suelto antes
de ese módulo provoca una importación circular. Cargarlo aquí garantiza el
orden correcto en todos los tests.
"""
import app.db.base  # noqa: F401
