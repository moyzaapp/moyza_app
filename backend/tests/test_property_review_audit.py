"""
Seguimiento de propiedades nuevas y compradores compatibles (solo admin, solo lectura):
servicio `property_review_audit_service` y rutas `/properties/seguimiento-nuevas`.

Con PostgreSQL dentro de una transacción externa que se deshace al terminar
(patrón de test_property_match_service.py). Escenario: Piso de Ana en MOYZA
y alertas que encajan, no encajan o quedan fuera por cada motivo.

- `reasons_not_matching` es una réplica de `criteria_matches_property`:
  lista vacía <=> encaja, sobre el escenario y sobre los perfiles reales de la base.
- `explain_alert`: resultado y motivos por cada caso (cerrada, sin comprador,
  agente inactivo, Alquiler, incompleto, precio, población con acentos…).
- `audit_rows` / `audit_detail`: antes y después del OK (registrados, avisos,
  simulación, diagnóstico); las `skipped` de la migración no entran por fecha.
- Rutas: el admin ve listado y detalle (200); el agente, redirigido; el admin
  de otra empresa no ve la propiedad; el detalle no escribe nada.

    docker exec moyza_backend python -m pytest tests/test_property_review_audit.py -q
"""
import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app.core.constants import AlertStatus
from app.core.constants import PropertyReviewStatus as RS
from app.models.property_buyer_match import PropertyBuyerMatch
from app.models.property_review import PropertyReview
from app.services import buyer_matching
from app.services import property_review_audit_service as audit
from app.services import property_review_service as review_svc


NOW = datetime.utcnow()
CITY = "PYTEST-AUD Villaverde"


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
def ctx(db):
    """MOYZA y MOES; admin de MOYZA y admin solo de MOES; Ana (captadora, con
    usuario), Bea (MOES, con usuario), Pepe (sin usuario), Inés (inactiva).
    Piso de Ana (150.000 €, 3 dorm., 2 baños, CP 23001) registrado `pending`."""
    from app.models.agent import Agent
    from app.models.company import Company
    from app.models.property import Property
    from app.models.role import Role
    from app.models.user import User

    # Lo real sin revisión no debe entrar en las pasadas del test
    orphans = (
        db.query(Property.id)
        .outerjoin(PropertyReview, PropertyReview.property_id == Property.id)
        .filter(PropertyReview.id.is_(None))
        .all()
    )
    for (pid,) in orphans:
        db.add(PropertyReview(property_id=pid, status=RS.SKIPPED, rounds=0, created_at=NOW - timedelta(days=400)))
    db.flush()

    moyza = db.query(Company).filter_by(code="MOYZA").one()
    moes = db.query(Company).filter_by(code="MOES").one()
    admin_role = db.query(Role).filter(Role.name.ilike("admin")).first()
    agent_role = db.query(Role).filter(Role.name.ilike("agent")).first()

    admin = User(email="pytest.aud.admin@example.com", full_name="Admin AUD", hashed_password="x",
                 is_active=True, role=admin_role)
    admin.companies.append(moyza)
    admin_moes = User(email="pytest.aud.adminmoes@example.com", full_name="Admin MOES AUD", hashed_password="x",
                      is_active=True, role=admin_role)
    admin_moes.companies.append(moes)
    users, agents = {}, {}
    for key, companies, has_user, active in (("ana", [moyza], True, True), ("bea", [moes], True, True),
                                             ("pepe", [moyza], False, True), ("ines", [moyza], True, False)):
        agents[key] = Agent(name=f"PYTEST-AUD {key.title()}", email=f"pytest.aud.{key}@example.com", is_active=active)
        agents[key].companies.extend(companies)
        if has_user:
            users[key] = User(email=f"pytest.aud.{key}@example.com", full_name=key.title(), hashed_password="x",
                              is_active=True, role=agent_role)
            users[key].companies.extend(companies)
    db.add_all([admin, admin_moes, *users.values(), *agents.values()])
    db.flush()

    prop = Property(title="PYTEST-AUD Piso", city=CITY, zona="Centro", property_type="Piso", business_type="Venta",
                    price=150000, status="Activa", num_dormitorios=3, num_banos_aseos=2, cod_postal="23001",
                    num_ascensores=1, public_url="https://example.com/aud", market_entry_date=NOW - timedelta(days=1),
                    company_id=moyza.id, agent_id=agents["ana"].id)
    db.add(prop)
    db.flush()
    env = SimpleNamespace(db=db, moyza=moyza, moes=moes, admin=admin, admin_moes=admin_moes, users=users,
                          agents=agents, prop=prop, alerts={})

    _alert(env, "ana", "ana", moyza)                                   # encaja (del captador)
    _alert(env, "bea", "bea", moes, status=AlertStatus.IN_PROGRESS)    # encaja (otra empresa)
    _alert(env, "pepe", "pepe", moyza)                                 # encaja, agente sin usuario
    _alert(env, "cerrada", "bea", moes, status=AlertStatus.COMPLETED, completed_at=NOW - timedelta(days=3))
    _alert(env, "incompleto", "ana", moyza, profile=dict(max_bedrooms=None))
    _alert(env, "sin_comprador", "ana", moyza, buyer=False)
    _alert(env, "inactiva", "ines", moyza)
    _alert(env, "caro", "bea", moes, profile=dict(max_price=140000))
    _alert(env, "acentos", "bea", moes, profile=dict(cities=["PYTEST-AUD Villavérde"]))
    _alert(env, "varios", "ana", moyza, profile=dict(min_bedrooms=4, min_bathrooms=3, garage=True,
                                                       property_types=["Chalet"], property_type="Chalet"))
    _alert(env, "alquiler", "bea", moes, business_type="Alquiler")
    db.flush()
    review_svc.register_new_properties(db, now=NOW)
    review_svc.notify_pending(db, now=NOW)
    db.expire_all()
    return env


