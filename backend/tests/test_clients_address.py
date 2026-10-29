"""
Clientes: columna "Dirección del inmueble" (sin número) y visibilidad por agente.

- El agente solo ve clientes con propiedades suyas en la empresa activa, y en
  la columna solo las direcciones de esas propiedades.
- El admin ve todos los clientes de la empresa activa y todas sus direcciones.
- Un cliente de la otra empresa no aparece.
- El buscador también encuentra por dirección (sobre la dirección completa).

Integración contra la app levantada (patrón de test_property_owner_phone.py,
se omite si la app no responde): crea clientes y propiedades de prueba en
MOYZA/MOES y los borra al terminar.

Ejecución dentro del contenedor:
    docker exec moyza_backend python -m pytest tests/test_clients_address.py -q
"""
import os
import re
import urllib.error
import urllib.parse
import urllib.request

import pytest

BASE_URL = os.getenv("MOYZA_TEST_BASE_URL", "http://localhost:8000")
ADMIN_EMAIL = os.getenv("MOYZA_TEST_ADMIN_EMAIL", "admin@moyza.com")
TAG = "PYTEST-DIR-CLIENTE"
AGENT_A = 6    # agente MOYZA
AGENT_B = 12   # otro agente
ADDRESS_A = "Calle Fuente del Peral, 8"
ADDRESS_B = "Avenida Pytest Otro Agente, 21"
ADDRESS_ARCHIVED = "Calle Pytest Archivada, 3"


def _server_up() -> bool:
    try:
        urllib.request.urlopen(BASE_URL + "/", timeout=3)
        return True
    except Exception:
        return False


class _Client:
    """Peticiones con cookies de sesión y empresa, sin seguir redirecciones."""

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    def __init__(self, company: str, email: str = ADMIN_EMAIL):
        from app.core.security import create_access_token
        token = create_access_token({"sub": email})
        self.cookie = f"access_token={token}; active_company={company}"
        self.opener = urllib.request.build_opener(self._NoRedirect)

    def get(self, path, params=None):
        url = BASE_URL + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url)
        req.add_header("Cookie", self.cookie)
        try:
            resp = self.opener.open(req, timeout=20)
            return resp.status, resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8")


@pytest.fixture
def db():
    if not _server_up():
        pytest.skip(f"La app no responde en {BASE_URL}; tests de integración omitidos")

    from app.db.session import SessionLocal
    from app.models.client import Client
    from app.models.property import Property

    def cleanup():
        session.rollback()
        for prop in session.query(Property).filter(Property.title.like(f"{TAG}%")).all():
            session.delete(prop)
        session.flush()
        for client in session.query(Client).filter(Client.name.like(f"{TAG}%")).all():
            session.delete(client)
        session.commit()

    session = SessionLocal()
    cleanup()
    yield session

    cleanup()
    session.close()


def _company(db, code):
    from app.models.company import Company
    return db.query(Company).filter(Company.code == code).first()


def _agent_email(db, agent_id):
    from app.models.agent import Agent
    from app.models.user import User

    agent = db.get(Agent, agent_id)
    if not agent or not db.query(User).filter(User.email == agent.email).first():
        pytest.skip(f"No existe el usuario del agente {agent_id}")
    return agent.email


def _client(db, name, company_code):
    from app.models.client import Client

    client = Client(name=f"{TAG} {name}", phone="600000000")
    client.companies.append(_company(db, company_code))
    db.add(client)
    db.flush()
    return client


def _property(db, client, title, address, agent_id, company_code="MOYZA", status=None):
    from app.core.constants import PropertyStatus
    from app.models.property import Property

    prop = Property(
        title=f"{TAG} {title}",
        address=address,
        city="Jaén",
        price=100000,
        status=status or PropertyStatus.ACTIVE,
        company_id=_company(db, company_code).id,
        client=client,
        agent_id=agent_id,
    )
    db.add(prop)
    return prop


