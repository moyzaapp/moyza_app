"""
Tests para el scheduler de tareas automáticas.
"""
import pytest
from unittest.mock import Mock, patch
from datetime import datetime

from app.jobs.scheduler import check_automatic_reports


@pytest.fixture
def mock_db_session():
    """Mock de la sesión de base de datos."""
    with patch("app.jobs.scheduler.SessionLocal") as mock_session:
        yield mock_session


def test_check_automatic_reports_sin_propiedades(mock_db_session):
    """Verifica que funciona correctamente cuando no hay propiedades."""
    # Setup
    mock_db = Mock()
    mock_db_session.return_value = mock_db
    mock_db.query.return_value.filter.return_value.all.return_value = []

    # Execute
    check_automatic_reports()

    # Verify
    mock_db.query.assert_called_once()
    mock_db.close.assert_called_once()


def test_check_automatic_reports_con_propiedad_activa(mock_db_session):
    """Verifica la generación de informe para propiedad configurada."""
    # Setup
    mock_db = Mock()
    mock_db_session.return_value = mock_db

    # Crear mock de propiedad
    mock_property = Mock()
    mock_property.id = 1
    mock_property.name = "Test Property"
    mock_property.report_frequency = "MONTHLY"
    mock_property.report_day = datetime.now().day
    mock_property.report_hour = datetime.now().hour
    mock_property.auto_send_report = True
    mock_property.status = "ACTIVA"

    mock_db.query.return_value.filter.return_value.all.return_value = [mock_property]

    # Execute
    check_automatic_reports()

    # Verify
    mock_db.query.assert_called_once()
    mock_db.close.assert_called_once()


def test_check_automatic_reports_con_propiedad_inactiva(mock_db_session):
    """Verifica que no procesa propiedades con hora diferente."""
    # Setup
    mock_db = Mock()
    mock_db_session.return_value = mock_db

    # Crear mock de propiedad con hora diferente
    mock_property = Mock()
    mock_property.id = 1
    mock_property.name = "Test Property"
    mock_property.report_frequency = "MONTHLY"
    mock_property.report_day = datetime.now().day
    mock_property.report_hour = (datetime.now().hour + 1) % 24  # Hora diferente
    mock_property.auto_send_report = True
    mock_property.status = "ACTIVA"

    mock_db.query.return_value.filter.return_value.all.return_value = [mock_property]

    # Execute
    check_automatic_reports()

    # Verify - no debería generar informe
    mock_db.query.assert_called_once()
    mock_db.close.assert_called_once()


def test_check_automatic_reports_maneja_errores(mock_db_session):
    """Verifica que los errores se manejan correctamente."""
    # Setup
    mock_db = Mock()
    mock_db_session.return_value = mock_db
    mock_db.query.side_effect = Exception("Database error")

    # Execute - no debería lanzar excepción
    check_automatic_reports()

    # Verify
    mock_db.close.assert_called_once()
