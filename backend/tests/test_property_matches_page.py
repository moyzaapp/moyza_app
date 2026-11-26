"""
Página «Compradores compatibles» y bloque del detalle
(PLAN_COMPRADORES_COMPATIBLES_PROPIEDAD_NUEVA.md §4.5, §7).

Las rutas se llaman en proceso con un `Request` armado a mano (patrón de
test_property_review_routes.py), contra PostgreSQL dentro de una transacción
externa que se deshace al terminar.

- Acceso: admin de la empresa de la propiedad, agente con cruces (solo los
  suyos), agente sin cruces y admin de otra empresa -> redirección.
- Filas: «Enviar por WhatsApp», «Enviada el», «Sin enlace web», «Sin
  teléfono válido», alerta cerrada y alerta bloqueada en la cola.
- El POST de envío desde la página: 303 a wa.me, registra `PROPIEDAD_ENVIADA`
  y la alerta sigue «sin gestionar»; los errores vuelven a la página.
- Bloque «Compradores compatibles: N» del detalle y flash del OK.

    docker exec moyza_backend python -m pytest tests/test_property_matches_page.py -q
"""
import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from starlette.requests import Request

from app.core.constants import AlertStatus, FollowUpActionType
from app.core.constants import PropertyReviewStatus as RS
from app.models.property_review import PropertyReview
from app.services import alert_view
from app.services import property_match_service as svc
from app.web.utils.flash import FLASH_COOKIE_NAME, decode_flash


NOW = datetime.utcnow()
CITY = "PYTEST-PMP Villanueva"
URL = "https://example.com/inmueble/pmp"


@pytest.fixture
def db():
    from sqlalchemy.orm import Session
    from app.db.session import engine
    try:
        connection = engine.connect()
    except Exception as e:  # pragma: no cover - depende del entorno
        pytest.skip(f"Sin base de datos: {e}")
    transaction = connection.begin()
    session = Session(bind=connection, autoflush=False, join_transaction_mode="create_savepoint")
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def env(db):
    """MOYZA y MOES; admin de MOYZA y admin solo de MOES; Ana, Bea y Carlos
    (agentes de MOYZA con usuario). Piso de Ana en MOYZA con enlace web.
    Compradores: Juan (de Ana, teléfono válido) y Luis (de Bea, teléfono
    inválido), ya cruzados con la propiedad."""
    from app.models.agent import Agent
    from app.models.company import Company
    from app.models.property import Property
    from app.models.role import Role
    from app.models.user import User

    moyza = db.query(Company).filter_by(code="MOYZA").one()
    moes = db.query(Company).filter_by(code="MOES").one()
    admin_role = db.query(Role).filter(Role.name.ilike("admin")).first()
    agent_role = db.query(Role).filter(Role.name.ilike("agent")).first()

    admin = User(email="pytest.pmp.admin@example.com", full_name="Admin PMP", hashed_password="x",
                 is_active=True, role=admin_role)
    admin.companies.append(moyza)
    admin_moes = User(email="pytest.pmp.adminmoes@example.com", full_name="Admin MOES", hashed_password="x",
                      is_active=True, role=admin_role)
    admin_moes.companies.append(moes)
    users, agents = {}, {}
    for key in ("ana", "bea", "carlos"):
        users[key] = User(email=f"pytest.pmp.{key}@example.com", full_name=key.title(), hashed_password="x",
                          is_active=True, role=agent_role)
        users[key].companies.append(moyza)
        agents[key] = Agent(name=f"PYTEST-PMP {key.title()}", email=f"pytest.pmp.{key}@example.com", is_active=True)
        agents[key].companies.append(moyza)
    db.add_all([admin, admin_moes, *users.values(), *agents.values()])
    db.flush()

    prop = Property(title="PYTEST-PMP Piso", address="Calle Secreta 7, 2ºB", city=CITY, zona="Centro",
                    property_type="Piso", business_type="Venta", price=150000, status="Activa",
                    num_dormitorios=3, public_url=URL, company_id=moyza.id, agent_id=agents["ana"].id)
    db.add(prop)
    db.flush()
    db.add(PropertyReview(property_id=prop.id, agent_id=agents["ana"].id, status=RS.OK, rounds=0,
                          created_at=NOW, ok_at=NOW))
    env = SimpleNamespace(db=db, moyza=moyza, moes=moes, admin=admin, admin_moes=admin_moes, users=users,
                          agents=agents, prop=prop, alerts={})
    _alert(env, "juan", "ana", "34600111222")
    _alert(env, "luis", "bea", "123")
    svc.match_property(db, prop, NOW, actor=admin)
    db.expire_all()
    return env