def _alert(env, key, agent_key, company, status=AlertStatus.PENDING, profile=None, buyer=True,
           business_type="Venta", completed_at=None):
    from app.models.buyer import Buyer
    from app.models.buyer_search_criteria import BuyerSearchCriteria
    from app.models.property_alert import PropertyAlert

    db = env.db
    name = f"PYTEST-AUD Comprador {key}"
    buyer_obj = None
    if buyer:
        buyer_obj = Buyer(name=name, phone="34600111222", company_id=company.id)
        db.add(buyer_obj)
        db.flush()
        fields = dict(property_types=["Piso"], property_type="Piso", business_type="Venta", max_price=160000,
                      max_bedrooms=3, cities=[CITY], zones=["Centro"])
        fields.update(profile or {})
        db.add(BuyerSearchCriteria(buyer_id=buyer_obj.id, created_at=NOW, **fields))
    alert = PropertyAlert(company_id=company.id, agent_id=env.agents[agent_key].id, lead_name=name,
                          lead_phone="34600111222", status=status, priority="NORMAL", origin="search",
                          business_type=business_type, buyer_id=buyer_obj.id if buyer_obj else None,
                          created_by=env.admin.id, created_at=NOW, assigned_at=NOW, completed_at=completed_at)
    db.add(alert)
    db.flush()
    env.alerts[key] = alert
    return alert


def _review(env):
    env.db.expire_all()
    return review_svc.review_for_property(env.db, env.prop.id)


def _by_key(env, rows):
    ids = {alert.id: key for key, alert in env.alerts.items()}
    return {ids[r["alert"].id]: r for r in rows if r["alert"].id in ids}


# ---------------------------------------------------------------------------
# reasons_not_matching: réplica del cruce
# ---------------------------------------------------------------------------

def test_reasons_replica_del_cruce_en_el_escenario(ctx):
    for key, alert in ctx.alerts.items():
        if alert.buyer is None:
            continue
        criteria = alert.buyer.search_criteria
        reasons = audit.reasons_not_matching(criteria, ctx.prop)
        assert (not reasons) == buyer_matching.criteria_matches_property(criteria, ctx.prop), (key, reasons)


def test_reasons_replica_del_cruce_con_perfiles_reales(ctx):
    """Todos los perfiles de la base contra la propiedad del test, y contra
    otras propiedades reales: los dos cruces dicen lo mismo."""
    from app.models.buyer_search_criteria import BuyerSearchCriteria
    from app.models.property import Property

    criteria_rows = ctx.db.query(BuyerSearchCriteria).limit(300).all()
    props = [ctx.prop] + ctx.db.query(Property).filter(Property.status == "Activa").limit(25).all()
    checked = 0
    for prop in props:
        for criteria in criteria_rows:
            reasons = audit.reasons_not_matching(criteria, prop)
            assert (not reasons) == buyer_matching.criteria_matches_property(criteria, prop), (prop.id, criteria.id, reasons)
            checked += 1
    assert checked > 0


