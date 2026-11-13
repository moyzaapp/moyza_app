"""
Enviar una propiedad al comprador por WhatsApp (PLAN_ENVIO_PROPIEDAD_COMPRADOR.md §4.2, §4.3, §6).

Rutas y servicios en proceso contra una SQLite en memoria con los modelos
reales (patrón de test_alert_search.py): sin la app levantada, sin
PostgreSQL y sin red (nunca se consulta la web de la inmobiliaria).

Lo más delicado (§2): el registro «Propiedad enviada» es solo informativo. No
desbloquea la cola, no permite cerrar, no cambia la etapa ni marca actividad
y el comprador sigue "sin gestionar".

    cd backend && python -m pytest tests/test_send_property.py -q
"""
import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode, urlparse

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from app.core.constants import AlertStatus, FollowUpActionType
from app.web.utils.flash import FLASH_COOKIE_NAME, decode_flash


T0 = datetime(2026, 10, 1, 9, 0)
MOYZA_TEMPLATE = (
    "https://www.inmobiliariamoyza.com/recursos/nficham06.php?cod_inmueble=9834998349{referencia}00"
)
URL_1933 = "https://www.inmobiliariamoyza.com/recursos/nficham06.php?cod_inmueble=9834998349193300"
SENT = FollowUpActionType.PROPIEDAD_ENVIADA


# ---------------------------------------------------------------------------
# SQLite en memoria
# ---------------------------------------------------------------------------

@pytest.fixture
def env():
    """MOYZA (con plantilla de enlace) y MOES (sin plantilla); admin; Ana y Bea
    (agentes de MOYZA con usuario); comprador Juan (34600111222, de Ana).

    Propiedades: Piso Centro (MOYZA, de Ana, ref 1933), Piso Bea (MOYZA, de
    Bea, sin referencia), Piso MOES (MOES, ref 55, sin enlace).
    """
    import app.db.base as db_base
    from app.models.agent import Agent
    from app.models.buyer import Buyer
    from app.models.company import Company
    from app.models.property import Property
    from app.models.role import Role
    from app.models.user import User

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    db_base.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autoflush=False)()

    moyza = Company(code="MOYZA", name="MOYZA", primary_color="#000000", property_url_template=MOYZA_TEMPLATE)
    moes = Company(code="MOES", name="MOES PREMIUM", primary_color="#8A6D1F")
    admin_role, agent_role = Role(name="admin"), Role(name="agent")
    admin = User(email="admin@example.com", full_name="Admin Uno", hashed_password="x", role=admin_role)
    users = {
        key: User(email=f"{key}@example.com", full_name=key.title(), hashed_password="x", role=agent_role)
        for key in ("ana", "bea")
    }
    agents = {key: Agent(name=f"Agente {key.title()}", email=f"{key}@example.com") for key in ("ana", "bea")}
    for obj in [admin, *users.values(), *agents.values()]:
        obj.companies.append(moyza)
    admin.companies.append(moes)
    db.add_all([moyza, moes, admin, *users.values(), *agents.values()])
    db.flush()

    def prop(title, company, agent, referencia=None):
        return Property(title=title, address=f"Calle {title} 1, 3ºA", city="Jaen", zona="Centro",
                        property_type="Piso", business_type="Venta", price=120000, status="Activa",
                        num_dormitorios=2, num_banos_aseos=1, referencia=referencia,
                        company_id=company.id, agent_id=agent.id)

    props = {
        "ana": prop("Piso Centro", moyza, agents["ana"], "1933"),
        "bea": prop("Piso Bea", moyza, agents["bea"]),
        "moes": prop("Piso MOES", moes, agents["ana"], "55"),
    }
    db.add_all(props.values())
    buyer = Buyer(name="Juan Comprador", phone="34600111222", company_id=moyza.id, created_by=users["ana"].id)
    db.add(buyer)
    db.commit()

    yield SimpleNamespace(db=db, moyza=moyza, moes=moes, admin=admin, users=users, agents=agents,
                          props=props, buyer=buyer)

    db.close()
    engine.dispose()


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
        "state": {"user": user, "company": company, "allowed_companies": [company]},
    }, receive)


def _flash(response):
    cookie = response.headers.get("set-cookie", "")
    raw = cookie.split(f"{FLASH_COOKIE_NAME}=", 1)[1].split(";", 1)[0].strip('"')
    return decode_flash(raw)[0]


