"""
Revisión de las propiedades nuevas: rutas y pantallas
(PLAN_REVISION_PROPIEDADES_NUEVAS.md §6, rutas).

Las rutas se llaman en proceso con un `Request` armado a mano (patrón de
test_send_property.py), pero contra PostgreSQL dentro de una transacción
externa que se deshace al terminar (como test_notification_service.py): el
listado de Propiedades usa SQL de PostgreSQL (`~`, `regexp_replace`).

- Permisos de las tres rutas: captador, otro agente, admin y admin de otra empresa.
- Alta del admin: la propiedad queda `pending` y avisa al captador (no al admin).
- Detalle en cada estado y rol; ventana al entrar y bloque del Inicio solo con
  pendientes; tarjeta y filtro del listado.

    docker exec moyza_backend python -m pytest tests/test_property_review_routes.py -q
"""
import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from starlette.requests import Request

from app.core.constants import PropertyReviewStatus as S
from app.models.notification import Notification
from app.models.property_review import PropertyReview
from app.services import property_review_service as svc
from app.web.utils.flash import FLASH_COOKIE_NAME, decode_flash


NOW = datetime.utcnow()


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
    """MOYZA y MOES; admin de MOYZA, admin solo de MOES; Ana y Bea (agentes de
    MOYZA con usuario); propietario; Piso Ana (MOYZA, de Ana) ya registrado `pending`."""
    from app.models.agent import Agent
    from app.models.client import Client
    from app.models.company import Company
    from app.models.property import Property
    from app.models.role import Role
    from app.models.user import User

    # Lo real sin revisión no debe colarse en las pasadas del test
    orphans = (
        db.query(Property.id)
        .outerjoin(PropertyReview, PropertyReview.property_id == Property.id)
        .filter(PropertyReview.id.is_(None))
        .all()
    )
    for (pid,) in orphans:
        db.add(PropertyReview(property_id=pid, status=S.SKIPPED, rounds=0, created_at=NOW))
    db.query(PropertyReview).filter(PropertyReview.status == S.PENDING,
                                    PropertyReview.notified_at.is_(None)).update(
        {PropertyReview.notified_at: NOW - timedelta(days=30)}, synchronize_session=False)
    db.flush()

    moyza = db.query(Company).filter_by(code="MOYZA").one()
    moes = db.query(Company).filter_by(code="MOES").one()
    admin_role = db.query(Role).filter(Role.name.ilike("admin")).first()
    agent_role = db.query(Role).filter(Role.name.ilike("agent")).first()

    admin = User(email="pytest.revr.admin@example.com", full_name="Admin Rev", hashed_password="x",
                 is_active=True, role=admin_role)
    admin.companies.append(moyza)
    admin_moes = User(email="pytest.revr.adminmoes@example.com", full_name="Admin MOES", hashed_password="x",
                      is_active=True, role=admin_role)
    admin_moes.companies.append(moes)
    users, agents = {}, {}
    for key in ("ana", "bea"):
        users[key] = User(email=f"pytest.revr.{key}@example.com", full_name=key.title(), hashed_password="x",
                          is_active=True, role=agent_role)
        users[key].companies.append(moyza)
        agents[key] = Agent(name=f"PYTEST-REVR {key.title()}", email=f"pytest.revr.{key}@example.com", is_active=True)
        agents[key].companies.append(moyza)
    client = Client(name="PYTEST-REVR Propietario", phone="34600999888", status="Activo")
    client.companies.append(moyza)
    db.add_all([admin, admin_moes, client, *users.values(), *agents.values()])
    db.flush()

    prop = Property(title="PYTEST-REVR Piso Ana", address="Calle Real 12, 3ºA", city="Jaén", zona="Centro",
                    property_type="Piso", business_type="Venta", price=120000, status="Activa",
                    num_dormitorios=3, m2_construidos=95, market_entry_date=NOW - timedelta(days=2),
                    company_id=moyza.id, agent_id=agents["ana"].id, client_id=client.id)
    db.add(prop)
    db.flush()
    svc.register_new_properties(db)
    svc.notify_pending(db)
    db.expire_all()
    return SimpleNamespace(db=db, moyza=moyza, moes=moes, admin=admin, admin_moes=admin_moes, users=users,
                           agents=agents, client=client, prop=prop)


def _request(env, user, path, method="GET", form=None, company=None, query=""):
    company = company or env.moyza
    body = urlencode(form or {}, doseq=True).encode()
    headers = [(b"host", b"testserver")]
    if form is not None:
        headers.append((b"content-type", b"application/x-www-form-urlencoded"))

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request({
        "type": "http", "method": method, "scheme": "http", "server": ("testserver", 80),
        "path": path, "root_path": "", "query_string": query.encode(), "headers": headers,
        "state": {"user": user, "company": company, "allowed_companies": [company],
                  "company_ids": [company.id], "unified_view": False},
    }, receive)