def test_reasons_textos_con_valores(ctx):
    rows = _by_key(ctx, [audit.explain_alert(a, ctx.prop) for a in ctx.alerts.values()])
    caro = rows["caro"]["reasons"]
    assert caro == ["Precio: 150.000 € supera el máximo 140.000 €"]
    varios = rows["varios"]["reasons"]
    assert any(r.startswith("Tipo: «Piso» no está en Chalet") for r in varios)
    assert "Dormitorios: 3 y el perfil pide al menos 4" in varios
    assert "Baños: 2 y el perfil pide al menos 3" in varios
    assert "Garaje: el perfil lo pide y la propiedad tiene sin dato plazas" in varios
    assert len(varios) == 4
    # Acentos: el cruce compara el texto exacto y la pista lo dice
    acentos = rows["acentos"]["reasons"]
    assert len(acentos) == 1 and "solo difiere en acentos" in acentos[0]


def test_reasons_dato_vacio_de_la_propiedad(ctx):
    ctx.prop.num_dormitorios = None
    ctx.prop.cod_postal = None
    criteria = ctx.alerts["ana"].buyer.search_criteria
    criteria.province = "Jaén"
    reasons = audit.reasons_not_matching(criteria, ctx.prop)
    assert "Dormitorios: sin dato y el perfil pide como máximo 3" in reasons
    assert any(r.startswith("Provincia: la propiedad no tiene código postal") for r in reasons)
    assert not buyer_matching.criteria_matches_property(criteria, ctx.prop)


# ---------------------------------------------------------------------------
# explain_alert: mismo orden que candidate_alerts
# ---------------------------------------------------------------------------

def test_explain_alert_resultados(ctx):
    pool = audit.open_alerts_with_buyer(ctx.db)
    users = audit.users_by_agent_email(ctx.db, [a.agent for a in pool])
    rows = _by_key(ctx, [audit.explain_alert(a, ctx.prop, users) for a in ctx.alerts.values()])

    assert {k for k, r in rows.items() if r["outcome"] == audit.OUTCOME_MATCH} == {"ana", "bea", "pepe"}
    assert rows["pepe"]["agent_users"] == []
    assert [u.id for u in rows["ana"]["agent_users"]] == [ctx.users["ana"].id]
    assert rows["cerrada"]["excluded"][0].startswith("Alerta cerrada (Completada)")
    assert rows["cerrada"]["fits_profile"] is True
    assert rows["sin_comprador"]["excluded"] == ["Alerta sin comprador: no puede tener perfil"]
    assert rows["inactiva"]["excluded"] == [f"Agente inactivo ({ctx.agents['ines'].name})"]
    assert rows["alquiler"]["excluded"] == ["Alerta de Alquiler: en esa operación no hay perfil ni cruce"]
    assert rows["incompleto"]["excluded"] == ["Perfil incompleto: falta dormitorios máximos"]
    assert rows["caro"]["outcome"] == audit.OUTCOME_NO_MATCH
    assert rows["caro"]["excluded"] == []


# ---------------------------------------------------------------------------
# audit_rows / audit_detail
# ---------------------------------------------------------------------------

def _row(env, **kwargs):
    data = audit.audit_rows(env.db, env.moyza.id, now=NOW, **kwargs)
    rows = [r for r in data["rows"] if r["property"].id == env.prop.id]
    assert len(rows) == 1
    return data, rows[0]


def test_audit_rows_antes_del_ok(ctx):
    data, row = _row(ctx)
    assert row["review"].status == RS.PENDING
    assert row["registered"] == []
    assert {r["alert"].id for r in row["simulated"]} == {ctx.alerts[k].id for k in ("ana", "bea", "pepe")}
    assert row["simulated_agents"] == 3
    assert len(row["review_notifications"]) == 1
    assert row["match_notifications"] == []
    assert row["diagnosis"][0].startswith("Sin OK todavía")
    assert "hoy 3 compradores encajarían" in row["diagnosis"][-1]
    assert [u.id for u in row["facts"]["captador_users"]] == [ctx.users["ana"].id]
    assert data["summary"]["pending"] >= 1
    pool = data["summary"]["pool"]
    # Abiertas con comprador: 9 del escenario (sin la cerrada ni la sin comprador) + las reales
    assert pool["total"] >= 9
    assert pool["complete"] >= 6 and pool["with_user"] >= 3