def _alert(env, name, agent_key, phone, created_at=None, profile=True):
    from app.models.buyer import Buyer
    from app.models.buyer_search_criteria import BuyerSearchCriteria
    from app.models.property_alert import PropertyAlert

    db = env.db
    created_at = created_at or NOW - timedelta(hours=1)
    buyer = Buyer(name=f"PYTEST-PMP {name.title()}", phone=phone, company_id=env.moyza.id)
    db.add(buyer)
    db.flush()
    if profile:
        db.add(BuyerSearchCriteria(buyer_id=buyer.id, property_types=["Piso"], property_type="Piso",
                                   business_type="Venta", max_price=160000, max_bedrooms=3, cities=[CITY],
                                   zones=["Centro"], created_at=NOW))
    alert = PropertyAlert(company_id=env.moyza.id, agent_id=env.agents[agent_key].id, lead_name=buyer.name,
                          lead_phone=phone, status=AlertStatus.PENDING, priority="NORMAL", origin="search",
                          business_type="Venta", buyer_id=buyer.id, created_by=env.admin.id,
                          created_at=created_at, assigned_at=created_at)
    db.add(alert)
    db.flush()
    env.alerts[name] = alert
    return alert


def _request(env, user, path, method="GET", form=None, company=None):
    company = company or env.moyza
    body = urlencode(form or {}, doseq=True).encode()
    headers = [(b"host", b"testserver")]
    if form is not None:
        headers.append((b"content-type", b"application/x-www-form-urlencoded"))

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request({
        "type": "http", "method": method, "scheme": "http", "server": ("testserver", 80),
        "path": path, "root_path": "", "query_string": b"", "headers": headers,
        "state": {"user": user, "company": company, "allowed_companies": [company],
                  "company_ids": [company.id], "unified_view": False},
    }, receive)


def _flash(response):
    cookie = response.headers.get("set-cookie", "")
    if f"{FLASH_COOKIE_NAME}=" not in cookie:
        return None
    raw = cookie.split(f"{FLASH_COOKIE_NAME}=", 1)[1].split(";", 1)[0].strip('"')
    return decode_flash(raw)[0]


def _page(env, user, company=None):
    from app.web.routes.properties import property_matches
    env.db.expire_all()
    request = _request(env, user, f"/properties/{env.prop.id}/matches", company=company)
    response = asyncio.run(property_matches(env.prop.id, request, db=env.db))
    html = response.body.decode("utf-8") if response.status_code == 200 else ""
    return response, html


def _detail_html(env, user):
    from app.web.routes.properties import property_detail
    env.db.expire_all()
    request = _request(env, user, f"/properties/{env.prop.id}")
    response = asyncio.run(property_detail(env.prop.id, request, db=env.db))
    assert response.status_code == 200
    return response.body.decode("utf-8")


def _send(env, user, alert):
    from app.web.routes.alerts import send_property_from_alert
    back = f"/properties/{env.prop.id}/matches"
    request = _request(env, user, f"/alerts/{alert.id}/send-property", "POST",
                       form={"property_id": env.prop.id, "next": back})
    return asyncio.run(send_property_from_alert(alert.id, request, property_id=env.prop.id, next_url=back,
                                                db=env.db))


