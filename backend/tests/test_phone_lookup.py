"""
Consulta de teléfono de propietario: pestaña "Consultar teléfono" de
Propiedades (app/services/phone_lookup_service.py y GET /properties con
tab=phone_check).

Reglas: solo coincide el número completo; cuentan las propiedades Activa,
Reservada y Pausada de las empresas del usuario; del propietario solo sale el nombre
enmascarado (ni nombre real, ni email, ni teléfono, ni id); cada consulta
válida deja `request.state.activity_path` para el registro de actividad.

- Servicio y ruta en proceso contra una SQLite en memoria con los modelos
  reales (entorno de tests/test_alert_search.py): no necesitan la app
  levantada. Los propietarios se crean dentro de cada test. La ruta solo se
  llama con tab=phone_check: el listado de las demás pestañas ordena con el
  operador `~` de PostgreSQL y no corre en SQLite.
- Integración contra la app levantada (por defecto http://localhost:8000,
  configurable con MOYZA_TEST_BASE_URL) y su base de datos: la consulta por
  HTTP y su fila en el registro de actividad. Crean su propio agente,
  propietario y propiedad con nombres únicos y los borran al final. Si la app
  no responde, se omiten.

    docker exec moyza_backend python -m pytest tests/test_phone_lookup.py -q
"""
import asyncio
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

import pytest

from app.core.constants import PropertyStatus
from app.core.phone import PHONE_ERROR_MESSAGE
from tests import test_alert_search

BASE_URL = os.getenv("MOYZA_TEST_BASE_URL", "http://localhost:8000")
ADMIN_EMAIL = os.getenv("MOYZA_TEST_ADMIN_EMAIL", "admin@moyza.com")


def _server_up() -> bool:
    try:
        urllib.request.urlopen(BASE_URL + "/", timeout=3)
        return True
    except Exception:
        return False


# Fixture del entorno SQLite en memoria (MOYZA: Piso Centro, Piso Bea, Casa Cara; MOES: Piso MOES)
env = test_alert_search.env

integration = pytest.mark.skipif(
    not _server_up(),
    reason=f"La app no responde en {BASE_URL}; tests de integración omitidos",
)

OWNER_NAME = "María Navarro López"
OWNER_EMAIL = "maria.navarro@example.com"
OWNER_PHONE = "34600112233"

RESULT_KEYS = {
    "id", "title", "referencia", "address", "city", "zona", "property_type", "business_type",
    "price", "moneda", "status", "agent_name", "company", "owner_masked",
}


def _owner(env, phone=OWNER_PHONE, name=OWNER_NAME, email=OWNER_EMAIL, props=("ana",)):
    """Propietario con ese teléfono (tal cual, texto libre) asignado a las propiedades dadas."""
    from app.models.client import Client

    client = Client(name=name, email=email, phone=phone)
    env.db.add(client)
    env.db.flush()
    for key in props:
        env.props[key].client_id = client.id
    env.db.commit()
    return client


def _lookup(env, phone, companies=None):
    """Consulta en las empresas dadas (por defecto las dos, como un admin)."""
    from app.services.phone_lookup_service import lookup_properties_by_phone
    companies = companies if companies is not None else [env.moyza, env.moes]
    return lookup_properties_by_phone(env.db, phone, [c.id for c in companies])


def _titles(rows):
    return [row["title"] for row in rows]


# ---------------------------------------------------------------------------
# mask_name
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name, expected", [
    ("María Navarro López", "Mar*** Na*** Ló***"),
    ("  María   Navarro  ", "Mar*** Na***"),
    ("Ana", "An***"),                 # nunca la palabra entera
    ("Jo Li", "J*** L***"),
    ("A B", "A*** B***"),             # una letra: esa letra y la máscara
    ("Li de la Torre", "L*** d*** l*** To***"),
    ("Inmobiliaria", "Inm***"),
    ("", ""),
    ("   ", ""),
    (None, ""),
])
def test_mask_name(name, expected):
    from app.services.phone_lookup_service import mask_name
    assert mask_name(name) == expected


def test_mask_name_no_revela_la_longitud():
    from app.services.phone_lookup_service import mask_name
    assert mask_name("Maximiliano") == mask_name("Maxi") == "Max***"


