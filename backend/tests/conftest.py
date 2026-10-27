"""Configuración común de pytest.

Los modelos se registran en `app.db.base`; importar un modelo suelto antes
de ese módulo provoca una importación circular. Cargarlo aquí garantiza el
orden correcto en todos los tests.

`settings.BUYER_ATTENTION_SINCE` (corte de los avisos de compradores) se
anula en todos los tests: muchos usan fechas fijas anteriores al corte. Los
tests del corte lo pasan explícito (`since=`) o lo fijan con `monkeypatch`.
La app levantada (tests de integración por HTTP) usa el valor real, que sigue
en `Settings.BUYER_ATTENTION_SINCE`.
"""
import pytest

import app.db.base  # noqa: F401


@pytest.fixture(autouse=True)
def _sin_corte_de_avisos(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "BUYER_ATTENTION_SINCE", None)