def _alert(env, agent_key="ana", created_at=T0, prop_key=None, status=AlertStatus.PENDING, phone=None):
    from app.models.property_alert import PropertyAlert
    from app.services import alert_assignment_service as svc
    alert = PropertyAlert(property=env.props[prop_key] if prop_key else None, company_id=env.moyza.id,
                          buyer_id=env.buyer.id, lead_name=env.buyer.name,
                          lead_phone=env.buyer.phone if phone is None else phone,
                          business_type="Venta", status=AlertStatus.PENDING, priority="NORMAL",
                          created_by=env.admin.id, created_at=created_at)
    env.db.add(alert)
    svc.assign(env.db, alert, env.agents[agent_key], env.admin, None, is_new=True, now=created_at)
    alert.status = status
    env.db.commit()
    return alert


def _complete_profile(env):
    from app.models.buyer_search_criteria import BuyerSearchCriteria
    criteria = BuyerSearchCriteria(buyer_id=env.buyer.id, property_type="Piso", max_price=200000,
                                   max_bedrooms=3, cities=["Jaen"], zones=["Centro"], business_type="Venta")
    env.db.add(criteria)
    env.db.commit()
    return criteria


def _send(env, user, alert, prop_key=None, property_id=None):
    from app.web.routes.alerts import send_property_from_alert
    pid = property_id if property_id is not None else env.props[prop_key].id
    request = _request(env, user, f"/alerts/{alert.id}/send-property", "POST", form={"property_id": pid})
    return asyncio.run(send_property_from_alert(alert.id, request, property_id=pid, db=env.db))


def _send_from_buyer(env, user, prop_key):
    from app.web.routes.alerts import send_property_from_buyer
    pid = env.props[prop_key].id
    request = _request(env, user, f"/buyers/{env.buyer.id}/send-property", "POST", form={"property_id": pid})
    return asyncio.run(send_property_from_buyer(env.buyer.id, request, property_id=pid, db=env.db))


def _sent_rows(env, alert=None):
    from app.models.alert_follow_up import AlertFollowUp
    env.db.expire_all()
    query = env.db.query(AlertFollowUp).filter(AlertFollowUp.action_type == SENT)
    if alert is not None:
        query = query.filter(AlertFollowUp.alert_id == alert.id)
    return query.all()


def _detail(env, user, alert, step=None):
    from app.web.routes.alerts import alert_detail
    query = urlencode({"step": step} if step else {})
    request = _request(env, user, f"/alerts/{alert.id}", query=query)
    response = asyncio.run(alert_detail(alert.id, request, step=step, confirm_property=None, company=None,
                                        db=env.db))
    return response, (response.body.decode("utf-8") if response.status_code == 200 else "")


def _buyer_html(env, user, tab="matches"):
    from app.web.routes.alerts import buyer_detail
    request = _request(env, user, f"/buyers/{env.buyer.id}", query=f"tab={tab}")
    response = asyncio.run(buyer_detail(env.buyer.id, request, tab=tab, db=env.db))
    return response, response.body.decode("utf-8")


def _whatsapp_text(response) -> str:
    return parse_qs(urlparse(response.headers["location"]).query)["text"][0]


# ---------------------------------------------------------------------------
# Constante
# ---------------------------------------------------------------------------

def test_propiedad_enviada_es_nota_del_sistema():
    from app.services import alert_view
    assert SENT in FollowUpActionType.SYSTEM_ACTIONS
    assert SENT in FollowUpActionType.AGENT_VISIBLE_SYSTEM_ACTIONS
    assert FollowUpActionType.REASIGNADA not in FollowUpActionType.AGENT_VISIBLE_SYSTEM_ACTIONS
    assert SENT not in FollowUpActionType.STAGE_ORDER
    assert not FollowUpActionType.is_valid(SENT)
    assert SENT not in dict(FollowUpActionType.ordered_stages())
    assert FollowUpActionType.labels()[SENT] == "Propiedad enviada"
    assert FollowUpActionType.stage_badge_color(SENT) == FollowUpActionType.stage_badge_color("REASIGNADA")
    follow_up = SimpleNamespace(action_type=SENT, created_at=T0 + timedelta(hours=1))
    assert not alert_view.is_real_follow_up(follow_up)
    assert not alert_view.has_follow_up_since_assignment([follow_up], SimpleNamespace(assigned_at=T0, created_at=T0))