# ---------------------------------------------------------------------------
# phone_candidates
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("34600112233", {"34600112233"}),
    ("600 11 22 33", {"34600112233"}),
    ("+34 600-112-233", {"34600112233"}),
    ("0034600112233", {"34600112233"}),
    ("+41 79 123 45 67", {"41791234567"}),
    ("600112233 / 953112233", {"34600112233", "34953112233"}),
    ("600112233, 953112233", {"34600112233", "34953112233"}),
    ("600112233; 953112233 | 0034 611 22 33 44", {"34600112233", "34953112233", "34611223344"}),
    ("600 11 22 33 y 953 11 22 33", {"34600112233", "34953112233"}),
    # Con separador, el trozo completo cuenta aunque todo junto también parezca un número
    ("600112233 / 12", {"34600112233", "3460011223312"}),
    ("600.112.233", {"34600112233"}),
    ("600,112,233", {"34600112233"}),         # trozos incompletos: queda el valor entero
    ("ext. 12", set()),
    ("no tiene", set()),
    ("", set()),
    (None, set()),
])
def test_phone_candidates(raw, expected):
    from app.services.phone_lookup_service import phone_candidates
    assert phone_candidates(raw) == expected


# ---------------------------------------------------------------------------
# lookup_properties_by_phone
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("stored", [
    "34600112233", "600112233", "600 11 22 33", "+34 600-112-233", "0034600112233", "(+34) 600.112.233",
])
def test_el_formato_guardado_no_importa(env, stored):
    _owner(env, phone=stored)

    for asked in ("34600112233", "600112233", "+34 600 11 22 33", "0034600112233"):
        assert _titles(_lookup(env, asked)) == ["Piso Centro"], (stored, asked)


def test_campo_con_dos_telefonos(env):
    _owner(env, phone="600112233 / 953112233")

    assert _titles(_lookup(env, "600112233")) == ["Piso Centro"]
    assert _titles(_lookup(env, "953 11 22 33")) == ["Piso Centro"]
    # La unión de los dos números no es un teléfono
    assert _lookup(env, "600112233953112233") == []


@pytest.mark.parametrize("asked", [
    "600112",          # parcial: los primeros dígitos
    "112233",          # parcial: los últimos
    "60011223",        # le falta un dígito
    "6001122334",      # le sobra un dígito
    "6001",            # demasiado corto para ser un teléfono
    "699000111",       # completo, pero de nadie
    "+41600112233",    # mismo número local, otro país
    "",
    None,
    "abc",
])
def test_numero_parcial_o_inexistente_no_encuentra_nada(env, asked):
    _owner(env)
    assert _lookup(env, asked) == []


def test_solo_cuentan_las_propiedades_en_cartera(env):
    _owner(env, props=("ana", "bea", "cara"))

    expected = {
        PropertyStatus.ACTIVE: True,
        PropertyStatus.RESERVED: True,
        PropertyStatus.PAUSED: True,
        PropertyStatus.SOLD: False,
        PropertyStatus.WITHDRAWN: False,
        PropertyStatus.ARCHIVED: False,
    }
    for status, in_portfolio in expected.items():
        env.props["ana"].status = status
        env.db.commit()
        titles = _titles(_lookup(env, OWNER_PHONE))
        assert ("Piso Centro" in titles) is in_portfolio, status
        # Las otras dos (Activa) salen siempre
        assert {"Piso Bea", "Casa Cara"} <= set(titles)


def test_propietario_sin_nada_en_cartera_no_sale(env):
    _owner(env)
    env.props["ana"].status = PropertyStatus.SOLD
    env.db.commit()

    assert _lookup(env, OWNER_PHONE) == []


def test_no_disponible_con_status_activa_sigue_en_cartera(env):
    _owner(env)
    env.props["ana"].estado_inmueble = "No disponible"
    env.db.commit()

    assert _titles(_lookup(env, OWNER_PHONE)) == ["Piso Centro"]


def test_salen_las_propiedades_de_las_dos_empresas(env):
    _owner(env, props=("cara", "ana", "moes"))

    rows = _lookup(env, OWNER_PHONE)
    # Orden: empresa (MOYZA primero) y título
    assert _titles(rows) == ["Casa Cara", "Piso Centro", "Piso MOES"]
    assert [row["company"] for row in rows] == [
        {"name": "MOYZA", "primary_color": "#000000"},
        {"name": "MOYZA", "primary_color": "#000000"},
        {"name": "MOES PREMIUM", "primary_color": "#8A6D1F"},
    ]


