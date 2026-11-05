"""
Calle de las propiedades de la otra empresa en la pestaña "Propiedades de
{otra empresa}" (PLAN_CIERRES_MANUALES_Y_DIRECCIONES.md §2.2, fase C).

Regla: un usuario ve la calle de una propiedad de otra empresa solo si esa
empresa está entre las que puede usar (`request.state.allowed_companies`: las
del usuario y las de su ficha de agente). El admin ve todas. Si no puede, la
calle ni sale del servidor y la búsqueda por texto no la mira.

- Unitarios de `_readonly_property_rows` contra una SQLite en memoria con los
  modelos reales (entorno de tests/test_alert_search.py).
- Integración contra la app levantada (por defecto http://localhost:8000,
  configurable con MOYZA_TEST_BASE_URL) y su base de datos. Crean sus propios
  usuarios, agentes y una propiedad en MOES con nombres únicos y los borran
  al final. Si la app no responde, se omiten.

    docker exec moyza_backend python -m pytest tests/test_other_company_address.py -q
"""
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid

import pytest

from tests import test_alert_search

BASE_URL = os.getenv("MOYZA_TEST_BASE_URL", "http://localhost:8000")
ADMIN_EMAIL = os.getenv("MOYZA_TEST_ADMIN_EMAIL", "admin@moyza.com")


def _server_up() -> bool:
    try:
        urllib.request.urlopen(BASE_URL + "/", timeout=3)
        return True
    except Exception:
        return False


# Fixture del entorno SQLite en memoria (MOYZA, MOES; "Piso MOES" en MOES)
env = test_alert_search.env

integration = pytest.mark.skipif(
    not _server_up(),
    reason=f"La app no responde en {BASE_URL}; tests de integración omitidos",
)


# ---------------------------------------------------------------------------
# Unitarios: _readonly_property_rows
# ---------------------------------------------------------------------------

def _moes_query(env):
    from app.models.property import Property
    return env.db.query(Property).filter(Property.id == env.props["moes"].id)


def test_sin_direccion_la_fila_no_lleva_calle(env):
    from app.web.routes.properties import _readonly_property_rows

    rows = _readonly_property_rows(_moes_query(env), "", include_address=False)
    assert len(rows) == 1
    assert rows[0]["address"] is None
    assert rows[0]["city"] == "Jaen" and rows[0]["zona"] == "Centro"

    # Por defecto (y en "Resto de propiedades") la calle sigue viniendo
    rows = _readonly_property_rows(_moes_query(env), "")
    assert rows[0]["address"] == "Calle Piso MOES 1"


def test_sin_direccion_la_busqueda_no_mira_la_calle(env):
    from app.web.routes.properties import _readonly_property_rows

    assert _readonly_property_rows(_moes_query(env), "Calle Piso", include_address=False) == []
    assert len(_readonly_property_rows(_moes_query(env), "Calle Piso")) == 1
    # Título, población y referencia siguen buscándose
    assert len(_readonly_property_rows(_moes_query(env), "Piso MOES", include_address=False)) == 1
    assert len(_readonly_property_rows(_moes_query(env), "Jaen", include_address=False)) == 1


# ---------------------------------------------------------------------------
# Integración: la pestaña renderizada
# ---------------------------------------------------------------------------

class _Client:
    """GET con cookie de sesión y empresa activa, sin seguir redirecciones."""

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    def __init__(self, email: str, company: str = "MOYZA"):
        from app.core.security import create_access_token
        token = create_access_token({"sub": email})
        self.cookie = f"access_token={token}; active_company={company}"
        self.opener = urllib.request.build_opener(self._NoRedirect)

    def get(self, path):
        req = urllib.request.Request(BASE_URL + path)
        req.add_header("Cookie", self.cookie)
        try:
            resp = self.opener.open(req, timeout=20)
            return resp.status, resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")


@pytest.fixture(scope="module")
def data():
    """Agente solo de MOYZA, agente de MOYZA y MOES y una propiedad activa de MOES."""
    from app.db.session import SessionLocal  # modelos ya registrados en conftest.py
    from app.models.agent import Agent
    from app.models.company import Company
    from app.models.property import Property
    from app.models.role import Role
    from app.models.user import User

    db = SessionLocal()
    tag = f"pytest-calle-{uuid.uuid4().hex[:8]}"
    moyza = db.query(Company).filter(Company.code == "MOYZA").first()
    moes = db.query(Company).filter(Company.code == "MOES").first()
    agent_role = db.query(Role).filter(Role.name == "agent").first()

    created = []
    emails = {}
    for key, companies in (("moyza", [moyza]), ("dual", [moyza, moes])):
        email = f"{tag}-{key}@example.com"
        user = User(email=email, full_name=f"{tag} {key}", hashed_password="x", role=agent_role)
        user.companies.extend([moyza])
        agent = Agent(name=f"{tag} {key}", email=email)
        agent.companies.extend(companies)
        created += [user, agent]
        emails[key] = email

    # Solo letras: así la búsqueda y el filtro `street` no dependen de números
    street = "Calle Pytestoculta " + "".join(chr(ord("a") + int(c, 16)) for c in uuid.uuid4().hex[:6])
    prop = Property(
        title=f"{tag} PROP", address=f"{street}, 12", city="Jaén", zona=f"Zona {tag}",
        property_type="Piso", business_type="Venta", price=123456, status="Activa",
        company_id=moes.id,
    )
    db.add_all([*created, prop])
    db.commit()

    yield {"tag": tag, "emails": emails, "street": street, "property": prop, "moes": moes}

    db.delete(prop)
    for obj in created:
        db.delete(obj)
    db.commit()
    db.close()


def _tab(data, query=""):
    return f"/properties?tab=other_company&company_id={data['moes'].id}{query}"


def _search(text):
    return "&search=" + urllib.parse.quote(text)


@integration
def test_agente_solo_moyza_no_ve_la_calle_de_moes(data):
    status, html = _Client(data["emails"]["moyza"]).get(_tab(data, _search(data["tag"])))
    assert status == 200
    assert f"{data['tag']} PROP" in html          # la propiedad sale
    assert f"Zona {data['tag']}" in html          # con población y zona
    assert "Jaén" in html
    assert data["street"] not in html             # pero sin calle
    assert "Buscar por título, ciudad o referencia..." in html


@integration
def test_agente_solo_moyza_no_encuentra_la_propiedad_por_la_calle(data):
    status, html = _Client(data["emails"]["moyza"]).get(_tab(data, _search(data["street"])))
    assert status == 200
    assert f"{data['tag']} PROP" not in html
    # La calle solo aparece como eco de lo buscado (campo y estado vacío)
    assert "No se encontraron propiedades para" in html
    assert f">{data['street']}<" not in html


@integration
def test_admin_ve_la_calle_de_moes(data):
    status, html = _Client(ADMIN_EMAIL).get(_tab(data, _search(data["street"])))
    assert status == 200
    assert f"{data['tag']} PROP" in html
    assert f">{data['street']}<" in html


@integration
def test_agente_de_las_dos_empresas_ve_la_calle(data):
    status, html = _Client(data["emails"]["dual"]).get(_tab(data, _search(data["tag"])))
    assert status == 200
    assert f"{data['tag']} PROP" in html
    assert f">{data['street']}<" in html
