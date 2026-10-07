"""
Tests de la validación de alertas de comprador duplicadas.

Dos bloques:

1. Unitarios (sin base de datos): normalización de teléfono y correo, y
   las notas que se añaden al mensaje de la alerta.
2. Integración: se ejecutan contra la app levantada (por defecto
   http://localhost:8000, configurable con MOYZA_TEST_BASE_URL) y su base
   de datos. Si la app no responde, se omiten. Crean datos de prueba en
   MOES y los eliminan al final.

Ejecución dentro del contenedor:
    docker exec moyza_backend python -m pytest tests/test_alert_duplicates.py -q
"""
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from http.cookiejar import CookieJar

import pytest

from app.services.alert_duplicate_service import (
    append_note,
    duplicate_note,
    new_contact_note,
    normalize_email,
    normalize_phone,
    phone_suffix,
    phones_match,
)
from app.web.utils.flash import decode_flash


# ===========================================================================
# Unitarios
# ===========================================================================

class TestNormalizacionTelefono:

    @pytest.mark.parametrize("raw, digits", [
        ("+34 600 11 22 33", "34600112233"),
        ("600-11-22-33", "600112233"),
        ("(600) 112233", "600112233"),
        ("", ""),
        (None, ""),
    ])
    def test_normalize_phone_deja_solo_digitos(self, raw, digits):
        assert normalize_phone(raw) == digits

    def test_phone_suffix_devuelve_ultimos_nueve(self):
        assert phone_suffix("+34 600 11 22 33") == "600112233"
        assert phone_suffix("0034600112233") == "600112233"

    def test_phone_suffix_vacio_si_es_corto(self):
        assert phone_suffix("12345") == ""
        assert phone_suffix(None) == ""

    def test_phones_match_ignora_prefijo_y_formato(self):
        assert phones_match("+34 600 11 22 33", "600112233")
        assert phones_match("600-112-233", "0034 600112233")

    def test_phones_match_distintos(self):
        assert not phones_match("600112233", "600112234")

    def test_phones_match_cortos_no_cuentan(self):
        assert not phones_match("1234", "1234")
        assert not phones_match("", "")


class TestNormalizacionEmail:

    def test_minusculas_y_sin_espacios(self):
        assert normalize_email("  Juan@Example.COM ") == "juan@example.com"

    def test_vacio(self):
        assert normalize_email(None) == ""
        assert normalize_email("   ") == ""


class TestNotas:

    def test_duplicate_note_incluye_id_y_fecha(self):
        from types import SimpleNamespace
        existing = SimpleNamespace(id=123, created_at=datetime(2026, 10, 3, 10, 0))
        note = duplicate_note(existing)
        assert "#123" in note
        assert "03/10/2026" in note
        assert note.startswith("Duplicado confirmado")

    def test_new_contact_note_con_origen_y_notas(self):
        note = new_contact_note("Idealista", "Admin", "Llamó otra vez", when=datetime(2026, 10, 6, 8, 30))
        assert note.startswith("Nuevo contacto 06/10/2026 10:30 vía Idealista (registrado por Admin).")
        assert note.endswith("Llamó otra vez")

    def test_new_contact_note_sin_origen_ni_notas(self):
        note = new_contact_note("  ", "Admin", None, when=datetime(2026, 10, 6, 8, 30))
        assert "vía" not in note
        assert note.endswith("(registrado por Admin).")

    def test_append_note_sobre_mensaje_vacio_y_existente(self):
        assert append_note(None, "Nota") == "Nota"
        assert append_note("  ", "Nota") == "Nota"
        assert append_note("Hola", "Nota") == "Hola\n\nNota"


# ===========================================================================
# Integración
# ===========================================================================

BASE_URL = os.getenv("MOYZA_TEST_BASE_URL", "http://localhost:8000")
ADMIN_EMAIL = os.getenv("MOYZA_TEST_ADMIN_EMAIL", "admin@moyza.com")


def _server_up() -> bool:
    try:
        urllib.request.urlopen(BASE_URL + "/", timeout=3)
        return True
    except Exception:
        return False


integration = pytest.mark.skipif(
    not _server_up(),
    reason=f"La app no responde en {BASE_URL}; tests de integración omitidos",
)


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

    def get_json(self, path):
        status, body, _ = self.get(path)
        return status, json.loads(body)

    def post(self, path, data):
        return self._request("POST", path, data or {})


def flash_of(headers) -> dict:
    """Primer mensaje flash de la respuesta (categoría y texto)."""
    raw = headers.get("set-cookie", "") or headers.get("Set-Cookie", "")
    match = re.search(r"moyza_flash=([^;]+)", raw)
    messages = decode_flash(match.group(1)) if match else []
    return messages[0] if messages else {}


@pytest.fixture(scope="module")
def db():
    import app.db.base  # noqa: F401  (registra todos los modelos)
    from app.db.session import SessionLocal
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture(scope="module")
def admin_token():
    from app.core.security import create_access_token
    return create_access_token({"sub": ADMIN_EMAIL})