def test_solo_salen_las_empresas_del_usuario(env):
    _owner(env, props=("cara", "ana", "moes"))

    assert _titles(_lookup(env, OWNER_PHONE, [env.moyza])) == ["Casa Cara", "Piso Centro"]
    assert _titles(_lookup(env, OWNER_PHONE, [env.moes])) == ["Piso MOES"]
    # Sin empresas no hay resultados
    assert _lookup(env, OWNER_PHONE, []) == []


def test_propietario_solo_de_la_otra_empresa_no_se_encuentra(env):
    _owner(env, props=("moes",))

    assert _lookup(env, OWNER_PHONE, [env.moyza]) == []
    assert _titles(_lookup(env, OWNER_PHONE, [env.moes])) == ["Piso MOES"]


def test_dos_propietarios_con_el_mismo_telefono(env):
    _owner(env, props=("ana",))
    _owner(env, name="Pedro Ruiz", email="pedro@example.com", phone="600 11 22 33", props=("moes",))
    _owner(env, name="Otra Persona", email="otra@example.com", phone="699000111", props=("bea",))

    rows = _lookup(env, OWNER_PHONE)
    assert [(row["title"], row["owner_masked"]) for row in rows] == [
        ("Piso Centro", "Mar*** Na*** Ló***"),
        ("Piso MOES", "Ped*** Ru***"),
    ]


def test_forma_de_la_fila_y_sin_datos_del_cliente(env):
    _owner(env, props=("ana",))
    prop = env.props["ana"]
    prop.referencia = "REF-77"
    prop.moneda = "EUR"
    prop.address = "Calle Fuente del Peral, 8"
    env.db.commit()

    rows = _lookup(env, OWNER_PHONE)
    assert len(rows) == 1
    row = rows[0]

    assert set(row) == RESULT_KEYS
    assert row == {
        "id": prop.id,
        "title": "Piso Centro",
        "referencia": "REF-77",
        "address": "Calle Fuente del Peral",     # solo la calle
        "city": "Jaen",
        "zona": "Centro",
        "property_type": "Piso",
        "business_type": "Venta",
        "price": 120000,
        "moneda": "EUR",
        "status": PropertyStatus.ACTIVE,
        "agent_name": "Agente Ana",
        "company": {"name": "MOYZA", "primary_color": "#000000"},
        "owner_masked": "Mar*** Na*** Ló***",
    }

    # Ni nombre real, ni email, ni teléfono guardado, ni id del cliente
    assert not {"client_id", "owner_name", "client", "phone", "email", "name"} & set(row)
    dumped = repr(row)
    for secret in (OWNER_NAME, "María", "Navarro", "López", OWNER_EMAIL, OWNER_PHONE, "600112233"):
        assert secret not in dumped
    assert set(row["company"]) == {"name", "primary_color"}


def test_propiedad_sin_agente(env):
    _owner(env)
    env.props["ana"].agent_id = None
    env.db.commit()

    rows = _lookup(env, OWNER_PHONE)
    assert _titles(rows) == ["Piso Centro"]
    assert rows[0]["agent_name"] is None


# ---------------------------------------------------------------------------
# Ruta: GET /properties?tab=phone_check
# ---------------------------------------------------------------------------

def _page(env, user, tab="phone_check", country_code=None, number=None, other_code=None, company=None):
    """GET /properties en proceso. Devuelve (request, response)."""
    from app.web.routes.properties import properties_page

    request = test_alert_search._request(env, user, "/properties", company=company)
    response = asyncio.run(properties_page(
        request, tab=tab, filtro="activas", company_id=None,
        phone_country_code=country_code, phone_number=number,
        phone_country_code_other=other_code, db=env.db,
    ))
    return request, response


def _activity_path(request):
    return getattr(request.state, "activity_path", None)