def _flash(response):
    cookie = response.headers.get("set-cookie", "")
    if f"{FLASH_COOKIE_NAME}=" not in cookie:
        return None
    raw = cookie.split(f"{FLASH_COOKIE_NAME}=", 1)[1].split(";", 1)[0].strip('"')
    return decode_flash(raw)[0]


def _review(env):
    env.db.expire_all()
    return svc.review_for_property(env.db, env.prop.id)


def _post(env, user, action, comment=None, company=None):
    from app.web.routes import properties as routes
    path = f"/properties/{env.prop.id}/review/{action}"
    form = {} if comment is None else {"comment": comment}
    request = _request(env, user, path, "POST", form=form, company=company)
    if action == "ok":
        return asyncio.run(routes.review_mark_ok(env.prop.id, request, db=env.db))
    if action == "issues":
        return asyncio.run(routes.review_flag_issues(env.prop.id, request, comment=comment or "", db=env.db))
    return asyncio.run(routes.review_mark_fixed(env.prop.id, request, comment=comment or "", db=env.db))


def _detail_html(env, user, company=None):
    from app.web.routes.properties import property_detail
    request = _request(env, user, f"/properties/{env.prop.id}", company=company)
    response = asyncio.run(property_detail(env.prop.id, request, db=env.db))
    assert response.status_code == 200
    return response.body.decode("utf-8")


def _list_html(env, user, filtro="activas"):
    from app.web.routes.properties import properties_page
    request = _request(env, user, "/properties", query=f"filtro={filtro}")
    response = asyncio.run(properties_page(request, tab="mine", filtro=filtro, company_id=None,
                                           phone_country_code=None, phone_number=None,
                                           phone_country_code_other=None, db=env.db))
    assert response.status_code == 200
    return response.body.decode("utf-8")


def _dashboard_html(env, user, company=None):
    from app.web.routes.dashboard import dashboard
    request = _request(env, user, "/dashboard", company=company)
    response = asyncio.run(dashboard(request, period_type="", period_start="", db=env.db))
    assert response.status_code == 200
    return response.body.decode("utf-8")


def _section(html, marker, length=6000):
    start = html.find(marker)
    return html[start:start + length] if start >= 0 else ""


# ---------------------------------------------------------------------------
# Permisos de las rutas
# ---------------------------------------------------------------------------

def test_ok_del_captador(env):
    response = _post(env, env.users["ana"], "ok")
    assert response.status_code == 303
    assert response.headers["location"] == f"/properties/{env.prop.id}#revision"
    assert _flash(response)["category"] == "success"
    review = _review(env)
    assert (review.status, review.ok_by) == (S.OK, env.users["ana"].id)


def test_otro_agente_no_puede_nada(env):
    for action, comment in (("ok", None), ("issues", "Precio mal"), ("fixed", "x")):
        response = _post(env, env.users["bea"], action, comment)
        assert _flash(response)["category"] == "error"
    assert _review(env).status == S.PENDING


def test_admin_de_otra_empresa_no_la_encuentra(env):
    response = _post(env, env.admin_moes, "ok", company=env.moes)
    assert response.headers["location"] == "/properties"
    assert _flash(response)["message"] == "Propiedad no encontrada"
    assert _review(env).status == S.PENDING


def test_issues_solo_captador_y_fixed_solo_admin(env):
    # El admin no puede pedir revisar; el captador sin comentario tampoco
    assert _flash(_post(env, env.admin, "issues", "algo"))["category"] == "error"
    assert _flash(_post(env, env.users["ana"], "issues", "   "))["message"] == "Escribe qué hay que revisar en la ficha."
    assert _review(env).status == S.PENDING

    assert _flash(_post(env, env.users["ana"], "issues", "Son 3 dormitorios, no 2"))["category"] == "success"
    review = _review(env)
    assert (review.status, review.agent_comment, review.rounds) == (S.ISSUES, "Son 3 dormitorios, no 2", 1)

    # Con observaciones el captador ya no puede dar el OK ni marcarla corregida
    assert _flash(_post(env, env.users["ana"], "ok"))["category"] == "error"
    assert _flash(_post(env, env.users["ana"], "fixed", "x"))["category"] == "error"
    assert _flash(_post(env, env.admin, "fixed", "Dormitorios corregidos"))["category"] == "success"
    review = _review(env)
    assert (review.status, review.admin_comment) == (S.FIXED, "Dormitorios corregidos")

    assert _flash(_post(env, env.users["ana"], "ok"))["category"] == "success"
    assert _review(env).status == S.OK


def test_admin_marca_correcta_p4(env):
    assert _flash(_post(env, env.admin, "ok"))["category"] == "success"
    review = _review(env)
    assert (review.status, review.ok_by) == (S.OK, env.admin.id)


