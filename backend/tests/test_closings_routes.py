"""
Tests de ruta de la pestaña Cierres (PLAN_CIERRES_MANUALES_Y_DIRECCIONES.md, fase B).

Integración contra la app levantada (patrón de test_commercial_results.py; se
omiten si la app no responde): solo admin, alta con validación (fecha
futura, agente de otra empresa, propiedad de otra empresa, operación),
borrado, recálculo del snapshot congelado, lupa de trazabilidad y CSV, y
aislamiento por empresa (un cierre de MOES no sale con MOYZA activa). Crean
dos agentes, una propiedad por empresa y un usuario agente; lo borran todo
(también los cierres y snapshots) al final.

Ejecución dentro del contenedor:
    docker exec moyza_backend python -m pytest tests/test_closings_routes.py -q
"""
import base64
import re
from datetime import date, datetime, timedelta

import pytest

from tests.test_commercial_results import Client
from tests.test_commercial_results import _server_up

ADMIN_EMAIL = "admin@moyza.com"
TAG = "PYTEST-CIERRES-RUTA"
AGENT_EMAIL = "pytest.cierres.ruta@example.com"
MOES_AGENT_EMAIL = "pytest.cierres.ruta.moes@example.com"

pytestmark = pytest.mark.skipif(not _server_up(), reason="La app no responde; tests de integración omitidos")


@pytest.fixture(scope="module")
def setup():
    """Agente de MOYZA (con usuario agente), agente solo de MOES y una propiedad vendida en cada empresa."""
    from app.db.session import SessionLocal
    from app.models.agent import Agent
    from app.models.agent_performance_report import AgentPerformanceReport
    from app.models.closing import Closing
    from app.models.company import Company
    from app.models.property import Property
    from app.models.role import Role
    from app.models.user import User

    db = SessionLocal()
    moyza = db.query(Company).filter_by(code="MOYZA").one()
    moes = db.query(Company).filter_by(code="MOES").one()
    role = db.query(Role).filter(Role.name.ilike("agent")).first()

    agent = Agent(name=f"{TAG} AGENTE", email=AGENT_EMAIL)
    agent.companies.append(moyza)
    moes_agent = Agent(name=f"{TAG} MOES", email=MOES_AGENT_EMAIL)
    moes_agent.companies.append(moes)
    user = User(email=AGENT_EMAIL, full_name=f"{TAG} usuario", hashed_password="pytest-sin-login",
                role_id=role.id if role else None, is_active=True)
    user.companies.append(moyza)
    db.add_all([agent, moes_agent, user])
    db.flush()
    prop = Property(title=f"{TAG} PISO", referencia="PYT-CIE-1", city="Jaén", company_id=moyza.id,
                    agent_id=agent.id, business_type="Venta", status="Vendida", market_entry_date=datetime(2025, 1, 1))
    moes_prop = Property(title=f"{TAG} PISO MOES", company_id=moes.id, agent_id=moes_agent.id,
                         business_type="Venta", market_entry_date=datetime(2025, 1, 1))
    db.add_all([prop, moes_prop])
    db.commit()

    data = {"agent_id": agent.id, "moes_agent_id": moes_agent.id, "prop_id": prop.id,
            "moes_prop_id": moes_prop.id, "moyza_id": moyza.id, "moes_id": moes.id}
    yield data

    agent_ids = [agent.id, moes_agent.id]
    db.query(Closing).filter(Closing.agent_id.in_(agent_ids)).delete(synchronize_session=False)
    db.query(AgentPerformanceReport).filter(AgentPerformanceReport.agent_id.in_(agent_ids)).delete(synchronize_session=False)
    db.query(Property).filter(Property.title.like(f"{TAG}%")).delete(synchronize_session=False)
    db.query(User).filter(User.email == AGENT_EMAIL).delete(synchronize_session=False)
    for email in (AGENT_EMAIL, MOES_AGENT_EMAIL):
        found = db.query(Agent).filter(Agent.email == email).first()
        if found:
            found.companies.clear()
            db.delete(found)
    db.commit()
    db.close()


@pytest.fixture(scope="module")
def admin():
    return Client(ADMIN_EMAIL, "MOYZA")


def _db():
    from app.db.session import SessionLocal
    return SessionLocal()