# ---------------------------------------------------------------------------
# POST /alerts/{id}/send-property
# ---------------------------------------------------------------------------

def test_envio_desde_la_alerta_redirige_a_whatsapp_y_registra(env):
    alert = _alert(env)
    response = _send(env, env.users["ana"], alert, "ana")

    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith("https://wa.me/34600111222?text=")
    text = _whatsapp_text(response)
    assert text.startswith("Hola Juan, soy Agente Ana de MOYZA. ")
    assert "Piso en Centro, Jaen · 2 dorm. · 120.000 €" in text
    assert text.endswith(URL_1933)
    assert "Calle" not in text and "3ºA" not in text

    rows = _sent_rows(env, alert)
    assert len(rows) == 1
    row = rows[0]
    assert row.property_id == env.props["ana"].id
    assert row.created_by == env.users["ana"].id
    assert row.notes == f"Enviada por WhatsApp: Piso Centro — {URL_1933}"
    assert row.next_action_date is None


def test_se_puede_reenviar_y_el_admin_tambien_envia(env):
    alert = _alert(env)
    assert _send(env, env.users["ana"], alert, "ana").status_code == 303
    response = _send(env, env.admin, alert, "ana")
    assert response.status_code == 303
    assert "soy Admin Uno de MOYZA" in _whatsapp_text(response)
    assert len(_sent_rows(env, alert)) == 2


def test_propiedad_de_otra_agente_y_de_otra_empresa_con_enlace_manual(env):
    """Mismas reglas que asociar: cualquier agente y las dos empresas."""
    env.props["bea"].public_url = "https://www.inmobiliariamoyza.com/ficha-bea"
    env.props["moes"].public_url = "https://moes.example/ficha/55"
    env.db.commit()
    alert = _alert(env)
    assert _send(env, env.users["ana"], alert, "bea").status_code == 303
    response = _send(env, env.users["ana"], alert, "moes")
    assert response.status_code == 303
    text = _whatsapp_text(response)
    assert "de MOES PREMIUM." in text and text.endswith("https://moes.example/ficha/55")
    assert {r.property_id for r in _sent_rows(env, alert)} == {env.props["bea"].id, env.props["moes"].id}


def test_agente_ajeno_rechazado_sin_seguimiento(env):
    alert = _alert(env, "ana")
    response = _send(env, env.users["bea"], alert, "ana")
    assert response.status_code == 302 and response.headers["location"] == "/alerts"
    assert _flash(response)["category"] == "error"
    assert _sent_rows(env) == []


def test_alerta_cerrada_rechazada(env):
    alert = _alert(env, status=AlertStatus.COMPLETED)
    response = _send(env, env.users["ana"], alert, "ana")
    assert response.status_code == 302 and "wa.me" not in response.headers["location"]
    assert _sent_rows(env) == []


@pytest.mark.parametrize("case", ["sin_enlace", "telefono", "no_disponible", "archivada", "no_existe"])
def test_errores_sin_whatsapp_ni_seguimiento(env, case):
    phone = "123" if case == "telefono" else None
    alert = _alert(env, phone=phone)
    property_id = None
    prop_key = "ana"
    if case == "sin_enlace":
        prop_key = "moes"            # MOES sin plantilla ni enlace manual
    elif case == "no_disponible":
        env.props["ana"].estado_inmueble = "No disponible"
    elif case == "archivada":
        env.props["ana"].status = "Archivada"
    elif case == "no_existe":
        property_id = 99999
    env.db.commit()

    response = _send(env, env.users["ana"], alert, prop_key, property_id=property_id)

    assert response.status_code == 302
    assert response.headers["location"] == f"/alerts/{alert.id}?step=proposal#propuesta"
    flash = _flash(response)
    assert flash["category"] == "error"
    expected = {
        "sin_enlace": "no tiene enlace en la web",
        "telefono": "teléfono válido para WhatsApp",
        "no_disponible": "no está disponible",
        "archivada": "no está disponible",
        "no_existe": "Propiedad no encontrada",
    }[case]
    assert expected in flash["message"]
    assert _sent_rows(env) == []


# ---------------------------------------------------------------------------
# Solo informativo: ningún indicador se mueve
# ---------------------------------------------------------------------------