def test_comentario_de_mas_de_1000_caracteres(env):
    response = _post(env, env.users["ana"], "issues", "x" * 1001)
    assert _flash(response)["message"] == "El comentario no puede pasar de 1000 caracteres."
    assert _review(env).status == S.PENDING


# ---------------------------------------------------------------------------
# Alta del admin
# ---------------------------------------------------------------------------

def test_alta_del_admin_queda_pending_y_avisa_al_captador(env):
    from app.models.property import Property
    from app.web.routes.properties import create_property
    form = {"title": "PYTEST-REVR Nueva", "address": "Calle Nueva 1", "city": "Jaen", "price": "99000",
            "description": "", "client_id": str(env.client.id), "agent_id": str(env.agents["bea"].id)}
    request = _request(env, env.admin, "/properties/create", "POST", form=form)
    response = asyncio.run(create_property(request, title=form["title"], address=form["address"], city="Jaen",
                                           price=99000.0, description="", client_id=env.client.id,
                                           agent_id=env.agents["bea"].id, db=env.db))
    assert _flash(response)["category"] == "success"
    env.db.expire_all()
    prop = env.db.query(Property).filter(Property.title == "PYTEST-REVR Nueva").one()
    review = svc.review_for_property(env.db, prop.id)
    assert review.status == S.PENDING and review.notified_at is not None
    notices = env.db.query(Notification).filter(Notification.entity_type == svc.ENTITY,
                                                Notification.entity_id == review.id).all()
    assert [n.user_id for n in notices] == [env.users["bea"].id]


# ---------------------------------------------------------------------------
# Detalle: caja de revisión por estado y rol
# ---------------------------------------------------------------------------

def test_detalle_pending_captador_admin_y_otro(env):
    html = _detail_html(env, env.users["ana"])
    box = _section(html, 'id="revision"')
    assert "Revisa esta ficha" in box and "Por revisar" in box
    assert "En el mercado desde el" in box
    assert f'action="/properties/{env.prop.id}/review/ok"' in box
    assert 'data-modal-open="reviewIssuesModal"' in box
    assert 'id="reviewIssuesModal"' in html and 'maxlength="1000"' in html
    assert "bg-violet-50" in box

    admin_box = _section(_detail_html(env, env.admin), 'id="revision"')
    assert "Pendiente de que PYTEST-REVR Ana revise la ficha" in admin_box
    assert "Marcar correcta" in admin_box and "Hay que revisar" not in admin_box

    assert 'id="revision"' not in _detail_html(env, env.users["bea"])


def test_detalle_issues_fixed_y_ok(env):
    svc.flag_issues(env.db, _review(env), env.users["ana"], "Son 3 dormitorios")
    admin_html = _detail_html(env, env.admin)
    box = _section(admin_html, 'id="revision"')
    assert "PYTEST-REVR Ana pide revisar esta ficha" in box and "Son 3 dormitorios" in box
    assert "Con observaciones" in box and 'data-modal-open="reviewFixedModal"' in box
    assert 'id="reviewFixedModal"' in admin_html
    assert "Pendiente de que el administrador la corrija" in _detail_html(env, env.users["ana"])

    svc.mark_fixed(env.db, _review(env), env.admin, "Ya está bien")
    box = _section(_detail_html(env, env.users["ana"]), 'id="revision"')
    assert "Confirma que la ficha está correcta" in box and "Ya está bien" in box
    assert "Corregida · pendiente de OK" in box

    svc.mark_ok(env.db, _review(env), env.users["ana"])
    box = _section(_detail_html(env, env.admin), 'id="revision"', 1500)
    assert "Revisada por Ana el" in box
    assert "/review/ok" not in box


def test_detalle_sin_revision_skipped(env):
    review = _review(env)
    review.status = S.SKIPPED
    env.db.flush()
    assert 'id="revision"' not in _detail_html(env, env.users["ana"])


# ---------------------------------------------------------------------------
# Inicio del agente: ventana al entrar y bloque propio
# ---------------------------------------------------------------------------

def test_inicio_del_agente_con_y_sin_pendientes(env):
    html = _dashboard_html(env, env.users["ana"])
    assert "Propiedades nuevas por revisar" in html
    assert 'id="pendingReviewsModal"' in html and 'data-auto-open-on-login="1"' in html
    assert "PYTEST-REVR Piso Ana" in _section(html, 'id="pendingReviewsModal"', 8000)
    assert f'href="/properties/{env.prop.id}#revision"' in html
    # El bloque va encima de «Mis resultados»
    assert html.find('id="reviewsTitle"') < html.find('id="kpisTitle"')

    other = _dashboard_html(env, env.users["bea"])
    assert 'id="pendingReviewsModal"' not in other and 'id="reviewsTitle"' not in other

    svc.mark_ok(env.db, _review(env), env.users["ana"])
    after = _dashboard_html(env, env.users["ana"])
    assert 'id="pendingReviewsModal"' not in after and 'id="reviewsTitle"' not in after