def _closings(agent_id):
    from app.models.closing import Closing
    db = _db()
    try:
        return db.query(Closing).filter(Closing.agent_id == agent_id).order_by(Closing.id).all()
    finally:
        db.close()


def _flash(headers) -> str:
    match = re.search(r'moyza_flash="?([^";]+)', headers.get("Set-Cookie", "") or headers.get("set-cookie", ""))
    return base64.b64decode(match.group(1)).decode("utf-8") if match else ""


def _create(client, **data):
    return client.post("/commercial-results/closings", data)


def test_agente_no_entra_ni_registra(setup):
    agent = Client(AGENT_EMAIL, "MOYZA")
    status, _, headers = agent.get("/commercial-results?tab=cierres")
    assert status == 302 and headers.get("location") == "/alerts"

    status, _, headers = _create(agent, agent_id=setup["agent_id"], closed_on=date.today().isoformat(),
                                 business_type="Venta")
    assert status == 302 and headers.get("location") == "/alerts"
    assert _closings(setup["agent_id"]) == []


def test_pestana_vacia_y_modal(admin, setup):
    status, body, _ = admin.get("/commercial-results?tab=cierres&year=2001")
    assert status == 200
    assert "Aún no hay cierres registrados en 2001" in body
    assert 'id="closingModal"' in body and "Registrar cierre" in body
    # Agentes activos de la empresa activa y propiedades de la empresa (también vendidas)
    assert f'<option value="{setup["agent_id"]}">{TAG} AGENTE</option>' in body
    assert f'value="{setup["moes_agent_id"]}"' not in body
    assert f'<option value="{setup["prop_id"]}">{TAG} PISO · PYT-CIE-1 (Vendida)</option>' in body
    assert f'value="{setup["moes_prop_id"]}"' not in body


def test_alta_validaciones(admin, setup):
    tomorrow = (datetime.utcnow() + timedelta(days=2)).date().isoformat()
    cases = [
        ({"agent_id": setup["agent_id"], "closed_on": tomorrow, "business_type": "Venta"}, "no puede ser futura"),
        ({"agent_id": setup["agent_id"], "closed_on": "", "business_type": "Venta"}, "fecha"),
        ({"agent_id": setup["agent_id"], "closed_on": "2025-03-10", "business_type": "Traspaso"}, "Venta o de Alquiler"),
        ({"agent_id": setup["moes_agent_id"], "closed_on": "2025-03-10", "business_type": "Venta"}, "agente activo"),
        ({"agent_id": setup["agent_id"], "closed_on": "2025-03-10", "business_type": "Venta",
          "property_id": setup["moes_prop_id"]}, "no pertenece a la empresa"),
    ]
    for data, message in cases:
        status, _, headers = _create(admin, **data)
        assert status == 302 and headers.get("location") == "/commercial-results?tab=cierres"
        assert message in _flash(headers)
    assert _closings(setup["agent_id"]) == []
    assert _closings(setup["moes_agent_id"]) == []


