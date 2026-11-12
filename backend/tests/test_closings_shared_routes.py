"""
Tests de ruta de los cierres compartidos (PLAN_CIERRES_DOS_AGENTES.md, fase B).

Integración contra la app levantada (patrón de test_closings_routes.py; se
omiten si la app no responde): alta con Agente 1 y Agente 2 (dos registros
enlazados, una fila en la pestaña con los dos nombres y 1 operación en los
totales), alta con el mismo agente dos veces (error y nada creado), borrado
desde la fila (borra la pareja), lupa y CSV con "con Nombre" y un solo evento
en la actividad del Inicio. Crean dos agentes y una propiedad de MOYZA y lo
borran todo al final.

Ejecución dentro del contenedor:
    docker exec moyza_backend python -m pytest tests/test_closings_shared_routes.py -q
"""
import html
import re
from datetime import datetime

import pytest

from tests.test_closings_routes import _flash
from tests.test_commercial_results import Client
from tests.test_commercial_results import _server_up

ADMIN_EMAIL = "admin@moyza.com"
TAG = "PYTEST-CIERRE-PAREJA"
ANA_EMAIL = "pytest.cierre.pareja.ana@example.com"
BEA_EMAIL = "pytest.cierre.pareja.bea@example.com"
YEAR = 2024

pytestmark = pytest.mark.skipif(not _server_up(), reason="La app no responde; tests de integración omitidos")


@pytest.fixture(scope="module")
def setup():
    """Ana y Bea, agentes de MOYZA, y una propiedad de MOYZA."""
    from app.db.session import SessionLocal
    from app.models.agent import Agent
    from app.models.agent_performance_report import AgentPerformanceReport
    from app.models.closing import Closing
    from app.models.company import Company
    from app.models.property import Property

    db = SessionLocal()
    moyza = db.query(Company).filter_by(code="MOYZA").one()
    ana = Agent(name=f"{TAG} ANA", email=ANA_EMAIL)
    ana.companies.append(moyza)
    bea = Agent(name=f"{TAG} BEA", email=BEA_EMAIL)
    bea.companies.append(moyza)
    db.add_all([ana, bea])
    db.flush()
    prop = Property(title=f"{TAG} PISO", referencia="PYT-PAR-1", city="Jaén", company_id=moyza.id,
                    agent_id=ana.id, business_type="Venta", status="Vendida", market_entry_date=datetime(2024, 1, 1))
    db.add(prop)
    db.commit()

    yield {"ana_id": ana.id, "bea_id": bea.id, "prop_id": prop.id, "moyza_id": moyza.id}

    agent_ids = [ana.id, bea.id]
    db.query(Closing).filter(Closing.agent_id.in_(agent_ids)).delete(synchronize_session=False)
    db.query(AgentPerformanceReport).filter(AgentPerformanceReport.agent_id.in_(agent_ids)).delete(synchronize_session=False)
    db.query(Property).filter(Property.title.like(f"{TAG}%")).delete(synchronize_session=False)
    for email in (ANA_EMAIL, BEA_EMAIL):
        found = db.query(Agent).filter(Agent.email == email).first()
        if found:
            found.companies.clear()
            db.delete(found)
    db.commit()
    db.close()


@pytest.fixture(scope="module")
def admin():
    return Client(ADMIN_EMAIL, "MOYZA")


def _closings(*agent_ids):
    from app.db.session import SessionLocal
    from app.models.closing import Closing
    db = SessionLocal()
    try:
        return db.query(Closing).filter(Closing.agent_id.in_(agent_ids)).order_by(Closing.id).all()
    finally:
        db.close()


def _create(client, **data):
    return client.post("/commercial-results/closings", data)


def _closings_body(client):
    return html.unescape(client.get(f"/commercial-results?tab=cierres&year={YEAR}")[1])


def test_modal_con_agente_2(admin, setup):
    body = _closings_body(admin)
    assert 'id="closing_agent_2"' in body and 'name="agent_id_2"' in body
    assert "Agente 1" in body and "(opcional, si cerraron entre dos)" in body
    assert "El cierre cuenta para los dos agentes" in body
    second = body.split('id="closing_agent_2"', 1)[1].split("</select>", 1)[0]
    assert f'<option value="{setup["bea_id"]}">{TAG} BEA</option>' in second