@pytest.fixture(scope="module")
def moes(admin_token):
    return Client(admin_token, "MOES")


@pytest.fixture(scope="module")
def moyza(admin_token):
    return Client(admin_token, "MOYZA")


@pytest.fixture(scope="module")
def data(db, moes):
    """Agente, cliente, propiedad y comprador en MOES; se borran al final (con sus alertas)."""
    from app.models.agent import Agent
    from app.models.buyer import Buyer
    from app.models.client import Client as ClientModel
    from app.models.property import Property
    from app.models.property_alert import PropertyAlert

    tag = "PYTEST-DUP"
    agent_email = "pytest.dup.agente@example.com"
    client_email = "pytest.dup.cliente@example.com"

    moes.post("/agents/create", {"name": f"{tag} AGENTE", "email": agent_email})
    moes.post("/clients/create", {"name": f"{tag} CLIENTE", "email": client_email, "phone": "600000001"})
    db.expire_all()
    agent = db.query(Agent).filter_by(email=agent_email).one()
    client = db.query(ClientModel).filter_by(email=client_email).one()

    moes.post("/properties/create", {
        "title": f"{tag} PROP", "address": "Calle Dup 1", "city": "Jaen", "price": "100000",
        "description": "t", "client_id": client.id, "agent_id": agent.id,
    })
    moes.post("/buyers/create", {"name": f"{tag} COMPRADOR", "phone": "+34 611 22 33 44", "email": "Dup.Comprador@Example.com"})
    db.expire_all()
    prop = db.query(Property).filter_by(title=f"{tag} PROP").one()
    buyer = db.query(Buyer).filter_by(name=f"{tag} COMPRADOR").one()

    yield {"tag": tag, "agent": agent, "client": client, "property": prop, "buyer": buyer}

    db.expire_all()
    buyer_ids = [b.id for b in db.query(Buyer).filter(Buyer.name.like(f"{tag}%")).all()]
    if buyer_ids:
        db.query(PropertyAlert).filter(PropertyAlert.buyer_id.in_(buyer_ids)).delete(synchronize_session=False)
    db.query(PropertyAlert).filter(PropertyAlert.property_id == prop.id).delete(synchronize_session=False)
    db.query(Buyer).filter(Buyer.name.like(f"{tag}%")).delete(synchronize_session=False)
    db.query(Property).filter(Property.title.like(f"{tag}%")).delete(synchronize_session=False)
    db.query(Agent).filter(Agent.email == agent_email).delete(synchronize_session=False)
    db.query(ClientModel).filter(ClientModel.email == client_email).delete(synchronize_session=False)
    db.commit()


def _alerts_for(db, buyer_id, property_id):
    from app.models.property_alert import PropertyAlert
    db.expire_all()
    return (
        db.query(PropertyAlert)
        .filter(PropertyAlert.buyer_id == buyer_id, PropertyAlert.property_id == property_id)
        .order_by(PropertyAlert.id.asc())
        .all()
    )


@integration
def test_flujo_duplicado_comprador_existente(moes, db, data):
    buyer_id, prop_id = data["buyer"].id, data["property"].id
    form = {"buyer_id": buyer_id, "property_id": prop_id, "source": "Idealista", "message": "Primer contacto"}

    # Sin alertas: la consulta previa no devuelve nada
    status, body = moes.get_json(f"/alerts/check-duplicate?buyer_id={buyer_id}&property_id={prop_id}")
    assert status == 200 and body["open"] == [] and body["recent_closed"] == []

    # Primera alerta: se crea
    status, _, headers = moes.post("/alerts/create", form)
    assert status == 302 and flash_of(headers).get("category") == "success"
    assert len(_alerts_for(db, buyer_id, prop_id)) == 1
    first = _alerts_for(db, buyer_id, prop_id)[0]

    # La consulta previa ahora la devuelve como abierta, con los datos para el aviso
    status, body = moes.get_json(f"/alerts/check-duplicate?buyer_id={buyer_id}&property_id={prop_id}")
    assert [a["id"] for a in body["open"]] == [first.id]
    assert body["open"][0]["source"] == "Idealista"
    assert body["open"][0]["status_label"] == "Pendiente"
    assert body["open"][0]["url"] == f"/alerts/{first.id}"
    assert body["open"][0]["agent"] == data["agent"].name

    # Segundo envío idéntico sin confirmar: se rechaza con aviso y no se crea
    status, _, headers = moes.post("/alerts/create", {**form, "source": "Fotocasa"})
    flash = flash_of(headers)
    assert status == 302 and flash.get("category") == "warning"
    assert f"#{first.id}" in flash.get("message", "")
    assert len(_alerts_for(db, buyer_id, prop_id)) == 1

    # Con confirmación: se crea y queda anotado el duplicado
    status, _, headers = moes.post("/alerts/create", {**form, "source": "Fotocasa", "confirm_duplicate": "1"})
    assert status == 302 and flash_of(headers).get("category") == "success"
    alerts = _alerts_for(db, buyer_id, prop_id)
    assert len(alerts) == 2
    assert "Primer contacto" in alerts[1].message
    assert f"Duplicado confirmado de la alerta #{first.id}" in alerts[1].message