def test_audit_rows_despues_del_ok(ctx):
    review_svc.mark_ok(ctx.db, _review(ctx), ctx.users["ana"], now=NOW)
    ctx.db.expire_all()
    data, row = _row(ctx)
    assert row["review"].status == RS.OK
    assert {m.alert_id for m in row["registered"]} == {ctx.alerts[k].id for k in ("ana", "bea", "pepe")}
    assert row["registered_agents"] == 3
    assert row["registered_notified"] == 2            # Pepe no tiene usuario
    assert len(row["match_notifications"]) == 1       # solo Bea: Ana dio el OK (nunca a sí misma)
    assert row["match_read"] == 0
    assert row["diagnosis"][0] == "3 compradores registrados de 3 agentes"
    assert "1 sin aviso" in row["diagnosis"][1]
    assert data["summary"]["with_registered"] >= 1 and data["summary"]["notifications"] >= 1

    # Un perfil que cambia después del OK: encaja hoy sin estar registrado y el diagnóstico lo dice
    ctx.alerts["caro"].buyer.search_criteria.max_price = 200000
    ctx.db.flush()
    _, row = _row(ctx)
    assert any("1 comprador encaja hoy pero no al dar el OK" in n for n in row["diagnosis"])


def test_audit_rows_filtros(ctx):
    data = audit.audit_rows(ctx.db, ctx.moyza.id, now=NOW, status=RS.OK)
    assert all(r["review"].status == RS.OK for r in data["rows"])
    assert not any(r["property"].id == ctx.prop.id for r in data["rows"])
    # MOES no ve la propiedad de MOYZA; «todas» sí
    assert not any(r["property"].id == ctx.prop.id for r in audit.audit_rows(ctx.db, ctx.moes.id, now=NOW)["rows"])
    assert any(r["property"].id == ctx.prop.id
               for r in audit.audit_rows(ctx.db, [ctx.moyza.id, ctx.moes.id], now=NOW)["rows"])
    # Las `skipped` de la migración (fila vieja, mercado viejo) no entran por el periodo
    data = audit.audit_rows(ctx.db, ctx.moyza.id, days=7, now=NOW)
    assert all(r["review"].status != RS.SKIPPED or
               (r["property"].market_entry_date and r["property"].market_entry_date >= NOW - timedelta(days=7))
               for r in data["rows"])


def test_audit_rows_busqueda(ctx):
    for text in ("PYTEST-AUD", "pytest-aud piso", str(ctx.prop.id), CITY):
        data = audit.audit_rows(ctx.db, ctx.moyza.id, now=NOW, search=text)
        assert [r["property"].id for r in data["rows"]] == [ctx.prop.id], text
    assert audit.audit_rows(ctx.db, ctx.moyza.id, now=NOW, search="PYTEST-AUD no existe")["rows"] == []
    # Con búsqueda no se limita el periodo
    review = _review(ctx)   # expira la sesión: cambiar la propiedad después
    review.created_at = NOW - timedelta(days=400)
    ctx.prop.market_entry_date = NOW - timedelta(days=400)
    ctx.db.flush()
    assert audit.audit_rows(ctx.db, ctx.moyza.id, days=7, now=NOW, search="PYTEST-AUD")["rows"]
    assert not any(r["property"].id == ctx.prop.id
                   for r in audit.audit_rows(ctx.db, ctx.moyza.id, days=7, now=NOW)["rows"])


def test_audit_detail(ctx):
    review_svc.mark_ok(ctx.db, _review(ctx), ctx.users["ana"], now=NOW)
    ctx.db.expire_all()
    data = audit.audit_detail(ctx.db, ctx.prop, now=NOW)
    keys = lambda rows: set(_by_key(ctx, rows))  # noqa: E731
    assert keys(data["registered"]) == {"ana", "bea", "pepe"}
    assert all(r["match"] is not None for r in data["registered"])
    assert keys(data["matches_now"]) == {"ana", "bea", "pepe"}
    assert keys(data["excluded"]) == {"incompleto", "inactiva", "alquiler"}
    assert keys(data["no_match"]) >= {"caro", "acentos", "varios"}
    assert keys(data["closed_fit"]) == {"cerrada"}
    assert dict(data["excluded_counter"])["Agente inactivo"] == 1
    assert dict(data["reason_counter"])["Precio"] >= 1
    assert len(data["match_notifications"]) == 1 and data["match_notifications"][0].user_id == ctx.users["bea"].id
    assert len(data["review_notifications"]) == 1
    assert data["settings"]["max_age_days"] >= 1
    # Solo lectura: ni un cruce ni un aviso más
    before = ctx.db.query(PropertyBuyerMatch).filter(PropertyBuyerMatch.property_id == ctx.prop.id).count()
    audit.audit_detail(ctx.db, ctx.prop, now=NOW)
    assert ctx.db.query(PropertyBuyerMatch).filter(PropertyBuyerMatch.property_id == ctx.prop.id).count() == before