def test_ruta_agente_consulta_un_numero_valido(env):
    _owner(env, phone="600 11 22 33", props=("bea", "moes"))

    # Ana (agente de MOYZA) consulta: ve la propiedad de Bea, no la de MOES
    request, response = _page(env, env.users["ana"], country_code="34", number="600 11 22 33")

    assert response.status_code == 200
    assert response.context["tab"] == "phone_check"
    check = response.context["phone_check"]
    assert set(check) == {"searched", "error", "phone", "country_code", "local_number", "results",
                          "company_names"}
    assert check["company_names"] == ["MOYZA"]
    assert check["searched"] is True
    assert check["error"] is None
    assert check["phone"] == "34600112233"
    assert (check["country_code"], check["local_number"]) == ("34", "600112233")
    assert _titles(check["results"]) == ["Piso Bea"]
    assert all(set(row) == RESULT_KEYS for row in check["results"])
    assert check["results"][0]["owner_masked"] == "Mar*** Na*** Ló***"

    assert _activity_path(request) == "/properties?tab=phone_check · tel 34600112233 · 1 propiedades"
    assert "Piso MOES" not in response.body.decode()

    # El nombre real y el email del propietario no llegan a la página
    html = response.body.decode()
    assert OWNER_NAME not in html and "Navarro" not in html and OWNER_EMAIL not in html


def test_ruta_solo_las_empresas_permitidas_del_usuario(env):
    _owner(env, props=("bea", "moes"))

    def titles(user, company, allowed):
        from app.web.routes.properties import properties_page
        request = test_alert_search._request(env, user, "/properties", company=company)
        request.state.allowed_companies = allowed
        response = asyncio.run(properties_page(
            request, tab="phone_check", filtro="activas", company_id=None,
            phone_country_code="34", phone_number="600112233",
            phone_country_code_other=None, db=env.db,
        ))
        return _titles(response.context["phone_check"]["results"])

    ana = env.users["ana"]
    # Agente solo de MOYZA / solo de MOES: lo de su empresa
    assert titles(ana, env.moyza, [env.moyza]) == ["Piso Bea"]
    assert titles(ana, env.moes, [env.moes]) == ["Piso MOES"]
    # Quien puede usar las dos (admin, agente en ambas) ve las dos, sea cual sea la activa
    both = [env.moyza, env.moes]
    assert titles(env.admin, env.moyza, both) == ["Piso Bea", "Piso MOES"]
    assert titles(env.admin, env.moes, both) == ["Piso Bea", "Piso MOES"]


def test_ruta_numero_sin_propiedades_tambien_se_registra(env):
    _owner(env)

    request, response = _page(env, env.users["ana"], country_code="34", number="699000111")

    check = response.context["phone_check"]
    assert check["searched"] is True and check["error"] is None
    assert check["phone"] == "34699000111"
    assert check["results"] == []
    assert _activity_path(request) == "/properties?tab=phone_check · tel 34699000111 · 0 propiedades"


def test_ruta_el_numero_puede_traer_el_indicativo(env):
    _owner(env)

    # Sin selector (enlace a mano) y con el indicativo repetido en el número
    for country_code, number in ((None, "600112233"), ("34", "+34 600 112 233"), ("34", "0034600112233")):
        _request, response = _page(env, env.users["ana"], country_code=country_code, number=number)
        check = response.context["phone_check"]
        assert check["phone"] == "34600112233", (country_code, number)
        assert _titles(check["results"]) == ["Piso Centro"]


@pytest.mark.parametrize("number", ["6001", "600", "1234567890123", "abc"])
def test_ruta_numero_invalido_da_error_y_no_consulta(env, number):
    _owner(env)

    request, response = _page(env, env.users["ana"], country_code="34", number=number)

    assert response.status_code == 200
    check = response.context["phone_check"]
    assert check["searched"] is False
    assert check["error"] == PHONE_ERROR_MESSAGE
    assert check["phone"] is None
    assert check["results"] == []
    # El formulario se repinta con lo que llegó
    assert (check["country_code"], check["local_number"]) == ("34", number)
    assert _activity_path(request) is None