def test_tras_el_envio_sigue_sin_gestionar(env):
    from app.services import buyer_attention_service as bas
    alert = _alert(env)
    _send(env, env.users["ana"], alert, "ana")
    env.db.expire_all()

    now = datetime.utcnow() + timedelta(days=10)
    clock = bas.alert_clock(env.db.get(type(alert), alert.id), now=now)
    assert clock.rule == bas.RULE_NO_ACTION and clock.never_managed
    assert clock.since == alert.assigned_at            # el reloj no se reinicia
    items = bas.find_buyers_needing_attention(env.db, company_id=env.moyza.id, now=now)
    assert [(i.alert.id, i.never_managed) for i in items] == [(alert.id, True)]

    from app.services.dashboard_service import DashboardService
    groups = DashboardService(env.db, env.moyza.id).unmanaged_by_agent(list(env.agents.values()), now=now)
    assert [(g["agent_id"], g["count"]) for g in groups] == [(env.agents["ana"].id, 1)]


def test_tras_el_envio_no_se_puede_cerrar(env):
    from app.web.routes.alerts import complete_alert
    alert = _alert(env)
    _send(env, env.users["ana"], alert, "ana")

    response, html = _detail(env, env.users["ana"], alert)
    assert response.status_code == 200
    assert response.context["can_complete"] is False

    request = _request(env, env.users["ana"], f"/alerts/{alert.id}/complete", "POST", form={})
    response = asyncio.run(complete_alert(alert.id, request, db=env.db))
    assert _flash(response)["category"] == "error"
    env.db.expire_all()
    assert env.db.get(type(alert), alert.id).status != AlertStatus.COMPLETED


def test_tras_el_envio_la_cola_sigue_bloqueada(env):
    from app.services.alert_view import get_locked_alert_ids
    first = _alert(env, created_at=T0)
    second = _alert(env, created_at=T0 + timedelta(hours=1))
    assert get_locked_alert_ids(env.agents["ana"].id, env.db, env.moyza.id) == {second.id}
    _send(env, env.users["ana"], first, "ana")
    assert get_locked_alert_ids(env.agents["ana"].id, env.db, env.moyza.id) == {second.id}


def test_tras_el_envio_no_cambia_la_etapa_ni_el_estado(env):
    """Etapa visible (listado y paso Contactar), estado y paso por defecto."""
    from app.models.alert_follow_up import AlertFollowUp
    from app.web.routes.alerts import alerts_page
    alert = _alert(env)
    env.db.add(AlertFollowUp(alert_id=alert.id, action_type="CONTACTADO", notes="Llamado",
                             created_at=T0 + timedelta(hours=1), created_by=env.users["ana"].id))
    env.db.commit()
    status_before = alert.status

    _send(env, env.users["ana"], alert, "ana")
    env.db.expire_all()
    assert env.db.get(type(alert), alert.id).status == status_before

    response, _ = _detail(env, env.admin, alert)
    assert response.context["current_stage_label"] == "Contactado"

    request = _request(env, env.admin, "/alerts")
    response = asyncio.run(alerts_page(request, q="", status_filter=[], agent_id=None, page=None,
                                       per_page=None, b_q="", b_page=None, attention=None, db=env.db))
    stages = response.context["alert_stages"]
    assert stages[alert.id]["value"] == "CONTACTADO"


def test_alerta_sin_gestion_sigue_en_contactar(env):
    """Sin gestión real el paso por defecto sigue siendo Contactar."""
    _complete_profile(env)
    alert = _alert(env)
    _send(env, env.users["ana"], alert, "ana")
    response, _ = _detail(env, env.users["ana"], alert)
    assert response.context["step"] == "contact"
    assert response.context["current_stage_label"] is None


def test_tras_el_envio_no_hay_actividad_ni_cambia_la_agenda(env):
    from app.models.alert_follow_up import AlertFollowUp
    from app.services.dashboard_service import DashboardService
    from app.services.notification_service import run_follow_up_due
    alert = _alert(env)
    service = DashboardService(env.db, env.moyza.id)
    assert env.agents["ana"].id not in service.last_activity_by_agent([env.agents["ana"].id])

    _send(env, env.users["ana"], alert, "ana")
    assert env.agents["ana"].id not in service.last_activity_by_agent([env.agents["ana"].id])

    # Un seguimiento real con próxima acción vencida no queda tapado por un envío posterior
    other = _alert(env, created_at=T0 - timedelta(days=1))
    now = datetime.utcnow()
    env.db.add(AlertFollowUp(alert_id=other.id, action_type="CONTACTADO", notes="x",
                             next_action_date=now - timedelta(days=1),
                             created_at=now - timedelta(hours=2), created_by=env.users["ana"].id))
    env.db.commit()
    _send(env, env.users["ana"], other, "ana")
    agenda = service.agenda(env.agents["ana"], now=now)
    assert [row["alert_id"] for row in agenda["due"]] == [other.id]
    assert agenda["due"][0]["action_label"] == "Contactado"
    assert run_follow_up_due(env.db, now=now) == 1