def _row(html, name):
    """Trozo del <li> de un comprador."""
    start = html.find(name)
    assert start >= 0, name
    end = html.find("</li>", start)
    return html[start:end]


# ---------------------------------------------------------------------------
# Acceso
# ---------------------------------------------------------------------------

def test_admin_ve_todos_agrupados_por_agente(env):
    response, html = _page(env, env.admin)
    assert response.status_code == 200
    assert "PYTEST-PMP Piso" in html
    assert "Compradores compatibles" in html
    assert "PYTEST-PMP Juan" in html and "PYTEST-PMP Luis" in html
    # Agrupado por agente y «N agentes avisados»
    assert html.index("PYTEST-PMP Ana") < html.index("PYTEST-PMP Juan") < html.index("PYTEST-PMP Bea") \
        < html.index("PYTEST-PMP Luis")
    assert "2 agentes avisados" in html
    # Cabecera: subtítulo, revisión, enlace a la web y a la ficha; nunca la dirección
    assert f"Piso · {CITY} · 3 dorm. · 150.000 €" in html
    assert "Revisada" in html
    assert URL in html and f'href="/properties/{env.prop.id}"' in html
    assert "Calle Secreta" not in html


def test_agente_solo_ve_los_suyos(env):
    response, html = _page(env, env.users["ana"])
    assert response.status_code == 200
    assert "PYTEST-PMP Juan" in html
    assert "PYTEST-PMP Luis" not in html
    assert "agentes avisados" not in html
    # Es la captadora: puede abrir la ficha
    assert f'href="/properties/{env.prop.id}"' in html

    response, html = _page(env, env.users["bea"])
    assert "PYTEST-PMP Luis" in html and "PYTEST-PMP Juan" not in html
    assert f'href="/properties/{env.prop.id}"' not in html
    assert "Calle Secreta" not in html


def test_agente_sin_cruces_y_admin_de_otra_empresa_redirigen(env):
    response, _ = _page(env, env.users["carlos"])
    assert response.status_code == 302
    assert response.headers["location"] == "/alerts"
    assert _flash(response)["category"] == "error"

    response, _ = _page(env, env.admin_moes, company=env.moes)
    assert response.status_code == 302
    assert response.headers["location"] == "/properties"


def test_admin_sin_cruces_ve_el_estado_vacio(env):
    from app.models.property_buyer_match import PropertyBuyerMatch
    env.db.query(PropertyBuyerMatch).delete()
    env.db.flush()
    response, html = _page(env, env.admin)
    assert response.status_code == 200
    assert "Ningún comprador encaja con esta propiedad" in html


# ---------------------------------------------------------------------------
# Filas
# ---------------------------------------------------------------------------

def test_fila_con_boton_de_enviar_y_sin_telefono_valido(env):
    _, html = _page(env, env.admin)
    juan = _row(html, "PYTEST-PMP Juan")
    assert f'action="/alerts/{env.alerts["juan"].id}/send-property"' in juan
    assert 'target="_blank"' in juan and "data-property-send" in juan
    assert f'name="next" value="/properties/{env.prop.id}/matches"' in juan
    assert "Enviar por WhatsApp" in juan
    assert f'href="/alerts/{env.alerts["juan"].id}"' in juan
    assert 'href="tel:' in juan
    assert "Busca: Piso" in juan
    assert "Pendiente" in juan and "Sin iniciar" in juan

    luis = _row(html, "PYTEST-PMP Luis")
    assert "send-property" not in luis
    assert "Sin teléfono válido" in luis


def test_sin_enlace_web(env):
    env.prop.public_url = None
    env.db.flush()
    _, html = _page(env, env.admin)
    assert "send-property" not in html
    assert "Sin enlace web" in _row(html, "PYTEST-PMP Juan")


