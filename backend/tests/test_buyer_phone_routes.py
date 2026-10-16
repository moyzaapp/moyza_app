"""
Teléfono con indicativo en los formularios de comprador
(PLAN_TELEFONO_COMPRADOR.md, fase 2): rutas contra la app levantada.

Patrón de test_buyer_business_type.py (se omite si la app no responde): crea
compradores de prueba en MOES con el prefijo TAG y los borra al terminar.

    docker exec moyza_backend python -m pytest tests/test_buyer_phone_routes.py -q
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

import pytest

BASE_URL = os.getenv("MOYZA_TEST_BASE_URL", "http://localhost:8000")
ADMIN_EMAIL = os.getenv("MOYZA_TEST_ADMIN_EMAIL", "admin@moyza.com")
TAG = "PYTEST-TELEFONO"


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

    def _open(self, req):
        req.add_header("Cookie", self.cookie)
        try:
            resp = self.opener.open(req, timeout=20)
            return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def post(self, path, data):
        body = urllib.parse.urlencode(data, doseq=True).encode()
        status, headers, _ = self._open(urllib.request.Request(BASE_URL + path, data=body, method="POST"))
        return status, headers

    def get_json(self, path):
        status, _, body = self._open(urllib.request.Request(BASE_URL + path))
        assert status == 200
        return json.loads(body)

    def get_html(self, path):
        status, _, body = self._open(urllib.request.Request(BASE_URL + path))
        assert status == 200
        return body.decode("utf-8")


@pytest.fixture
def db():
    if not _server_up():
        pytest.skip(f"La app no responde en {BASE_URL}; tests de integración omitidos")

    from app.db.session import SessionLocal
    from app.models.buyer import Buyer

    def cleanup():
        # db.delete por ORM, como /buyers/{id}/delete: arrastra criterios y alertas
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
    return base64.urlsafe_b64decode(match.group(1)).decode("utf-8") if match else ""


def _buyer(db, name):
    from app.models.buyer import Buyer
    db.expire_all()
    buyers = db.query(Buyer).filter(Buyer.name == name).all()
    return buyers[0] if len(buyers) == 1 else None


def _available_property_id(db, company_code: str) -> int:
    from app.core.constants import PropertyStatus
    from app.models.company import Company
    from app.models.property import Property

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


def test_alta_indicativo_repetido_y_otro_pais(db):
    client = _Client("MOES")

    name = f"{TAG} ES"
    status, headers = client.post("/buyers/create", {
        "name": name, "phone_country_code": "34", "phone_number": "+34 600 11 22 33",
    })
    assert status == 302
    assert _buyer(db, name).phone == "34600112233"

    name = f"{TAG} CO"
    client.post("/buyers/create", {
        "name": name, "phone_country_code": "57", "phone_number": "300 123 4567",
    })
    assert _buyer(db, name).phone == "573001234567"

    name = f"{TAG} SIN TELEFONO"
    client.post("/buyers/create", {"name": name, "phone_country_code": "34", "phone_number": ""})
    assert _buyer(db, name).phone is None


def test_alta_rechaza_numero_corto(db):
    client = _Client("MOES")
    name = f"{TAG} CORTO"
    status, headers = client.post("/buyers/create", {
        "name": name, "phone_country_code": "34", "phone_number": "12345",
    })
    assert status == 302
    assert headers.get("location") == "/alerts"
    assert "Revisa el teléfono" in _flash(headers)
    assert _buyer(db, name) is None


def test_campo_antiguo_sigue_funcionando(db):
    client = _Client("MOES")

    name = f"{TAG} ANTIGUO"
    client.post("/buyers/create", {"name": name, "phone": "600 11 22 33"})
    assert _buyer(db, name).phone == "34600112233"

    name = f"{TAG} ANTIGUO CRITERIOS"
    client.post("/buyers/create-with-criteria", {
        "buyer_name": name, "buyer_phone": "+57 300 123 4567", "business_type": "Venta",
    })
    assert _buyer(db, name).phone == "573001234567"


def test_alta_con_criterios_campos_nuevos(db):
    client = _Client("MOES")
    name = f"{TAG} CRITERIOS"
    status, headers = client.post("/buyers/create-with-criteria", {
        "buyer_name": name, "buyer_phone_country_code": "34",
        "buyer_phone_number": "0034 611 22 33 44", "business_type": "Venta",
    })
    assert status == 302
    assert _buyer(db, name).phone == "34611223344"


def test_edicion_conserva_pais_y_numero(db):
    from app.models.buyer import Buyer
    from app.models.company import Company

    client = _Client("MOES")
    company = db.query(Company).filter(Company.code == "MOES").first()

    # Comprador antiguo con teléfono sin indicativo
    name = f"{TAG} EDICION"
    old = Buyer(name=name, phone="600112233", company_id=company.id)
    db.add(old)
    db.commit()

    html = client.get_html(f"/buyers/{old.id}")
    assert 'name="phone_number" value="600112233"' in html
    assert '<option value="34" data-full=' in html and 'data-short="+34" selected' in html

    # Guardar sin tocar el teléfono: se conserva tal cual
    status, headers = client.post(f"/buyers/{old.id}/update-contact", {
        "name": name, "phone_country_code": "34", "phone_number": "600112233", "email": "x@example.com",
    })
    assert status == 303
    db.expire_all()
    assert old.phone == "600112233"
    assert old.email == "x@example.com"

    # Cambiar de país: se guarda canónico
    client.post(f"/buyers/{old.id}/update-contact", {
        "name": name, "phone_country_code": "57", "phone_number": "300 123 4567",
    })
    db.expire_all()
    assert old.phone == "573001234567"

    html = client.get_html(f"/buyers/{old.id}")
    assert 'name="phone_number" value="3001234567"' in html
    assert 'data-short="+57" selected' in html

    # Número no válido: error y no se toca
    status, headers = client.post(f"/buyers/{old.id}/update-contact", {
        "name": name, "phone_country_code": "57", "phone_number": "123",
    })
    assert "Revisa el teléfono" in _flash(headers)
    db.expire_all()
    assert old.phone == "573001234567"

    # Vaciarlo
    client.post(f"/buyers/{old.id}/update-contact", {
        "name": name, "phone_country_code": "57", "phone_number": "",
    })
    db.expire_all()
    assert old.phone is None


def test_alerta_copia_telefono_canonico(db):
    client = _Client("MOES")
    property_id = _available_property_id(db, "MOES")

    name = f"{TAG} ALERTA"
    status, headers = client.post("/alerts/create", {
        "property_id": property_id,
        "buyer_name": name,
        "buyer_phone_country_code": "34",
        "buyer_phone_number": "+34 622 33 44 55",
        "confirm_new_buyer": "1",
        "business_type": "Venta",
    })
    assert status == 302
    buyer = _buyer(db, name)
    assert buyer.phone == "34622334455"
    assert [a.lead_phone for a in buyer.alerts] == ["34622334455"]


def test_duplicado_con_telefono_guardado_con_formato(db):
    from app.models.buyer import Buyer
    from app.models.company import Company

    client = _Client("MOES")
    company = db.query(Company).filter(Company.code == "MOES").first()
    name = f"{TAG} EXISTENTE"
    existing = Buyer(name=name, phone="+34 633 44 55 66", company_id=company.id)
    db.add(existing)
    db.commit()

    # Lo que manda el formulario en vivo: indicativo + dígitos
    results = client.get_json("/alerts/check-buyer?phone=34633445566&email=")["results"]
    match = [b for b in results if b["id"] == existing.id]
    assert match and match[0]["phone_display"] == "+34 633 445 566"

    # Alta de alerta con comprador nuevo y mismo teléfono: aviso, no se crea
    property_id = _available_property_id(db, "MOES")
    new_name = f"{TAG} REPETIDO"
    status, headers = client.post("/alerts/create", {
        "property_id": property_id,
        "buyer_name": new_name,
        "buyer_phone_country_code": "34",
        "buyer_phone_number": "633 44 55 66",
        "business_type": "Venta",
    })
    assert status == 302
    assert "Ya existe un comprador" in _flash(headers)
    assert "+34 633 445 566" in _flash(headers)
    assert _buyer(db, new_name) is None

    # search-buyers devuelve phone_display
    results = client.get_json("/alerts/search-buyers?q=" + urllib.parse.quote(name))["results"]
    assert [b["phone_display"] for b in results if b["id"] == existing.id] == ["+34 633 445 566"]