def test_inicio_del_admin_requiere_atencion(env):
    svc.flag_issues(env.db, _review(env), env.users["ana"], "Revisar precio")
    html = _dashboard_html(env, env.admin)
    assert "1 propiedad con observaciones del captador" in html
    assert 'href="/properties?filtro=revision"' in html


def test_inicio_del_admin_ventana_y_bloque_por_corregir(env):
    # Sin `issues`: ni ventana ni bloque
    before = _dashboard_html(env, env.admin)
    assert 'id="reviewIssuesModal"' not in before and 'id="reviewIssuesTitle"' not in before

    svc.flag_issues(env.db, _review(env), env.users["ana"], "El precio no es 120.000, son 125.000")
    html = _dashboard_html(env, env.admin)
    assert "Propiedades por corregir" in html
    # La ventana se abre al entrar, antes que la de compradores sin gestionar
    assert 'id="reviewIssuesModal"' in html and 'data-auto-open-on-login="1"' in html
    modal = _section(html, 'id="reviewIssuesModal"', 8000)
    assert "PYTEST-REVR Piso Ana" in modal and "son 125.000" in modal and "PYTEST-REVR Ana lo pidió" in modal
    assert f'href="/properties/{env.prop.id}#revision"' in modal
    # El bloque va arriba del todo
    assert html.find('id="reviewIssuesTitle"') < html.find('id="generalKpisTitle"')

    # El admin de MOES no la ve
    assert 'id="reviewIssuesModal"' not in _dashboard_html(env, env.admin_moes, company=env.moes)

    svc.mark_fixed(env.db, _review(env), env.admin, "Precio corregido")
    after = _dashboard_html(env, env.admin)
    assert 'id="reviewIssuesModal"' not in after and 'id="reviewIssuesTitle"' not in after


def test_inicio_del_agente_cuadro_propiedades_nuevas_separado(env):
    from app.services import notification_service as ns

    # Ana tiene el aviso violet de revisión y, aparte, uno normal del admin
    ns.notify(env.db, users=[env.users["ana"]], company_id=env.moyza.id, kind=ns.NotificationKind.ADMIN_NOTE_ADDED,
              title="Observación del admin", body="Llama al propietario", url="/alerts", entity=("alert", 1))
    env.db.flush()
    html = _dashboard_html(env, env.users["ana"])
    property_box = _section(html, 'id="propertyNewsTitle"', 3000)
    news_box = _section(html, 'id="newsTitle"', 3000)
    assert "Propiedades nuevas" in property_box
    assert "Propiedad nueva: revisa la ficha" in property_box
    assert "Propiedad nueva: revisa la ficha" not in news_box
    assert "Observación del admin" in news_box
    assert "Observación del admin" not in property_box
    # Cada cuadro cuenta solo lo suyo
    assert "1 nueva" in property_box and "1 nueva" in news_box
    # El cuadro de propiedades nuevas va encima de «Novedades»
    assert html.find('id="propertyNewsTitle"') < html.find('id="newsTitle"')

    # Bea no tiene avisos de propiedades nuevas: no sale el cuadro
    assert 'id="propertyNewsTitle"' not in _dashboard_html(env, env.users["bea"])


# ---------------------------------------------------------------------------
# Listado: tarjeta «Por revisar» y filtro
# ---------------------------------------------------------------------------

def test_listado_tarjeta_y_filtro_admin_y_agente(env):
    html = _list_html(env, env.admin)
    assert 'href="/properties?filtro=revision"' in html and "Por revisar" in html
    assert "sm:grid-cols-3" in html

    filtered = _list_html(env, env.admin, "revision")
    assert "PYTEST-REVR Piso Ana" in filtered
    assert "border-violet-500" in filtered
    assert f'href="/properties/{env.prop.id}#revision"' in filtered

    # Con observaciones: el admin la sigue viendo; el captador no (le toca al admin)
    svc.flag_issues(env.db, _review(env), env.users["ana"], "Revisar")
    assert "PYTEST-REVR Piso Ana" in _list_html(env, env.admin, "revision")
    agent_html = _list_html(env, env.users["ana"], "revision")
    assert "No hay propiedades nuevas por revisar" in agent_html

    svc.mark_ok(env.db, _review(env), env.admin, by_admin=True)
    assert "PYTEST-REVR Piso Ana" not in _list_html(env, env.admin, "revision")


def test_listado_sin_pendientes_no_pinta_la_tarjeta(env):
    html = _list_html(env, env.users["bea"])
    assert 'href="/properties?filtro=revision"' not in html