def test_duplicados_no_cuentan_el_envio(env):
    from app.services.alert_duplicate_service import serialize_duplicates
    alert = _alert(env, prop_key="ana")
    _send(env, env.users["ana"], alert, "ana")
    env.db.expire_all()
    data = serialize_duplicates(env.db, {"open": [env.db.get(type(alert), alert.id)], "recent_closed": []})
    assert data["open"][0]["follow_ups"] == 0


# ---------------------------------------------------------------------------
# Historial de la alerta
# ---------------------------------------------------------------------------

def test_historial_muestra_el_envio_al_agente_y_al_admin(env):
    alert = _alert(env)
    _send(env, env.users["ana"], alert, "ana")
    for user in (env.users["ana"], env.admin):
        response, html = _detail(env, user, alert)
        assert "Propiedad enviada (WhatsApp abierto)" in html
        assert "Enviada por WhatsApp: Piso Centro" in html
    # La nota de reasignación sigue oculta al agente
    response, html = _detail(env, env.users["ana"], alert)
    assert not any(f.action_type == "REASIGNADA" for f in response.context["follow_ups"])


def test_el_agente_no_ve_envios_anteriores_a_su_asignacion(env):
    from app.services import alert_assignment_service as svc
    alert = _alert(env, "bea")
    _send(env, env.users["bea"], alert, "ana")
    svc.assign(env.db, alert, env.agents["ana"], env.admin, None, is_new=False, now=datetime.utcnow() + timedelta(seconds=5))
    env.db.commit()
    response, html = _detail(env, env.users["ana"], alert)
    assert "Propiedad enviada" not in html
    response, html = _detail(env, env.admin, alert)
    assert "Propiedad enviada (WhatsApp abierto)" in html


# ---------------------------------------------------------------------------
# Paso Propuesta: tarjetas con el botón
# ---------------------------------------------------------------------------

def test_propuesta_pinta_el_boton_y_la_fecha_del_envio(env):
    _complete_profile(env)
    alert = _alert(env)
    response, html = _detail(env, env.users["ana"], alert, step="proposal")
    assert f'action="/alerts/{alert.id}/send-property"' in html
    assert html.count("Enviar por WhatsApp</button>") >= 1
    assert f'href="{URL_1933}"' in html and "Ver en la web" in html
    assert "Sin enlace web" not in html                   # Piso Bea, sin enlace: sin aviso
    assert "Enviada el" not in html

    _send(env, env.users["ana"], alert, "ana")
    response, html = _detail(env, env.users["ana"], alert, step="proposal")
    assert response.context["sent_dates"].keys() == {env.props["ana"].id}
    assert "Enviada el " in html


def test_propuesta_sin_telefono_valido_no_pinta_el_boton(env):
    _complete_profile(env)
    alert = _alert(env, phone="123")
    response, html = _detail(env, env.users["ana"], alert, step="proposal")
    assert "Comprador sin teléfono válido" in html
    assert "send-property" not in html.split("Comprador sin teléfono válido")[0].rsplit("<article", 1)[-1]
    assert "Enviar por WhatsApp</button>" not in html


# ---------------------------------------------------------------------------
# Ficha del comprador
# ---------------------------------------------------------------------------

def test_ficha_registra_en_la_alerta_abierta_mas_reciente_del_agente(env):
    old_open = _alert(env, "ana", created_at=T0)
    new_open = _alert(env, "ana", created_at=T0 + timedelta(days=2))
    _alert(env, "ana", created_at=T0 + timedelta(days=5), status=AlertStatus.COMPLETED)
    bea_open = _alert(env, "bea", created_at=T0 + timedelta(days=9))

    response = _send_from_buyer(env, env.users["ana"], "ana")
    assert response.status_code == 303 and response.headers["location"].startswith("https://wa.me/34600111222?text=")
    assert [r.alert_id for r in _sent_rows(env)] == [new_open.id]

    # El admin: la abierta más reciente de cualquier agente
    _send_from_buyer(env, env.admin, "ana")
    assert sorted(r.alert_id for r in _sent_rows(env)) == sorted([new_open.id, bea_open.id])
    assert old_open.id not in {r.alert_id for r in _sent_rows(env)}


