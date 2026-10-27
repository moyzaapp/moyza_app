"""
Teléfono del propietario en el listado de propiedades: columna solo en
"Mis propiedades" (y búsqueda por él); "Resto de propiedades" y
"Propiedades de {otra empresa}" siguen sin datos del propietario.

Integración contra la app levantada (patrón de test_buyer_business_type.py,
se omite si la app no responde): crea un propietario y una propiedad de
prueba en MOYZA y los borra al terminar.

Ejecución dentro del contenedor:
    docker exec moyza_backend python -m pytest tests/test_property_owner_phone.py -q
"""
import os
import urllib.error
import urllib.parse
import urllib.request

import pytest

BASE_URL = os.getenv("MOYZA_TEST_BASE_URL", "http://localhost:8000")
ADMIN_EMAIL = os.getenv("MOYZA_TEST_ADMIN_EMAIL", "admin@moyza.com")
TAG = "PYTEST-TEL-PROPIETARIO"
OWNER_PHONE = "34699123457"
OWNER_PHONE_DISPLAY = "+34 699 123 457"


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


def _owned_property(db, title, agent_id=None):
    """Propiedad activa y disponible en MOYZA con un propietario con teléfono."""
    from app.core.constants import PropertyStatus
    from app.models.client import Client
    from app.models.property import Property

    moyza = _company(db, "MOYZA")
    client = Client(name=f"{TAG} DUEÑO", phone=OWNER_PHONE)
    client.companies.append(moyza)
    prop = Property(
        title=title,
        city="Jaén",
        price=123456,
        status=PropertyStatus.ACTIVE,
        company_id=moyza.id,
        client=client,
        agent_id=agent_id,
    )
    db.add_all([client, prop])
    db.commit()
    return prop


def _agent_user_email(db, company_code):
    """Email de un usuario no admin con agente en la empresa (rol agente)."""
    from app.models.agent import Agent
    from app.models.user import User

    company = _company(db, company_code)
    for user in db.query(User).all():
        if user.role and user.role.name.lower() == "admin":
            continue
        agent = db.query(Agent).filter(Agent.email == user.email).first()
        if agent and agent.companies and any(c.id == company.id for c in agent.companies):
            return user.email
    pytest.skip(f"No hay usuarios agente en {company_code}")


def test_mis_propiedades_muestra_telefono_del_propietario(db):
    title = f"{TAG} MIS"
    _owned_property(db, title)

    status, html = _Client("MOYZA").get("/properties", {"tab": "mine"})
    assert status == 200
    assert "Teléfono propietario" in html
    assert title in html
    assert OWNER_PHONE_DISPLAY in html
    assert f'href="tel:+{OWNER_PHONE}"' in html
    assert f"https://wa.me/{OWNER_PHONE}" in html


def test_buscar_por_telefono_del_propietario(db):
    title = f"{TAG} BUSCAR"
    _owned_property(db, title)
    client = _Client("MOYZA")

    for search in (OWNER_PHONE, "699 123 457", "+34 699-123-457"):
        status, html = client.get("/properties", {"tab": "mine", "search": search})
        assert status == 200
        assert title in html, search


def test_otra_empresa_no_muestra_telefono(db):
    title = f"{TAG} OTRA EMPRESA"
    _owned_property(db, title)
    moyza = _company(db, "MOYZA")

    status, html = _Client("MOES").get("/properties", {"tab": "other_company", "company_id": moyza.id})
    assert status == 200
    assert title in html  # la fila se pinta...
    assert "Teléfono propietario" not in html  # ...pero sin datos del propietario
    assert OWNER_PHONE_DISPLAY not in html
    assert OWNER_PHONE not in html
    assert "wa.me" not in html


def test_resto_de_propiedades_no_muestra_telefono(db):
    title = f"{TAG} RESTO"
    _owned_property(db, title, agent_id=None)  # sin agente: entra en "Resto" de cualquier agente

    status, html = _Client("MOYZA", _agent_user_email(db, "MOYZA")).get("/properties", {"tab": "others"})
    assert status == 200
    assert title in html
    assert "Teléfono propietario" not in html
    assert OWNER_PHONE_DISPLAY not in html
    assert OWNER_PHONE not in html
    assert "wa.me" not in html
