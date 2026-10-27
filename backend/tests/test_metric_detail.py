"""
Tests de ruta del detalle de indicadores (PLAN_TRAZABILIDAD_INDICADORES.md, fase 2).

Integración contra la app levantada (patrón de test_commercial_results.py; se
omiten si la app no responde): solo admin (403 al agente), parcial con las
filas, "Ver más" con offset, CSV con cabecera, N filas y Content-Disposition,
y aislamiento por empresa (agente de MOES con MOYZA activa -> 404). Crean dos
agentes, 53 propiedades y un usuario agente; lo borran todo al final.

Ejecución dentro del contenedor:
    docker exec moyza_backend python -m pytest tests/test_metric_detail.py -q
"""
import os
import re
from datetime import datetime

import pytest

from tests.test_commercial_results import Client
from tests.test_commercial_results import _agent_card
from tests.test_commercial_results import _server_up

BASE_URL = os.getenv("MOYZA_TEST_BASE_URL", "http://localhost:8000")
ADMIN_EMAIL = os.getenv("MOYZA_TEST_ADMIN_EMAIL", "admin@moyza.com")
TAG = "PYTEST-TRAZA-RUTA"
AGENT_EMAIL = "pytest.traza.ruta@example.com"
MOES_AGENT_EMAIL = "pytest.traza.ruta.moes@example.com"
SALE_COUNT = 30
RENT_COUNT = 22
TOTAL = SALE_COUNT + RENT_COUNT

pytestmark = pytest.mark.skipif(
    not _server_up(),
    reason=f"La app no responde en {BASE_URL}; tests de integración omitidos",
)


@pytest.fixture(scope="module")
def setup():
    """Agente de MOYZA con 52 captaciones este mes y agente solo de MOES con una."""
    from app.db.session import SessionLocal
    from app.models.agent import Agent
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

    now = datetime.utcnow()
    for i in range(TOTAL):
        db.add(Property(title=f"{TAG} PROP {i:02d}", referencia=f"PYT-{i:02d}", city="Jaén",
                        address="Calle Secreta 12", company_id=moyza.id, agent_id=agent.id,
                        business_type="Venta" if i < SALE_COUNT else "Alquiler",
                        market_entry_date=now, price=100000 + i))
    db.add(Property(title=f"{TAG} PROP MOES", company_id=moes.id, agent_id=moes_agent.id,
                    business_type="Venta", market_entry_date=now))
    db.commit()

    yield {"agent_id": agent.id, "moes_agent_id": moes_agent.id}

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


def _url(agent_id, key, **params):
    query = "&".join(f"{k}={v}" for k, v in {"period_type": "MONTHLY", **params}.items())
    return f"/commercial-results/{agent_id}/metric/{key}?{query}"


def _rows(body: str) -> int:
    return len(re.findall(r"<tr[^>]*data-metric-row\b", body))


def test_agente_recibe_403(setup):
    agent = Client(AGENT_EMAIL, "MOYZA")
    for url in (_url(setup["agent_id"], "captaciones_crm"),
                _url(setup["agent_id"], "captaciones_crm", format="csv")):
        status, body, _ = agent.get(url)
        assert status == 403
        assert "PYT-" not in body


def test_agente_no_ve_la_pestana_ni_la_lupa(setup):
    status, body, headers = Client(AGENT_EMAIL, "MOYZA").get("/commercial-results?tab=rendimiento")
    assert status == 302 and headers.get("location") == "/alerts"
    assert "data-metric-detail" not in body


def test_admin_ve_la_lupa_en_cada_tarjeta(admin, setup):
    body = admin.get("/commercial-results?tab=rendimiento&period_type=MONTHLY")[1]
    card = _agent_card(body, setup["agent_id"])
    keys = re.findall(rf'data-metric-detail="/commercial-results/{setup["agent_id"]}/metric/([a-z_]+)\?', card)
    assert keys == ["captaciones_crm", "bajadas", "cierres", "contactos", "hojas_visita"]
    assert f'aria-label="Ver el detalle de Captaciones CRM de {TAG} AGENTE"' in card
    assert 'id="metricDrawer"' in body and 'role="dialog"' in body


def test_admin_ve_regla_totales_y_primera_pagina(admin, setup):
    status, body, _ = admin.get(_url(setup["agent_id"], "captaciones_crm"))
    assert status == 200
    assert f"cuyo agente es {TAG} AGENTE" in body and "propiedades de MOYZA" in body
    assert f'data-metric-total>{TOTAL}<' in body
    assert f"venta {SALE_COUNT} · alquiler {RENT_COUNT}" in body
    assert _rows(body) == 50
    assert "Ver más (2 restantes)" in body
    agent_id = setup["agent_id"]
    assert (f'data-metric-more="/commercial-results/{agent_id}/metric/captaciones_crm?'
            f'period_type=MONTHLY&amp;period_start=') in body
    assert "&amp;offset=50\"" in body
    assert "format=csv" in body
    # Referencia y ciudad, sin dirección (decisión §4, nota)
    assert "PYT-" in body and "Jaén" in body
    assert "Calle Secreta" not in body


def test_ver_mas_con_offset(admin, setup):
    status, body, _ = admin.get(_url(setup["agent_id"], "captaciones_crm", offset=50))
    assert status == 200
    assert "data-metric-page" in body
    assert _rows(body) == TOTAL - 50
    assert "Ver más" not in body
    assert "data-metric-rule" not in body


def test_csv(admin, setup):
    status, body, headers = admin.get(_url(setup["agent_id"], "captaciones_crm", format="csv"))
    assert status == 200
    assert headers["content-type"].startswith("text/csv")
    disposition = headers["content-disposition"]
    assert disposition.startswith("attachment;") and ".csv" in disposition
    assert "captaciones_crm" in disposition and "moyza" in disposition

    lines = body.lstrip("﻿").strip().splitlines()
    assert lines[0] == "Fecha de entrada;Propiedad;Ciudad;Tipo;Precio;Estado;Enlace"
    assert len(lines) == TOTAL + 1
    assert sum(1 for line in lines[1:] if ";Venta;" in line) == SALE_COUNT
    assert "Calle Secreta" not in body


def test_indicador_sin_registros(admin, setup):
    status, body, _ = admin.get(_url(setup["agent_id"], "hojas_visita", period_type="WEEKLY"))
    assert status == 200
    assert "No hay registros en este período" in body
    assert _rows(body) == 0


@pytest.mark.parametrize("key", ["captaciones_crm", "bajadas", "cierres", "contactos", "hojas_visita"])
@pytest.mark.parametrize("period_type", ["WEEKLY", "MONTHLY", "YEARLY"])
def test_todos_los_indicadores_y_periodos(admin, setup, key, period_type):
    status, body, _ = admin.get(_url(setup["agent_id"], key, period_type=period_type))
    assert status == 200
    assert "data-metric-rule" in body


def test_aislamiento_por_empresa(setup):
    moes_agent = setup["moes_agent_id"]
    status, body, _ = Client(ADMIN_EMAIL, "MOYZA").get(_url(moes_agent, "captaciones_crm"))
    assert status == 404
    assert "PROP MOES" not in body
    assert Client(ADMIN_EMAIL, "MOYZA").get(_url(moes_agent, "captaciones_crm", format="csv"))[0] == 404

    status, body, _ = Client(ADMIN_EMAIL, "MOES").get(_url(moes_agent, "captaciones_crm"))
    assert status == 200
    assert _rows(body) == 1 and "propiedades de MOES PREMIUM" in body


def test_indicador_desconocido(admin, setup):
    assert admin.get(_url(setup["agent_id"], "calidad_cartera"))[0] == 404