def test_ficha_sin_abiertas_usa_la_cerrada_mas_reciente(env):
    _alert(env, "ana", created_at=T0, status=AlertStatus.COMPLETED)
    latest_closed = _alert(env, "ana", created_at=T0 + timedelta(days=1), status=AlertStatus.CANCELLED)
    assert _send_from_buyer(env, env.users["ana"], "ana").status_code == 303
    assert [r.alert_id for r in _sent_rows(env)] == [latest_closed.id]


def test_ficha_sin_alerta_propia_no_pinta_el_boton_y_rechaza(env):
    """Ana registró al comprador (lo ve) pero la única alerta es de Bea."""
    _complete_profile(env)
    _alert(env, "bea")
    response, html = _buyer_html(env, env.users["ana"])
    assert response.status_code == 200
    assert "Piso Centro" in html                           # la pestaña sí tiene tarjetas
    assert response.context["send_action"] is None
    assert "send-property" not in html and "Enviar por WhatsApp" not in html

    response = _send_from_buyer(env, env.users["ana"], "ana")
    assert response.status_code == 302 and response.headers["location"] == f"/buyers/{env.buyer.id}?tab=matches"
    assert _flash(response)["category"] == "error"
    assert _sent_rows(env) == []


def test_ficha_con_alerta_pinta_boton_y_enviada(env):
    _complete_profile(env)
    _alert(env, "ana")
    response, html = _buyer_html(env, env.users["ana"])
    assert f'action="/buyers/{env.buyer.id}/send-property"' in html
    assert "Enviada el" not in html
    _send_from_buyer(env, env.users["ana"], "ana")
    response, html = _buyer_html(env, env.users["ana"])
    assert response.context["sent_dates"].keys() == {env.props["ana"].id}
    assert "Enviada el " in html


def test_ficha_errores_vuelven_a_la_ficha(env):
    _alert(env, "ana")
    response = _send_from_buyer(env, env.users["ana"], "moes")     # sin enlace
    assert response.status_code == 302 and response.headers["location"] == f"/buyers/{env.buyer.id}?tab=matches"
    env.buyer.phone = "12"
    env.db.commit()
    response = _send_from_buyer(env, env.users["ana"], "ana")
    assert "wa.me" not in response.headers["location"]
    assert "teléfono válido" in _flash(response)["message"]
    assert _sent_rows(env) == []


# ---------------------------------------------------------------------------
# Tarjeta (render directo del macro)
# ---------------------------------------------------------------------------

def _card(**kwargs):
    from app.web.template_env import templates
    company = SimpleNamespace(name="MOYZA", primary_color="#000000", property_url_template=MOYZA_TEMPLATE)
    prop = SimpleNamespace(id=7, title="Piso Centro", business_type="Venta", company_id=1, company=company,
                           address="Calle Secreta 1", city="Jaén", zona="Centro", num_dormitorios=2,
                           num_banos_aseos=1, price=120000, agent=None, referencia="1933", public_url=None)
    for key in ("referencia", "public_url"):
        if key in kwargs:
            setattr(prop, key, kwargs.pop(key))
    source = ('{% from "components/property_card.html" import property_card %}'
              '{{ property_card(prop, **kw) }}')
    return templates.env.from_string(source).render(prop=prop, kw=kwargs)


def test_tarjeta_sin_send_action_como_antes():
    html = _card()
    assert "send-property" not in html and "Enviar por WhatsApp" not in html
    assert "Ver en la web" not in html and "data-sent-label" not in html


def test_tarjeta_con_send_action():
    html = _card(send_action="/alerts/5/send-property", buyer_phone="600111222")
    assert 'action="/alerts/5/send-property"' in html and 'target="_blank"' in html
    assert 'name="property_id" value="7"' in html
    assert "data-once" not in html                         # se puede reenviar
    assert "Enviar por WhatsApp</button>" in html
    assert f'href="{URL_1933}"' in html and 'rel="noopener noreferrer"' in html
    assert "Enviada el" not in html and "data-sent-label" in html
    assert "Sin enlace web" not in html and "Comprador sin teléfono válido" not in html
    # Sin logo de marca ni verde de WhatsApp
    assert "green" not in html