def test_audit_detail_propiedad_historica(ctx):
    rev = _review(ctx)
    rev.status = RS.SKIPPED
    ctx.prop.market_entry_date = NOW - timedelta(days=40)
    ctx.db.flush()
    data = audit.audit_detail(ctx.db, ctx.prop, now=NOW)
    assert data["facts"]["historical"] is True
    assert "carga histórica" in data["diagnosis"][0]
    assert "3 compradores encajarían" in data["diagnosis"][1]


# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------

def _request(env, user, path, company=None, query=""):
    company = company or env.moyza

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request({
        "type": "http", "method": "GET", "scheme": "http", "server": ("testserver", 80),
        "path": path, "root_path": "", "query_string": query.encode(), "headers": [(b"host", b"testserver")],
        "state": {"user": user, "company": company, "allowed_companies": [company],
                  "company_ids": [company.id], "unified_view": False},
    }, receive)


def _list(env, user, company=None, **params):
    from app.web.routes.property_review_audit import review_audit_list
    request = _request(env, user, "/properties/seguimiento-nuevas", company=company)
    return asyncio.run(review_audit_list(request, dias=params.get("dias", 30), estado=params.get("estado", "todas"),
                                         empresa=params.get("empresa", "activa"), q=params.get("q", ""), db=env.db))


def _detail(env, user, company=None):
    from app.web.routes.property_review_audit import review_audit_detail
    request = _request(env, user, f"/properties/seguimiento-nuevas/{env.prop.id}", company=company)
    return asyncio.run(review_audit_detail(env.prop.id, request, db=env.db))


def test_rutas_admin(ctx):
    html = _list(ctx, ctx.admin).body.decode()
    assert "Seguimiento de propiedades nuevas" in html
    assert "PYTEST-AUD Piso" in html
    assert f"/properties/seguimiento-nuevas/{ctx.prop.id}" in html
    assert "Sin OK todavía" in html

    html = _detail(ctx, ctx.admin).body.decode()
    assert "Encajan con los datos de hoy" in html
    assert "PYTEST-AUD Comprador bea" in html
    assert "Precio: 150.000 € supera el máximo 140.000 €" in html
    assert "Alerta cerrada (Completada)" in html or "Cerradas hace poco" in html
    assert "solo difiere en acentos" in html
    # Filtro por estado y «todas las empresas» responden
    assert _list(ctx, ctx.admin, estado=RS.OK, dias=90).status_code == 200
    assert _list(ctx, ctx.admin, empresa="todas").status_code == 200
    html = _list(ctx, ctx.admin, q="PYTEST-AUD").body.decode()
    assert "PYTEST-AUD Piso" in html and "Quitar búsqueda" in html
    html = _list(ctx, ctx.admin, q="PYTEST-AUD no existe").body.decode()
    assert "Ninguna propiedad encontrada" in html


def test_rutas_sin_permiso(ctx):
    for user in (ctx.users["ana"], ctx.users["bea"]):
        assert _list(ctx, user).status_code in (302, 303)
        assert _detail(ctx, user).status_code in (302, 303)
    # Admin de MOES: no ve la propiedad de MOYZA
    assert "PYTEST-AUD Piso" not in _list(ctx, ctx.admin_moes, company=ctx.moes).body.decode()
    response = _detail(ctx, ctx.admin_moes, company=ctx.moes)
    assert response.status_code in (302, 303)
    assert response.headers["location"] == "/properties/seguimiento-nuevas"


def test_listado_de_propiedades_enlaza_al_seguimiento(ctx):
    from app.web.routes.properties import properties_page
    request = _request(ctx, ctx.admin, "/properties")
    response = asyncio.run(properties_page(request, tab="mine", filtro="activas", company_id=None,
                                           phone_country_code=None, phone_number=None,
                                           phone_country_code_other=None, db=ctx.db))
    assert 'href="/properties/seguimiento-nuevas"' in response.body.decode()
    request = _request(ctx, ctx.users["ana"], "/properties")
    response = asyncio.run(properties_page(request, tab="mine", filtro="activas", company_id=None,
                                           phone_country_code=None, phone_number=None,
                                           phone_country_code_other=None, db=ctx.db))
    assert 'href="/properties/seguimiento-nuevas"' not in response.body.decode()