@pytest.fixture
def data(db):
    """Clientes de prueba:

    - MIXTO: una propiedad del agente A y otra del agente B (MOYZA).
    - SOLO B: solo propiedades del agente B (MOYZA).
    - MOES: cliente solo de MOES con propiedad del agente A en MOES.
    """
    from app.core.constants import PropertyStatus

    mixed = _client(db, "MIXTO", "MOYZA")
    _property(db, mixed, "A", ADDRESS_A, AGENT_A)
    _property(db, mixed, "B", ADDRESS_B, AGENT_B)
    _property(db, mixed, "ARCHIVADA", ADDRESS_ARCHIVED, AGENT_A, status=PropertyStatus.ARCHIVED)

    only_b = _client(db, "SOLO B", "MOYZA")
    _property(db, only_b, "SOLO B", "Calle Pytest Solo B, 5", AGENT_B)

    moes = _client(db, "MOES", "MOES")
    _property(db, moes, "MOES", "Calle Pytest Moes, 9", AGENT_A, company_code="MOES")

    db.commit()
    return {"mixed": mixed, "only_b": only_b, "moes": moes}


def test_agente_solo_ve_sus_clientes_y_sus_direcciones(db, data):
    status, html = _Client("MOYZA", _agent_email(db, AGENT_A)).get("/clients")
    assert status == 200
    assert "Dirección del inmueble" in html

    assert f"{TAG} MIXTO" in html
    assert f"{TAG} SOLO B" not in html  # solo tiene propiedades de otro agente
    assert f"{TAG} MOES" not in html    # cliente de la otra empresa

    # Dirección sin número, enlazada a la ficha
    assert "Calle Fuente del Peral" in html
    assert ", 8" not in html
    prop_a = next(p for p in data["mixed"].properties if p.title.endswith(" A"))
    assert f'href="/properties/{prop_a.id}"' in html

    # La propiedad del otro agente no sale; la archivada sí, con marca
    # (decisión 2026-10-28) y después de las activas
    assert "Avenida Pytest Otro Agente" not in html
    assert "Calle Pytest Archivada" in html
    assert re.search(r">\s*Archivada\s*<", html), "falta la marca Archivada"
    assert html.index("Calle Fuente del Peral") < html.index("Calle Pytest Archivada")


def test_admin_ve_todos_los_clientes_de_la_empresa(db, data):
    status, html = _Client("MOYZA").get("/clients")
    assert status == 200

    assert f"{TAG} MIXTO" in html
    assert f"{TAG} SOLO B" in html
    assert f"{TAG} MOES" not in html

    assert "Calle Fuente del Peral" in html
    assert "Avenida Pytest Otro Agente" in html
    assert "Calle Pytest Solo B" in html
    assert "Calle Pytest Archivada" in html
    assert re.search(r">\s*Archivada\s*<", html), "falta la marca Archivada"
    assert ", 8" not in html and ", 21" not in html


def test_otra_empresa_no_muestra_clientes_de_moyza(db, data):
    status, html = _Client("MOES").get("/clients")
    assert status == 200
    assert f"{TAG} MOES" in html
    assert "Calle Pytest Moes" in html
    assert f"{TAG} MIXTO" not in html
    assert f"{TAG} SOLO B" not in html


def test_buscar_por_direccion(db, data):
    agent = _Client("MOYZA", _agent_email(db, AGENT_A))
    admin = _Client("MOYZA")

    prop_a = next(p for p in data["mixed"].properties if p.title.endswith(" A"))

    # Sobre la dirección completa (con número)
    for client in (agent, admin):
        for search in ("Fuente", "fuente del peral, 8"):
            status, html = client.get("/clients", {"search": search})
            assert status == 200
            assert f"{TAG} MIXTO" in html, search
            # Una sola fila del cliente aunque tenga varias propiedades
            assert html.count(f'href="/properties/{prop_a.id}"') == 1

    # El agente no encuentra clientes por direcciones de propiedades ajenas
    status, html = agent.get("/clients", {"search": "Pytest Solo B"})
    assert status == 200
    assert f"{TAG} SOLO B" not in html
    status, html = agent.get("/clients", {"search": "Pytest Otro Agente"})
    assert f"{TAG} MIXTO" not in html

    # El admin sí
    status, html = admin.get("/clients", {"search": "Pytest Solo B"})
    assert f"{TAG} SOLO B" in html

    # La dirección de una propiedad archivada también encuentra al cliente
    status, html = agent.get("/clients", {"search": "Pytest Archivada"})
    assert status == 200
    assert f"{TAG} MIXTO" in html