def test_ruta_indicativo_escrito_a_mano(env):
    from app.core.constants import PhoneCountryCodes
    from app.core.phone import OTHER_CODE_ERROR_MESSAGE

    _owner(env, phone="+41 79 123 45 67")

    request, response = _page(env, env.users["ana"], country_code=PhoneCountryCodes.OTHER,
                              number="79 123 45 67", other_code="41")
    check = response.context["phone_check"]
    assert check["searched"] is True
    assert check["phone"] == "+41791234567"
    assert (check["country_code"], check["local_number"]) == ("41", "791234567")
    assert _titles(check["results"]) == ["Piso Centro"]
    assert _activity_path(request) == "/properties?tab=phone_check · tel +41791234567 · 1 propiedades"

    # Indicativo que no existe: error y se repinta "Otro…" con lo escrito
    request, response = _page(env, env.users["ana"], country_code=PhoneCountryCodes.OTHER,
                              number="791234567", other_code="999")
    check = response.context["phone_check"]
    assert check["searched"] is False
    assert check["error"] == OTHER_CODE_ERROR_MESSAGE
    assert (check["country_code"], check["local_number"]) == ("999", "791234567")
    assert _activity_path(request) is None


def test_ruta_pestana_sin_numero_no_consulta(env):
    _owner(env)

    for number in (None, "", "   "):
        request, response = _page(env, env.users["ana"], country_code="34", number=number)
        assert response.context["tab"] == "phone_check"
        assert response.context["phone_check"] == {
            "searched": False, "error": None, "phone": None,
            "country_code": "34", "local_number": "", "results": [],
            "company_names": ["MOYZA"],
        }
        assert _activity_path(request) is None


def test_ruta_la_pestana_vale_para_agente_y_admin(env):
    for user in (env.users["ana"], env.admin):
        _request, response = _page(env, user)
        assert response.status_code == 200
        assert response.context["tab"] == "phone_check"


# ---------------------------------------------------------------------------
# Registro de actividad: ActivityMiddleware usa request.state.activity_path
# ---------------------------------------------------------------------------

def _logged_paths(monkeypatch, route):
    """Paths que guardaría ActivityMiddleware para GET /consulta con esa ruta.

    Se monta el middleware debajo de otro BaseHTTPMiddleware, como en la app
    (ActivityMiddleware envuelve a FlashMiddleware y AuthMiddleware).
    """
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.routing import Route
    from starlette.testclient import TestClient

    from app.web.middleware import activity

    logged = []
    monkeypatch.setattr(activity, "_write_log", lambda **kwargs: logged.append(kwargs["path"]))

    class Inner(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            return await call_next(request)

    app = Starlette(
        routes=[Route("/consulta", route)],
        middleware=[Middleware(activity.ActivityMiddleware), Middleware(Inner)],
    )
    assert TestClient(app).get("/consulta").status_code == 200
    return logged


def test_middleware_usa_activity_path_si_la_ruta_lo_deja(monkeypatch):
    from starlette.responses import PlainTextResponse

    async def route(request):
        request.state.activity_path = "/properties?tab=phone_check · tel 34600112233 · 2 propiedades"
        return PlainTextResponse("ok")

    assert _logged_paths(monkeypatch, route) == [
        "/properties?tab=phone_check · tel 34600112233 · 2 propiedades"
    ]


def test_middleware_sin_activity_path_guarda_la_ruta(monkeypatch):
    from starlette.responses import PlainTextResponse

    async def route(request):
        return PlainTextResponse("ok")

    assert _logged_paths(monkeypatch, route) == ["/consulta"]


# ---------------------------------------------------------------------------
# Integración: la consulta por HTTP y su fila en /activity-logs
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

    def get(self, path, params=None):
        url = BASE_URL + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url)
        req.add_header("Cookie", self.cookie)
        try:
            resp = self.opener.open(req, timeout=20)
            return resp.status, resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")