def test_alerta_cerrada_y_alerta_bloqueada_en_la_cola(env):
    env.alerts["luis"].status = AlertStatus.COMPLETED
    # Ana tiene un comprador anterior sin gestionar: Juan queda bloqueado en su cola
    _alert(env, "anterior", "ana", "34600999000", created_at=NOW - timedelta(days=3), profile=False)
    env.db.flush()
    _, html = _page(env, env.admin)
    assert "Alerta cerrada" in _row(html, "PYTEST-PMP Luis")
    assert "send-property" in _row(html, "PYTEST-PMP Juan")   # el admin no tiene cola

    _, html = _page(env, env.users["ana"])
    juan = _row(html, "PYTEST-PMP Juan")
    assert "send-property" not in juan
    assert "Gestiona antes" in juan
    assert f'href="/alerts/{env.alerts["juan"].id}"' not in juan


# ---------------------------------------------------------------------------
# Envío desde la página
# ---------------------------------------------------------------------------

def test_enviar_desde_la_pagina(env):
    from app.models.alert_follow_up import AlertFollowUp
    alert = env.alerts["juan"]
    response = _send(env, env.users["ana"], alert)
    assert response.status_code == 303
    assert response.headers["location"].startswith("https://wa.me/34600111222?text=")

    env.db.expire_all()
    sent = env.db.query(AlertFollowUp).filter(AlertFollowUp.alert_id == alert.id).all()
    assert [(f.action_type, f.property_id) for f in sent] == [(FollowUpActionType.PROPIEDAD_ENVIADA, env.prop.id)]
    # Informativo: la alerta sigue «sin gestionar» y en el mismo estado
    alert = env.db.get(type(alert), alert.id)
    assert alert.status == AlertStatus.PENDING
    assert not alert_view.has_follow_up_since_assignment(alert.follow_ups, alert)

    _, html = _page(env, env.users["ana"])
    juan = _row(html, "PYTEST-PMP Juan")
    assert "Enviada el" in juan
    assert "Sin iniciar" in juan
    assert "send-property" in juan   # se puede reenviar


def test_error_de_envio_vuelve_a_la_pagina(env):
    env.prop.public_url = None
    env.db.flush()
    response = _send(env, env.users["ana"], env.alerts["juan"])
    assert response.status_code == 302
    assert response.headers["location"] == f"/properties/{env.prop.id}/matches"
    assert _flash(response)["category"] == "error"


def test_next_ajeno_no_se_usa():
    from app.web.routes.alerts import _send_back_url
    assert _send_back_url("/properties/12/matches", "/x") == "/properties/12/matches"
    for bad in ("https://evil.example/properties/1/matches", "/properties/1/matches/../x", "//evil", None, ""):
        assert _send_back_url(bad, "/x") == "/x"


# ---------------------------------------------------------------------------
# Detalle de la propiedad y flash del OK
# ---------------------------------------------------------------------------

def test_bloque_en_el_detalle(env):
    html = _detail_html(env, env.admin)
    assert "Compradores compatibles: <span class=\"tabular-nums\">2</span>" in html
    assert f'href="/properties/{env.prop.id}/matches"' in html

    html = _detail_html(env, env.users["ana"])
    assert "Compradores compatibles: <span class=\"tabular-nums\">1</span>" in html

    html = _detail_html(env, env.users["carlos"])
    assert "Compradores compatibles:" not in html


def test_flash_del_ok_cuenta_los_compradores(env):
    from app.models.property_buyer_match import PropertyBuyerMatch
    from app.web.routes import properties as routes
    env.db.query(PropertyBuyerMatch).delete()
    review = env.db.query(PropertyReview).filter_by(property_id=env.prop.id).one()
    review.status, review.ok_at = RS.PENDING, None
    env.db.flush()

    request = _request(env, env.users["ana"], f"/properties/{env.prop.id}/review/ok", "POST", form={})
    response = asyncio.run(routes.review_mark_ok(env.prop.id, request, db=env.db))
    flash = _flash(response)
    assert flash["category"] == "success"
    assert flash["message"].endswith(". 1 de tus compradores encaja con ella")
    assert svc.matches_count_for_property(env.db, env.prop) == 2
