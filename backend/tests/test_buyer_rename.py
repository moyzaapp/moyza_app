"""Cambiar el nombre de un comprador después de crearlo (PLAN_RENOMBRAR_COMPRADOR.md).

Unidad: `buyer_rename.clean_buyer_name`. Integración (se omite si la app no
responde): desde el detalle de la alerta y desde "Editar contacto" de la
ficha, el nombre se propaga a la ficha y a todas las alertas del comprador;
permisos del agente. Datos con prefijo TAG, borrados al terminar.

    docker exec moyza_backend python -m pytest tests/test_buyer_rename.py -q
"""
import base64
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

import pytest

from app.services.buyer_rename import BuyerNameError
from app.services.buyer_rename import NAME_MAX_LENGTH
from app.services.buyer_rename import clean_buyer_name

BASE_URL = os.getenv("MOYZA_TEST_BASE_URL", "http://localhost:8000")
ADMIN_EMAIL = os.getenv("MOYZA_TEST_ADMIN_EMAIL", "admin@moyza.com")
TAG = "PYTEST-RENOMBRAR"
EMAIL = "pytest.renombrar.{}@example.com"


# ---------------------------------------------------------------------------
# Unidad
# ---------------------------------------------------------------------------

def test_clean_buyer_name_recorta_y_valida():
    assert clean_buyer_name("  Ana   Pérez ") == "Ana Pérez"
    with pytest.raises(BuyerNameError, match="obligatorio"):
        clean_buyer_name("   ")
    with pytest.raises(BuyerNameError, match="obligatorio"):
        clean_buyer_name(None)
    with pytest.raises(BuyerNameError, match=str(NAME_MAX_LENGTH)):
        clean_buyer_name("x" * (NAME_MAX_LENGTH + 1))


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
    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    def __init__(self, email: str, company: str = "MOYZA"):
        from app.core.security import create_access_token
        self.cookie = f"access_token={create_access_token({'sub': email})}; active_company={company}"
        self.opener = urllib.request.build_opener(self._NoRedirect)

    def _request(self, method, path, data=None):
        body = urllib.parse.urlencode(data, doseq=True).encode() if data is not None else None
        req = urllib.request.Request(BASE_URL + path, data=body, method=method)
        req.add_header("Cookie", self.cookie)
        try:
            resp = self.opener.open(req, timeout=30)
            return resp.status, resp.read().decode("utf-8", "replace"), dict(resp.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace"), dict(e.headers)

    def get(self, path):
        return self._request("GET", path)

    def post(self, path, data):
        return self._request("POST", path, data)


def _flashes(headers) -> list:
    match = re.search(r'moyza_flash="?([^";]+)', headers.get("set-cookie", ""))
    return json.loads(base64.urlsafe_b64decode(match.group(1)).decode("utf-8")) if match else []


def _cleanup(db):
    from sqlalchemy import select
    from app.models.agent import Agent
    from app.models.alert_follow_up import AlertFollowUp
    from app.models.buyer import Buyer
    from app.models.notification import Notification
    from app.models.property_alert import PropertyAlert
    from app.models.user import User

    db.rollback()
    users = select(User.id).where(User.email.like(EMAIL.format("%")))
    db.query(Notification).filter(Notification.user_id.in_(users)).delete(synchronize_session=False)
    alerts = select(PropertyAlert.id).where(PropertyAlert.lead_name.like(f"{TAG}%"))
    db.query(AlertFollowUp).filter(AlertFollowUp.alert_id.in_(alerts)).delete(synchronize_session=False)
    db.query(PropertyAlert).filter(PropertyAlert.lead_name.like(f"{TAG}%")).delete(synchronize_session=False)
    for buyer in db.query(Buyer).filter(Buyer.name.like(f"{TAG}%")).all():
        db.delete(buyer)
    db.query(User).filter(User.email.like(EMAIL.format("%"))).delete(synchronize_session=False)
    db.query(Agent).filter(Agent.email.like(EMAIL.format("%"))).delete(synchronize_session=False)
    db.commit()


@pytest.fixture
def data():
    if not _server_up():
        pytest.skip(f"La app no responde en {BASE_URL}; tests de integración omitidos")

    from app.db.session import SessionLocal
    from app.models.agent import Agent
    from app.models.buyer import Buyer
    from app.models.company import Company
    from app.models.property_alert import PropertyAlert
    from app.models.role import Role
    from app.models.user import User

    db = SessionLocal()
    _cleanup(db)
    moyza = db.query(Company).filter_by(code="MOYZA").one()
    role = db.query(Role).filter(Role.name.ilike("agent")).first()
    admin_user_id = db.query(User.id).filter(User.email == ADMIN_EMAIL).scalar()

    out = {"moyza_id": moyza.id}
    for key in ("ana", "bea"):
        agent = Agent(name=f"{TAG} {key.upper()}", email=EMAIL.format(key))
        agent.companies.append(moyza)
        user = User(email=EMAIL.format(key), full_name=f"{TAG} {key}", hashed_password="pytest-sin-login",
                    role_id=role.id if role else None, is_active=True)
        user.companies.append(moyza)
        db.add_all([agent, user])
        db.flush()
        out[key] = agent.id

    buyer = Buyer(name=f"{TAG} SN", phone="34600990011", created_by=admin_user_id, company_id=moyza.id)
    db.add(buyer)
    db.flush()
    now = datetime.utcnow()
    alerts = []
    for agent_key, status in (("ana", "IN_PROGRESS"), ("ana", "COMPLETED"), ("bea", "PENDING")):
        alert = PropertyAlert(
            company_id=moyza.id, agent_id=out[agent_key], buyer_id=buyer.id, lead_name=buyer.name,
            lead_phone=buyer.phone, status=status, created_by=admin_user_id, created_at=now,
            assigned_at=now, origin="search", business_type="Venta",
        )
        db.add(alert)
        alerts.append(alert)
    # Alerta antigua sin ficha de comprador: solo cambia ella
    legacy = PropertyAlert(
        company_id=moyza.id, agent_id=out["ana"], buyer_id=None, lead_name=f"{TAG} SIN FICHA",
        status="IN_PROGRESS", created_by=admin_user_id, created_at=now, assigned_at=now,
        origin="search", business_type="Venta",
    )
    db.add(legacy)
    db.commit()
    out.update(buyer_id=buyer.id, alert_ids=[a.id for a in alerts], legacy_id=legacy.id, db=db)
    yield out

    _cleanup(db)
    db.close()


def _names(db, data) -> tuple:
    from app.models.buyer import Buyer
    from app.models.property_alert import PropertyAlert
    db.expire_all()
    buyer_name = db.get(Buyer, data["buyer_id"]).name
    lead_names = [db.get(PropertyAlert, i).lead_name for i in data["alert_ids"]]
    return buyer_name, lead_names


def test_detalle_muestra_el_lapiz_y_el_modal(data):
    status, body, _ = _Client(EMAIL.format("ana")).get(f"/alerts/{data['alert_ids'][0]}")
    assert status == 200
    assert 'data-modal-open="renameBuyerModal"' in body
    assert f'action="/alerts/{data["alert_ids"][0]}/rename-buyer"' in body
    assert f'value="{TAG} SN"' in body
    assert f'href="/buyers/{data["buyer_id"]}"' in body
    assert f'maxlength="{NAME_MAX_LENGTH}"' in body


def test_agente_renombra_desde_la_alerta_y_se_propaga(data):
    alert_id = data["alert_ids"][0]
    status, _, headers = _Client(EMAIL.format("ana")).post(f"/alerts/{alert_id}/rename-buyer",
                                                          {"name": f"  {TAG}   Ana Pérez "})
    assert status == 303 and headers["location"] == f"/alerts/{alert_id}"
    assert _flashes(headers)[0]["category"] == "success"
    assert _names(data["db"], data) == (f"{TAG} Ana Pérez", [f"{TAG} Ana Pérez"] * 3)   # también la cerrada y la de Bea


def test_editar_contacto_de_la_ficha_tambien_propaga(data):
    status, _, headers = _Client(ADMIN_EMAIL).post(f"/buyers/{data['buyer_id']}/update-contact", {
        "name": f"{TAG} Desde la ficha", "phone_country_code": "34", "phone_number": "600990011", "email": "",
    })
    assert status == 303, _flashes(headers)
    assert _names(data["db"], data) == (f"{TAG} Desde la ficha", [f"{TAG} Desde la ficha"] * 3)


def test_otro_agente_no_puede_renombrar(data):
    # Bea no es la agente de la primera alerta
    status, _, headers = _Client(EMAIL.format("bea")).post(f"/alerts/{data['alert_ids'][0]}/rename-buyer",
                                                          {"name": f"{TAG} Intruso"})
    assert status == 302 and headers["location"] == "/alerts"
    assert _flashes(headers)[0]["category"] == "error"
    assert _names(data["db"], data)[0] == f"{TAG} SN"


def test_nombre_vacio_se_rechaza(data):
    alert_id = data["alert_ids"][0]
    status, _, headers = _Client(ADMIN_EMAIL).post(f"/alerts/{alert_id}/rename-buyer", {"name": "   "})
    assert status == 303 and headers["location"] == f"/alerts/{alert_id}"
    assert "obligatorio" in _flashes(headers)[0]["message"]
    assert _names(data["db"], data)[0] == f"{TAG} SN"


def test_alerta_sin_ficha_solo_cambia_ella(data):
    from app.models.property_alert import PropertyAlert
    status, _, _ = _Client(ADMIN_EMAIL).post(f"/alerts/{data['legacy_id']}/rename-buyer",
                                             {"name": f"{TAG} Con nombre"})
    assert status == 303
    db = data["db"]
    db.expire_all()
    assert db.get(PropertyAlert, data["legacy_id"]).lead_name == f"{TAG} Con nombre"
    assert _names(db, data)[0] == f"{TAG} SN"
