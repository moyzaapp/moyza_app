"""
Tests de integración del aislamiento por empresa (MOYZA / MOES PREMIUM).

Se ejecutan contra la app levantada (por defecto http://localhost:8000,
configurable con MOYZA_TEST_BASE_URL) y su base de datos. Si la app no
responde, se omiten. Crean datos de prueba en MOES y los eliminan al final.

Ejecución dentro del contenedor:
    docker exec moyza_backend python -m pytest tests/test_company_isolation.py -q
"""
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar

import pytest

BASE_URL = os.getenv("MOYZA_TEST_BASE_URL", "http://localhost:8000")
ADMIN_EMAIL = os.getenv("MOYZA_TEST_ADMIN_EMAIL", "admin@moyza.com")


def _server_up() -> bool:
    try:
        urllib.request.urlopen(BASE_URL + "/", timeout=3)
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _server_up(),
    reason=f"La app no responde en {BASE_URL}; tests de integración omitidos",
)


# ---------------------------------------------------------------------------
# Cliente HTTP mínimo (sin dependencias externas)
# ---------------------------------------------------------------------------

class Client:
    """Peticiones con cookies de sesión y empresa, sin seguir redirecciones."""

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    def __init__(self, token: str, company: str | None):
        self.cookie = f"access_token={token}"
        if company:
            self.cookie += f"; active_company={company}"
        self.opener = urllib.request.build_opener(self._NoRedirect, urllib.request.HTTPCookieProcessor(CookieJar()))

    def _request(self, method, path, data=None):
        body = urllib.parse.urlencode(data).encode() if data is not None else None
        req = urllib.request.Request(BASE_URL + path, data=body, method=method)
        req.add_header("Cookie", self.cookie)
        try:
            resp = self.opener.open(req, timeout=20)
            return resp.status, resp.read().decode("utf-8", "replace"), dict(resp.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace"), dict(e.headers)

    def get(self, path):
        return self._request("GET", path)

    def post(self, path, data):
        return self._request("POST", path, data or {})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def db():
    import app.db.base  # noqa: F401  (registra todos los modelos)
    from app.db.session import SessionLocal
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture(scope="module")
def companies(db):
    from app.models.company import Company
    moyza = db.query(Company).filter_by(code="MOYZA").one()
    moes = db.query(Company).filter_by(code="MOES").one()
    return {"MOYZA": moyza, "MOES": moes}


@pytest.fixture(scope="module")
def admin_token():
    from app.core.security import create_access_token
    return create_access_token({"sub": ADMIN_EMAIL})


@pytest.fixture(scope="module")
def moyza(admin_token):
    return Client(admin_token, "MOYZA")


@pytest.fixture(scope="module")
def moes(admin_token):
    return Client(admin_token, "MOES")


@pytest.fixture(scope="module")
def moes_data(db, moes):
    """Agente, cliente, propiedad y comprador creados en MOES; se borran al final."""
    from app.models.agent import Agent
    from app.models.buyer import Buyer
    from app.models.client import Client as ClientModel
    from app.models.property import Property

    tag = "PYTEST-MOES"
    moes.post("/agents/create", {"name": f"{tag} AGENTE", "email": "pytest.agente@example.com"})
    moes.post("/clients/create", {"name": f"{tag} CLIENTE", "email": "pytest.cliente@example.com", "phone": "600000000"})
    db.expire_all()
    agent = db.query(Agent).filter_by(email="pytest.agente@example.com").one()
    client = db.query(ClientModel).filter_by(email="pytest.cliente@example.com").one()

    moes.post("/properties/create", {
        "title": f"{tag} PROP", "address": "Calle Test 1", "city": "Jaen", "price": "100000",
        "description": "t", "client_id": agent and client.id, "agent_id": agent.id,
    })
    moes.post("/buyers/create", {"name": f"{tag} COMPRADOR"})
    db.expire_all()
    prop = db.query(Property).filter_by(title=f"{tag} PROP").one()
    buyer = db.query(Buyer).filter_by(name=f"{tag} COMPRADOR").one()

    data = {"tag": tag, "agent": agent, "client": client, "property": prop, "buyer": buyer}
    yield data

    db.expire_all()
    db.query(Property).filter(Property.title.like(f"{tag}%")).delete(synchronize_session=False)
    db.query(Buyer).filter(Buyer.name.like(f"{tag}%")).delete(synchronize_session=False)
    db.query(Agent).filter(Agent.email.like("pytest.%@example.com")).delete(synchronize_session=False)
    db.query(ClientModel).filter(ClientModel.email.like("pytest.%@example.com")).delete(synchronize_session=False)
    db.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

PAGES = [
    "/properties", "/alerts", "/alerts?tab=buyers", "/clients",
    "/agents", "/visits", "/visits/select-property", "/reports",
    "/commercial-results", "/commercial-results?tab=evolucion", "/commercial-results?tab=compradores",
    "/commercial-results?tab=rendimiento&period_type=MONTHLY",
    "/commercial-results?tab=rendimiento&period_type=YEARLY",
    "/dashboard", "/report-logs", "/ai-logs-dashboard", "/auth",
]


@pytest.mark.parametrize("path", PAGES)
def test_paginas_renderizan_en_ambas_empresas(moyza, moes, path):
    assert moyza.get(path)[0] == 200
    assert moes.get(path)[0] == 200


def test_datos_de_moes_asignados_a_moes(moes_data, companies):
    moes_id = companies["MOES"].id
    assert moes_data["property"].company_id == moes_id
    assert moes_data["buyer"].company_id == moes_id
    assert [c.code for c in moes_data["agent"].companies] == ["MOES"]
    assert [c.code for c in moes_data["client"].companies] == ["MOES"]


@pytest.mark.parametrize("path", ["/properties", "/agents", "/clients", "/alerts?tab=buyers"])
def test_listados_aislados(moyza, moes, moes_data, path):
    tag = moes_data["tag"]
    assert tag in moes.get(path)[1]
    assert tag not in moyza.get(path)[1]


def test_detalle_por_id_cruzado_redirige(moyza, moes, moes_data):
    prop_id = moes_data["property"].id
    buyer_id = moes_data["buyer"].id
    assert moes.get(f"/properties/{prop_id}")[0] == 200
    assert moyza.get(f"/properties/{prop_id}")[0] == 302
    assert moes.get(f"/buyers/{buyer_id}")[0] == 200
    assert moyza.get(f"/buyers/{buyer_id}")[0] == 302
    assert moyza.get(f"/visits/new/{prop_id}")[0] == 302


def test_alta_cruzada_rechazada(moyza, db, moes_data):
    """Una propiedad de MOYZA no puede apuntar a un cliente de MOES."""
    from app.models.property import Property
    from app.models.agent import Agent
    moyza_agent = db.query(Agent).filter(Agent.companies.any(code="MOYZA")).first()
    moyza.post("/properties/create", {
        "title": "PYTEST-CRUZADA", "address": "x", "city": "y", "price": "1", "description": "d",
        "client_id": moes_data["client"].id, "agent_id": moyza_agent.id,
    })
    db.expire_all()
    assert db.query(Property).filter_by(title="PYTEST-CRUZADA").count() == 0


def test_agente_existente_se_anade_a_otra_empresa_sin_duplicar(moyza, db, moes_data):
    from app.models.agent import Agent
    agent = moes_data["agent"]
    status, _, headers = moyza.post("/agents/create", {"name": "Dup", "email": agent.email})
    assert status == 302
    db.expire_all()
    assert db.query(Agent).filter_by(email=agent.email).count() == 1
    assert sorted(c.code for c in agent.companies) == ["MOES", "MOYZA"]
    # Quitarlo de MOYZA conserva la ficha en MOES
    moyza.post(f"/agents/delete/{agent.id}", {})
    db.expire_all()
    assert [c.code for c in agent.companies] == ["MOES"]


def test_switch_company_valida_destino_y_empresa(moyza):
    status, _, headers = moyza.post("/switch-company", {"code": "MOES", "next": "/alerts?tab=buyers"})
    assert status == 303
    assert headers.get("location") == "/alerts?tab=buyers"
    assert "active_company=MOES" in headers.get("set-cookie", "")

    status, _, headers = moyza.post("/switch-company", {"code": "FAKE", "next": "/properties"})
    assert status == 303
    assert "active_company" not in headers.get("set-cookie", "")

    status, _, headers = moyza.post("/switch-company", {"code": "MOYZA", "next": "https://evil.com"})
    assert headers.get("location") == "/properties"


def test_api_sin_sesion_no_expone_datos():
    anon = Client("invalido", None)
    assert anon.get("/api/ai-logs/stats/summary")[0] == 401
    assert anon.get("/api/report-logs/stats")[0] == 401
    status, body, _ = anon.get("/api/alerts/unread-count")
    assert status == 200 and '"unread_count":0' in body.replace(" ", "")


def test_titulo_y_marca_siguen_a_la_empresa(moyza, moes):
    assert re.search(r"<title>\s*Compradores - MOES PREMIUM", moes.get("/alerts")[1])
    assert re.search(r"<title>\s*Compradores - MOYZA", moyza.get("/alerts")[1])


# ---------------------------------------------------------------------------
# Excepción acotada: pestaña "Propiedades de {otra empresa}" en /properties
# ---------------------------------------------------------------------------

def test_pestana_otra_empresa_lista_solo_inventario_disponible(moyza, moes, db, moes_data, companies):
    """MOYZA ve en solo lectura las propiedades activas y disponibles de MOES.

    El detalle sigue acotado a la empresa activa y una propiedad No
    disponible de la otra empresa no aparece.
    """
    from app.core.constants import PropertyStatus
    from app.models.property import Property

    tag = moes_data["tag"]
    prop = moes_data["property"]
    assert prop.status == PropertyStatus.ACTIVE and prop.is_available

    no_disponible = Property(
        title=f"{tag} NO-DISPONIBLE",
        address="Calle Test 2",
        city="Jaen",
        price=90000,
        status=PropertyStatus.ACTIVE,
        estado_inmueble="No disponible",
        company_id=companies["MOES"].id,
        agent_id=moes_data["agent"].id,
    )
    db.add(no_disponible)
    db.commit()

    status, body, _ = moyza.get(f"/properties?tab=other_company&company_id={companies['MOES'].id}")
    assert status == 200
    assert "Propiedades de MOES PREMIUM" in body
    assert "Solo lectura. Estas propiedades pertenecen a MOES PREMIUM." in body
    assert f"{tag} PROP" in body
    assert moes_data["agent"].name in body           # agente captador visible
    assert moes_data["client"].name not in body      # propietario nunca
    assert f"{tag} NO-DISPONIBLE" not in body
    assert f'href="/properties/{prop.id}"' not in body  # sin enlace al detalle

    # Buscador por título dentro de la pestaña
    status, body, _ = moyza.get(f"/properties?tab=other_company&search={urllib.parse.quote(tag)}")
    assert status == 200 and f"{tag} PROP" in body
    status, body, _ = moyza.get("/properties?tab=other_company&search=zzz-no-existe-zzz")
    assert status == 200 and f"{tag} PROP" not in body

    # El detalle y el alta de visita siguen fuera de alcance desde MOYZA
    assert moyza.get(f"/properties/{prop.id}")[0] == 302
    assert moyza.get(f"/visits/new/{prop.id}")[0] == 302

    # Desde MOES la pestaña muestra MOYZA, no su propio inventario
    status, body, _ = moes.get("/properties?tab=other_company")
    assert status == 200
    assert "Propiedades de MOYZA" in body
    assert f"{tag} PROP" not in body