def test_mismo_agente_dos_veces_no_crea_nada(admin, setup):
    status, _, headers = _create(admin, agent_id=setup["ana_id"], agent_id_2=setup["ana_id"],
                                 closed_on=f"{YEAR}-05-10", business_type="Venta")
    assert status == 302 and headers.get("location") == "/commercial-results?tab=cierres"
    assert "distintos" in _flash(headers)
    assert _closings(setup["ana_id"], setup["bea_id"]) == []


def test_alta_doble_fila_unica_lupa_csv_inicio_y_borrado(admin, setup):
    from app.db.session import SessionLocal
    from app.services.dashboard_service import DashboardService

    status, _, headers = _create(admin, agent_id=setup["ana_id"], agent_id_2=setup["bea_id"],
                                 closed_on=f"{YEAR}-05-20", business_type="Venta",
                                 property_id=setup["prop_id"], notes="Entre dos")
    assert status == 302 and headers.get("location") == f"/commercial-results?tab=cierres&year={YEAR}"
    assert f"Cierre de {TAG} ANA y {TAG} BEA registrado" in _flash(headers)

    first, second = _closings(setup["ana_id"], setup["bea_id"])
    assert (first.agent_id, first.shared_with_agent_id) == (setup["ana_id"], setup["bea_id"])
    assert (second.agent_id, second.shared_with_agent_id) == (setup["bea_id"], setup["ana_id"])
    assert first.pair_key and first.pair_key == second.pair_key

    # Pestaña: una sola fila (la del Agente 1) con los dos nombres y 1 operación en los totales
    body = _closings_body(admin)
    rows = re.findall(r'data-closing-row="(\d+)"', body)
    assert str(first.id) in rows and str(second.id) not in rows
    row = body.split(f'data-closing-row="{first.id}"', 1)[1].split("</tr>", 1)[0]
    assert f"{TAG} ANA" in row and f"con {TAG} BEA" in row
    assert row.count("data-delete-closing=") == 1
    assert f'data-delete-closing="/commercial-results/closings/{first.id}/delete"' in row
    assert 'data-closing-shared="1"' in row
    assert "se quitará a los dos agentes" in body
    totals = body.split('id="closingsTitle"', 1)[1].split("</p>", 1)[0]
    assert re.search(r'tabular-nums">1</span> cierre · venta <span class="tabular-nums">1</span>', totals)
    assert re.search(r'tabular-nums">1</span> compartido entre dos agentes', totals)

    # Lupa y CSV de cada agente: el cierre cuenta 1 y lleva "con" el otro
    query = f"period_type=MONTHLY&period_start={YEAR}-05-01"
    for agent_key, other in (("ana_id", "BEA"), ("bea_id", "ANA")):
        detail = html.unescape(admin.get(f"/commercial-results/{setup[agent_key]}/metric/cierres?{query}")[1])
        assert len(re.findall(r"<tr[^>]*data-metric-row\b", detail)) == 1
        assert f"con {TAG} {other}" in detail
        csv_body = admin.get(f"/commercial-results/{setup[agent_key]}/metric/cierres?{query}&format=csv")[1]
        lines = csv_body.lstrip("﻿").strip().splitlines()
        assert lines[0] == "Fecha de cierre;Operación;Con;Propiedad;Ciudad;Nota;Enlace"
        assert lines[1].startswith(f"20/05/{YEAR};Venta;{TAG} {other};PYT-PAR-1 · {TAG} PISO;")

    # Inicio del admin: un solo evento con los dos agentes
    db = SessionLocal()
    try:
        feed = DashboardService(db, setup["moyza_id"]).activity_feed()
    finally:
        db.close()
    events = [e for e in feed if e["kind"] == "closing" and TAG in e["text"]]
    assert len(events) == 1
    assert events[0]["title"] == f"Cierre · {TAG} PISO"
    assert events[0]["text"] == f"{TAG} ANA y {TAG} BEA · Venta · firmado el 20/05/{YEAR}"
    home = html.unescape(admin.get("/dashboard")[1])
    assert home.count(f"{TAG} ANA y {TAG} BEA") == 1

    # Borrado desde la fila: se van los dos registros
    status, _, headers = admin.post(f"/commercial-results/closings/{first.id}/delete", {})
    assert status == 302 and headers.get("location") == f"/commercial-results?tab=cierres&year={YEAR}"
    assert "a los dos agentes" in _flash(headers)
    assert _closings(setup["ana_id"], setup["bea_id"]) == []
