"""
Operación obligatoria (Venta / Alquiler) al dar de alta un comprador con
criterios y al editar sus criterios.

- Unitario: `BusinessType` (constante única para plantillas y validación).
- Integración contra la app levantada (patrón de test_company_isolation.py,
  se omite si la app no responde): crea compradores de prueba en MOES y los
  borra al terminar.

Ejecución dentro del contenedor:
    docker exec moyza_backend python -m pytest tests/test_buyer_business_type.py -q
"""
import os
import urllib.error
import urllib.parse
import urllib.request

import pytest

from app.core.constants import BusinessType

BASE_URL = os.getenv("MOYZA_TEST_BASE_URL", "http://localhost:8000")
ADMIN_EMAIL = os.getenv("MOYZA_TEST_ADMIN_EMAIL", "admin@moyza.com")
TAG = "PYTEST-OPERACION"


# ---------------------------------------------------------------------------
# Constante
# ---------------------------------------------------------------------------

def test_business_type_valores_fijos():
    assert BusinessType.values() == ("Venta", "Alquiler")
    assert BusinessType.is_valid("Venta")
    assert BusinessType.is_valid("Alquiler")
    for value in (None, "", "venta", "Traspaso"):
        assert not BusinessType.is_valid(value)


# ---------------------------------------------------------------------------
# Integración
# ---------------------------------------------------------------------------

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

    def __init__(self, company: str):
        from app.core.security import create_access_token
        token = create_access_token({"sub": ADMIN_EMAIL})
        self.cookie = f"access_token={token}; active_company={company}"
        self.opener = urllib.request.build_opener(self._NoRedirect)

    def post(self, path, data):
        body = urllib.parse.urlencode(data, doseq=True).encode()
        req = urllib.request.Request(BASE_URL + path, data=body, method="POST")
        req.add_header("Cookie", self.cookie)
        try:
            resp = self.opener.open(req, timeout=20)
            return resp.status, dict(resp.headers)
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers)


@pytest.fixture
def db():
    if not _server_up():
        pytest.skip(f"La app no responde en {BASE_URL}; tests de integración omitidos")

    from app.db.session import SessionLocal
    from app.models.buyer import Buyer

    def cleanup():
        # db.delete por ORM, como /buyers/{id}/delete: arrastra sus criterios
        session.rollback()
        for buyer in session.query(Buyer).filter(Buyer.name.like(f"{TAG}%")).all():
            session.delete(buyer)
        session.commit()

    session = SessionLocal()
    cleanup()
    yield session

    cleanup()
    session.close()


def _flash(headers) -> str:
    """Mensaje del flash (cookie `moyza_flash`, JSON en base64)."""
    import base64
    import re
    match = re.search(r'moyza_flash="?([^";]+)', headers.get("set-cookie", ""))
    return base64.b64decode(match.group(1)).decode("utf-8") if match else ""


def _buyers(db, name):
    from app.models.buyer import Buyer
    db.expire_all()
    return db.query(Buyer).filter(Buyer.name == name).all()


def test_alta_con_criterios_exige_operacion(db):
    client = _Client("MOES")

    for business_type in (None, "", "Traspaso"):
        name = f"{TAG} SIN OPERACION"
        data = {"buyer_name": name, "buyer_phone": "600000002"}
        if business_type is not None:
            data["business_type"] = business_type
        status, headers = client.post("/buyers/create-with-criteria", data)
        assert status == 302
        assert headers.get("location") == "/alerts"
        assert "Venta o Alquiler" in _flash(headers)
        assert _buyers(db, name) == []

    name = f"{TAG} VENTA"
    status, headers = client.post("/buyers/create-with-criteria", {
        "buyer_name": name, "buyer_phone": "600000003", "business_type": "Venta",
    })
    assert status == 302
    buyers = _buyers(db, name)
    assert len(buyers) == 1
    assert headers.get("location") == f"/buyers/{buyers[0].id}?tab=matches"
    assert buyers[0].search_criteria.business_type == "Venta"


def test_edicion_de_criterios_exige_operacion(db):
    client = _Client("MOES")

    name = f"{TAG} EDICION"
    client.post("/buyers/create-with-criteria", {"buyer_name": name, "business_type": "Venta"})
    buyer = _buyers(db, name)[0]

    status, headers = client.post(f"/buyers/{buyer.id}/search-criteria", {"business_type": ""})
    assert status == 302
    assert headers.get("location") == f"/buyers/{buyer.id}?tab=criteria"
    assert "Venta o Alquiler" in _flash(headers)
    db.expire_all()
    assert buyer.search_criteria.business_type == "Venta"

    status, headers = client.post(f"/buyers/{buyer.id}/search-criteria", {"business_type": "Alquiler"})
    assert status == 302
    assert headers.get("location") == f"/buyers/{buyer.id}?tab=matches"
    db.expire_all()
    assert buyer.search_criteria.business_type == "Alquiler"


def _available_property_id(db, company_code: str) -> int:
    from app.models.company import Company
    from app.models.property import Property
    from app.core.constants import PropertyStatus

    company = db.query(Company).filter(Company.code == company_code).first()
    prop = (
        db.query(Property)
        .filter(
            Property.company_id == company.id,
            Property.status == PropertyStatus.ACTIVE,
            Property.available_clause(),
        )
        .first()
    )
    if prop is None:
        pytest.skip(f"No hay propiedades disponibles en {company_code} para crear alertas")
    return prop.id


def test_nueva_alerta_exige_operacion(db):
    """El modal de nueva alerta (y el rápido de la ficha del comprador) también
    exigen Venta o Alquiler; sin operación no se crea ni comprador ni alerta."""
    client = _Client("MOES")
    property_id = _available_property_id(db, "MOES")

    name = f"{TAG} ALERTA SIN OPERACION"
    for business_type in (None, "", "Traspaso"):
        data = {
            "property_id": property_id,
            "buyer_name": name,
            "buyer_phone": "600000004",
            "confirm_new_buyer": "1",
        }
        if business_type is not None:
            data["business_type"] = business_type
        status, headers = client.post("/alerts/create", data)
        assert status == 302
        assert headers.get("location") == "/alerts"
        assert "Venta o Alquiler" in _flash(headers)
        assert _buyers(db, name) == []

    name = f"{TAG} ALERTA VENTA"
    status, headers = client.post("/alerts/create", {
        "property_id": property_id,
        "buyer_name": name,
        "buyer_phone": "600000005",
        "confirm_new_buyer": "1",
        "business_type": "Venta",
    })
    assert status == 302
    buyers = _buyers(db, name)
    assert len(buyers) == 1
    assert len(buyers[0].alerts) == 1
    assert buyers[0].alerts[0].business_type == "Venta"

    # Formulario rápido: comprador existente sin operación vuelve a su ficha
    status, headers = client.post("/alerts/create", {
        "property_id": property_id,
        "buyer_id": buyers[0].id,
        "business_type": "",
    })
    assert status == 302
    assert headers.get("location") == f"/buyers/{buyers[0].id}"
    assert "Venta o Alquiler" in _flash(headers)
    db.expire_all()
    assert len(buyers[0].alerts) == 1