def test_alta_listado_lupa_snapshot_y_borrado(admin, setup):
    from app.models.agent_performance_report import AgentPerformanceReport

    # Marzo de 2025 congelado para el agente (sin cierres)
    db = _db()
    report = AgentPerformanceReport(agent_id=setup["agent_id"], company_id=setup["moyza_id"], period_type="MONTHLY",
                                    period_start=datetime(2025, 3, 1), period_end=datetime(2025, 3, 31, 23, 59, 59),
                                    captaciones_crm=3, cierres=0, cierres_venta=0, cierres_alquiler=0,
                                    is_locked=True, locked_at=datetime(2025, 4, 1, 3, 0))
    db.add(report)
    db.commit()
    report_id = report.id
    db.close()

    status, _, headers = _create(admin, agent_id=setup["agent_id"], closed_on="2025-03-31", business_type="Venta",
                                 property_id=setup["prop_id"], notes="Firma en notaría")
    assert status == 302 and headers.get("location") == "/commercial-results?tab=cierres&year=2025"
    assert "registrado" in _flash(headers)
    _create(admin, agent_id=setup["agent_id"], closed_on="2025-03-05", business_type="Alquiler")

    closings = _closings(setup["agent_id"])
    assert [(c.closed_on, c.business_type, c.property_id, c.notes) for c in closings] == [
        (date(2025, 3, 31), "Venta", setup["prop_id"], "Firma en notaría"),
        (date(2025, 3, 5), "Alquiler", None, None),
    ]
    assert all(c.company_id == setup["moyza_id"] and c.created_by is not None for c in closings)

    # Snapshot congelado: solo las columnas de cierres
    db = _db()
    stored = db.get(AgentPerformanceReport, report_id)
    assert (stored.cierres, stored.cierres_venta, stored.cierres_alquiler, stored.captaciones_crm) == (2, 1, 1, 3)
    db.close()

    # Listado del año, más reciente primero
    body = admin.get("/commercial-results?tab=cierres&year=2025")[1]
    rows = re.findall(r'data-closing-row="(\d+)"', body)
    assert rows.index(str(closings[0].id)) < rows.index(str(closings[1].id))
    assert "31/03/2025" in body and "Firma en notaría" in body and f"{TAG} PISO" in body
    assert f'data-delete-closing="/commercial-results/closings/{closings[0].id}/delete"' in body

    # Lupa de trazabilidad y CSV del mes
    detail = admin.get(f"/commercial-results/{setup['agent_id']}/metric/cierres?period_type=MONTHLY&period_start=2025-03-01")[1]
    assert "registrados por el administrador" in detail
    assert len(re.findall(r"<tr[^>]*data-metric-row\b", detail)) == 2
    status, csv_body, _ = admin.get(
        f"/commercial-results/{setup['agent_id']}/metric/cierres?period_type=MONTHLY&period_start=2025-03-01&format=csv")
    lines = csv_body.lstrip("﻿").strip().splitlines()
    assert lines[0] == "Fecha de cierre;Operación;Propiedad;Ciudad;Nota;Enlace"
    assert lines[1] == f"31/03/2025;Venta;PYT-CIE-1 · {TAG} PISO;Jaén;Firma en notaría;/properties/{setup['prop_id']}"

    # Borrado: el snapshot vuelve a contar uno menos
    status, _, headers = admin.post(f"/commercial-results/closings/{closings[1].id}/delete", {})
    assert status == 302 and headers.get("location") == "/commercial-results?tab=cierres&year=2025"
    assert "Cierre eliminado" in _flash(headers)
    assert [c.id for c in _closings(setup["agent_id"])] == [closings[0].id]
    db = _db()
    stored = db.get(AgentPerformanceReport, report_id)
    assert (stored.cierres, stored.cierres_venta, stored.cierres_alquiler) == (1, 1, 0)
    db.close()


def test_agente_no_borra(setup):
    from app.models.closing import Closing
    db = _db()
    closing = Closing(company_id=setup["moyza_id"], agent_id=setup["agent_id"], business_type="Venta",
                      closed_on=date(2025, 6, 1))
    db.add(closing)
    db.commit()
    closing_id = closing.id
    db.close()

    status, _, headers = Client(AGENT_EMAIL, "MOYZA").post(f"/commercial-results/closings/{closing_id}/delete", {})
    assert status == 302 and headers.get("location") == "/alerts"
    assert closing_id in [c.id for c in _closings(setup["agent_id"])]


def test_aislamiento_por_empresa(setup):
    moes = Client(ADMIN_EMAIL, "MOES")
    status, _, headers = _create(moes, agent_id=setup["moes_agent_id"], closed_on="2025-05-20", business_type="Venta",
                                 property_id=setup["moes_prop_id"], notes="Cierre MOES")
    assert status == 302 and "registrado" in _flash(headers)
    moes_closing = _closings(setup["moes_agent_id"])[0]
    assert moes_closing.company_id == setup["moes_id"]

    moyza = Client(ADMIN_EMAIL, "MOYZA")
    body = moyza.get("/commercial-results?tab=cierres&year=2025")[1]
    assert f'data-closing-row="{moes_closing.id}"' not in body and "Cierre MOES" not in body
    assert f'data-closing-row="{moes_closing.id}"' in moes.get("/commercial-results?tab=cierres&year=2025")[1]

    # Con MOYZA activa no se puede borrar un cierre de MOES
    status, _, headers = moyza.post(f"/commercial-results/closings/{moes_closing.id}/delete", {})
    assert status == 302 and "no encontrado" in _flash(headers)
    assert [c.id for c in _closings(setup["moes_agent_id"])] == [moes_closing.id]