@pytest.fixture(scope="module")
def data():
    """Agente solo de MOYZA y un propietario con una propiedad activa en MOES."""
    from app.db.session import SessionLocal  # modelos ya registrados en conftest.py
    from app.models.agent import Agent
    from app.models.client import Client
    from app.models.company import Company
    from app.models.property import Property
    from app.models.role import Role
    from app.models.user import User
    from app.models.user_activity_log import UserActivityLog

    db = SessionLocal()
    tag = f"pytest-tel-{uuid.uuid4().hex[:8]}"
    moyza = db.query(Company).filter(Company.code == "MOYZA").first()
    moes = db.query(Company).filter(Company.code == "MOES").first()
    agent_role = db.query(Role).filter(Role.name == "agent").first()

    email = f"{tag}@example.com"
    user = User(email=email, full_name=f"{tag} agente", hashed_password="x", role=agent_role)
    user.companies.append(moyza)
    agent = Agent(name=f"{tag} agente", email=email)
    agent.companies.append(moyza)

    # Número único por ejecución, guardado en texto libre con espacios
    local = "69" + "".join(random.choice("0123456789") for _ in range(7))
    owner_name = f"Propietariosecreto Apellido{tag[-8:]}"
    owner = Client(name=owner_name, email=f"{tag}-owner@example.com",
                   phone=f"{local[:3]} {local[3:6]} {local[6:]}")
    prop = Property(
        title=f"{tag} PROP", address="Calle Pytest Consulta, 3", city="Jaén", zona=f"Zona {tag}",
        property_type="Piso", business_type="Venta", price=123456, status="Activa",
        company_id=moes.id, client=owner,
    )
    db.add_all([user, agent, owner, prop])
    db.commit()

    yield {"db": db, "tag": tag, "email": email, "user_id": user.id, "local": local,
           "phone": "34" + local, "owner_name": owner_name}

    db.rollback()
    db.query(UserActivityLog).filter(UserActivityLog.user_id == user.id).delete()
    db.delete(prop)
    db.flush()
    for obj in (owner, agent, user):
        db.delete(obj)
    db.commit()
    db.close()


def _logged_path(data, contains, timeout=5.0):
    """Path de la última fila de actividad del agente que contiene ese texto, o None.

    El middleware escribe el log después de responder (tarea en segundo
    plano): se espera un poco a que aparezca.
    """
    from app.models.user_activity_log import UserActivityLog

    db = data["db"]
    deadline = time.monotonic() + timeout
    while True:
        db.rollback()  # nueva transacción: ver lo que acaba de escribir la app
        row = (
            db.query(UserActivityLog.path)
            .filter(UserActivityLog.user_id == data["user_id"], UserActivityLog.path.contains(contains))
            .order_by(UserActivityLog.id.desc())
            .first()
        )
        if row or time.monotonic() >= deadline:
            return row[0] if row else None
        time.sleep(0.2)


@integration
def test_http_la_consulta_queda_en_el_registro_de_actividad(data):
    # Agente solo de MOYZA, con MOYZA activa: la propiedad es de MOES
    status, html = _Client(data["email"]).get("/properties", {
        "tab": "phone_check", "phone_country_code": "34", "phone_number": data["local"],
    })
    assert status == 200
    # Ni el nombre real ni el email del propietario llegan a la página
    assert data["owner_name"] not in html
    assert "Propietariosecreto" not in html
    assert f"{data['tag']}-owner@example.com" not in html
    # La propiedad es de MOES y el agente solo de MOYZA: no la ve
    assert f"{data['tag']} PROP" not in html

    assert _logged_path(data, data["phone"]) == (
        f"/properties?tab=phone_check · tel {data['phone']} · 0 propiedades"
    )

    # El admin (todas las empresas) sí la ve, con MOYZA activa
    status, html = _Client(ADMIN_EMAIL).get("/properties", {
        "tab": "phone_check", "phone_country_code": "34", "phone_number": data["local"],
    })
    assert status == 200
    assert f"{data['tag']} PROP" in html
    assert data["owner_name"] not in html


@integration
def test_http_numero_invalido_u_otra_pestana_no_registran_consulta(data):
    client = _Client(data["email"])

    # Número incompleto: error, sin consulta
    status, _html = client.get("/properties", {
        "tab": "phone_check", "phone_country_code": "34", "phone_number": "6001",
    })
    assert status == 200

    # Otra pestaña con los campos del teléfono: se ignoran
    marker = "".join(random.choice("0123456789") for _ in range(9))
    status, _html = client.get("/properties", {
        "tab": "others", "phone_country_code": "34", "phone_number": marker,
    })
    assert status == 200

    # Las dos peticiones se registran con la ruta de siempre
    assert _logged_path(data, "/properties") is not None
    assert _logged_path(data, marker, timeout=1.0) is None
    assert _logged_path(data, "tel 346001", timeout=0.5) is None