def test_tarjeta_con_sent_at():
    html = _card(send_action="/x", buyer_phone="600111222", sent_at=datetime(2026, 11, 3, 10, 0))
    assert "Enviada el 03/11" in html


def test_tarjeta_sin_enlace():
    html = _card(send_action="/x", buyer_phone="600111222", referencia=None)
    assert "Sin enlace" not in html
    assert "Enviar por WhatsApp</button>" not in html and "Ver en la web" not in html


def test_tarjeta_sin_telefono():
    for phone in (None, "", "123"):
        html = _card(send_action="/x", buyer_phone=phone)
        assert "Comprador sin teléfono válido" in html
        assert "Enviar por WhatsApp</button>" not in html
        assert "Ver en la web" in html                     # se puede comprobar la ficha


# ---------------------------------------------------------------------------
# Propiedades: campo "Enlace en la web" y botón del listado
# ---------------------------------------------------------------------------

def _update(env, prop, public_url):
    from app.models.client import Client
    from app.web.routes.properties import update_property
    client = env.db.query(Client).first()
    if client is None:
        client = Client(name="Propietario", phone="34600000000")
        client.companies.append(env.moyza)
        env.db.add(client)
        env.db.commit()
    form = {"property_id": str(prop.id), "title": prop.title, "price": "120000", "client_id": str(client.id),
            "agent_id": str(prop.agent_id), "address": prop.address, "city": prop.city, "description": "-",
            "status": "Activa", "referencia": prop.referencia or "", "public_url": public_url,
            "property_type": "Piso", "business_type": "Venta", "zona": "Centro", "num_dormitorios": "2",
            "num_banos_aseos": "1"}
    request = _request(env, env.admin, "/properties/update", "POST", form=form)
    return asyncio.run(update_property(
        request, property_id=prop.id, title=prop.title, price=120000.0, client_id=client.id,
        agent_id=prop.agent_id, address=prop.address, city=prop.city, description="-", status="Activa",
        auto_send_report=False, report_frequency=None, report_day=None, report_hour=None, db=env.db,
    ))


def test_editar_guarda_el_enlace_y_lo_deja_en_el_historial(env):
    from app.models.property import Property
    from app.models.property_change_log import PropertyChangeLog
    prop = env.props["moes"]
    prop.company_id = env.moyza.id                     # editable desde la empresa activa
    env.db.commit()
    response = _update(env, prop, "  https://moes.example/ficha/55  ")
    assert _flash(response)["category"] == "success"
    env.db.expire_all()
    assert env.db.get(Property, prop.id).public_url == "https://moes.example/ficha/55"
    log = env.db.query(PropertyChangeLog).filter_by(property_id=prop.id, field_name="public_url").one()
    assert log.field_label == "Enlace en la web" and log.new_value == "https://moes.example/ficha/55"

    # Vaciarlo vuelve al automático
    _update(env, env.db.get(Property, prop.id), "")
    env.db.expire_all()
    assert env.db.get(Property, prop.id).public_url is None


def test_editar_rechaza_un_enlace_no_web(env):
    from app.models.property import Property
    prop = env.props["ana"]
    response = _update(env, prop, "javascript:alert(1)")
    assert _flash(response)["category"] == "error"
    assert "http" in _flash(response)["message"]
    env.db.expire_all()
    assert env.db.get(Property, prop.id).public_url is None


def test_filas_de_solo_lectura_llevan_el_enlace(env):
    from app.models.property import Property
    from app.web.routes.properties import _readonly_property_rows
    env.props["moes"].public_url = "https://moes.example/ficha/55"
    env.db.commit()
    rows = {r["title"]: r for r in _readonly_property_rows(env.db.query(Property), "")}
    assert rows["Piso Centro"]["public_url"] == URL_1933
    assert rows["Piso Bea"]["public_url"] is None
    assert rows["Piso MOES"]["public_url"] == "https://moes.example/ficha/55"
    assert "client_id" not in rows["Piso Centro"]


def test_registro_de_actividad_nombra_las_rutas():
    from app.services.activity_log_view import describe
    for path in ("/alerts/12/send-property", "/buyers/3/send-property"):
        row = describe("POST", path)
        assert row["label"] == "Envió propiedad al comprador" and row["module"] == "Compradores"