@integration
def test_registrar_nuevo_contacto_en_alerta_existente(moes, db, data):
    buyer_id, prop_id = data["buyer"].id, data["property"].id
    alert = _alerts_for(db, buyer_id, prop_id)[0]
    alert.read_at = datetime.utcnow()
    db.commit()

    status, _, headers = moes.post(
        f"/alerts/{alert.id}/register-contact",
        {"source": "Llamada", "notes": "Volvió a preguntar", "priority": "ALTA"},
    )
    assert status == 302 and flash_of(headers).get("category") == "success"
    assert headers.get("location") == f"/alerts/{alert.id}"

    db.expire_all()
    assert "Nuevo contacto" in alert.message
    assert "vía Llamada" in alert.message
    assert "Volvió a preguntar" in alert.message
    assert alert.priority == "ALTA"
    assert alert.read_at is None
    # No crea otra alerta
    assert len(_alerts_for(db, buyer_id, prop_id)) == 2


@integration
def test_registrar_contacto_en_alerta_cerrada_se_rechaza(moes, db, data):
    from app.core.constants import AlertStatus
    buyer_id, prop_id = data["buyer"].id, data["property"].id
    alert = _alerts_for(db, buyer_id, prop_id)[1]
    alert.status = AlertStatus.COMPLETED
    alert.completed_at = datetime.utcnow()
    db.commit()

    status, _, headers = moes.post(f"/alerts/{alert.id}/register-contact", {"source": "Web"})
    assert status == 302 and flash_of(headers).get("category") == "error"

    # La consulta previa la lista como cerrada reciente, no como abierta
    status, body = moes.get_json(f"/alerts/check-duplicate?buyer_id={buyer_id}&property_id={prop_id}")
    assert [a["id"] for a in body["recent_closed"]] == [alert.id]
    assert alert.id not in [a["id"] for a in body["open"]]


@integration
def test_comprador_nuevo_con_telefono_repetido(moes, db, data):
    from app.models.buyer import Buyer
    tag = data["tag"]
    prop_id = data["property"].id

    # La consulta previa encuentra al comprador aunque el formato del teléfono cambie
    status, body = moes.get_json("/alerts/check-buyer?phone=611223344&email=")
    assert status == 200 and [b["id"] for b in body["results"]] == [data["buyer"].id]

    # También por correo, sin distinguir mayúsculas
    status, body = moes.get_json("/alerts/check-buyer?phone=&email=dup.comprador@example.com")
    assert [b["id"] for b in body["results"]] == [data["buyer"].id]

    before = db.query(Buyer).filter(Buyer.name.like(f"{tag}%")).count()

    # Alta como nuevo comprador con el mismo teléfono: se rechaza con aviso
    status, _, headers = moes.post("/alerts/create", {
        "property_id": prop_id, "buyer_name": f"{tag} OTRO", "buyer_phone": "611 22 33 44",
    })
    flash = flash_of(headers)
    assert status == 302 and flash.get("category") == "warning"
    assert data["buyer"].name in flash.get("message", "")
    db.expire_all()
    assert db.query(Buyer).filter(Buyer.name.like(f"{tag}%")).count() == before

    # Confirmando que es otra persona: se crea
    status, _, headers = moes.post("/alerts/create", {
        "property_id": prop_id, "buyer_name": f"{tag} OTRO", "buyer_phone": "611 22 33 44",
        "confirm_new_buyer": "1",
    })
    assert status == 302 and flash_of(headers).get("category") == "success"
    db.expire_all()
    assert db.query(Buyer).filter(Buyer.name.like(f"{tag}%")).count() == before + 1


@integration
def test_consultas_respetan_la_empresa(moyza, data):
    buyer_id, prop_id = data["buyer"].id, data["property"].id

    # Desde MOYZA el comprador de MOES no existe: ni alertas ni coincidencias
    status, body = moyza.get_json(f"/alerts/check-duplicate?buyer_id={buyer_id}&property_id={prop_id}")
    assert status == 200 and body["open"] == [] and body["recent_closed"] == []

    status, body = moyza.get_json("/alerts/check-buyer?phone=611223344")
    assert status == 200 and body["results"] == []


@integration
def test_consultas_requieren_admin():
    anon = Client("invalido", "MOES")
    status, _, _ = anon.get("/alerts/check-duplicate?buyer_id=1&property_id=1")
    assert status in (302, 401, 403)
    status, _, _ = anon.get("/alerts/check-buyer?phone=611223344")
    assert status in (302, 401, 403)
