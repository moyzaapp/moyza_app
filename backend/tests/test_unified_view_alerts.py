"""
Vista unificada de alertas y compradores para agentes de varias empresas
(PLAN_VISTA_UNIFICADA_AGENTES.md, fase B).

- Un agente en MOYZA y MOES (sin "Puede cambiar de empresa") ve en `/alerts`
  las alertas y compradores de las dos, con distintivo de empresa y sin el
  banner "cambia de empresa"; abre el detalle de la de la otra empresa; crea
  un comprador o una búsqueda general eligiendo la empresa.
- Con `company_switch_enabled` sigue como antes: solo la activa y el banner.
- El admin no cambia.
- La cola secuencial sigue siendo por empresa (unión de bloqueos).

Rutas en proceso contra una SQLite en memoria (entorno de
tests/test_alert_search.py: MOYZA y MOES; Ana y Bea agentes de MOYZA; Piso
MOES de Ana). Aquí Ana pasa a estar también en MOES. El estado de empresa de
la petición se resuelve con `resolve_company_scope`, como el middleware.

    cd backend && python -m pytest tests/test_unified_view_alerts.py -q
"""
import asyncio
from datetime import timedelta
from urllib.parse import urlencode

from starlette.requests import Request

from app.core.constants import AlertOrigin, AlertStatus
from tests.test_alert_search import (  # noqa: F401  (env es un fixture)
    T0,
    _flash,
    _property_alert,
    env,
)


def _request(env, user, path, method="GET", form=None, cookie_company=None, query=""):
    """Petición con el estado de empresa que dejaría AuthMiddleware para `user`."""
    from app.web.dependencies.company import resolve_company_scope

    allowed = [env.moyza, env.moes] if user is env.admin else [
        c for c in (env.moyza, env.moes)
        if c in user.companies or c in env.agents_by_email.get(user.email, _NoAgent).companies
    ]
    scope = resolve_company_scope(user, allowed, cookie_company)
    body = urlencode(form or {}, doseq=True).encode()
    headers = [(b"host", b"testserver")]
    if form is not None:
        headers.append((b"content-type", b"application/x-www-form-urlencoded"))

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request({
        "type": "http", "method": method, "scheme": "http", "server": ("testserver", 80),
        "path": path, "root_path": "", "query_string": query.encode(), "headers": headers,
        "state": {"user": user, "company": scope.company, "allowed_companies": scope.allowed,
                  "company_ids": scope.company_ids, "unified_view": scope.unified_view},
    }, receive)


class _NoAgent:
    companies = []


def _setup_dual(env, switch=False):
    """Ana en MOYZA y MOES; una alerta suya en cada empresa. Devuelve (moyza, moes)."""
    from app.models.buyer import Buyer
    from app.models.property_alert import PropertyAlert
    from app.services import alert_assignment_service as svc

    env.agents["ana"].companies.append(env.moes)
    env.users["ana"].companies.append(env.moes)
    env.users["ana"].company_switch_enabled = switch
    env.agents_by_email = {a.email: a for a in env.agents.values()}
    moes_buyer = Buyer(name="Marta MOES", phone="34600999111", company_id=env.moes.id,
                       created_by=env.users["ana"].id)
    env.db.add(moes_buyer)
    env.db.flush()

    moyza_alert = _property_alert(env, "ana", "ana")
    moes_alert = PropertyAlert(property=env.props["moes"], company_id=env.moes.id, buyer_id=moes_buyer.id,
                               lead_name=moes_buyer.name, lead_phone=moes_buyer.phone, business_type="Venta",
                               status=AlertStatus.PENDING, priority="NORMAL", created_by=env.admin.id,
                               created_at=T0 + timedelta(hours=1))
    env.db.add(moes_alert)
    svc.assign(env.db, moes_alert, env.agents["ana"], env.admin, None, is_new=True, now=T0 + timedelta(hours=1))
    env.db.commit()
    return moyza_alert, moes_alert


def _list(env, user, cookie_company=None):
    from app.web.routes.alerts import alerts_page
    request = _request(env, user, "/alerts", cookie_company=cookie_company)
    response = asyncio.run(alerts_page(request, q="", status_filter=[], agent_id=None, page=None,
                                       per_page=None, b_q="", b_page=None, attention=None, db=env.db))
    return response, response.body.decode("utf-8")


def _detail(env, user, alert, cookie_company=None):
    from app.web.routes.alerts import alert_detail
    request = _request(env, user, f"/alerts/{alert.id}", cookie_company=cookie_company)
    response = asyncio.run(alert_detail(alert.id, request, step=None, confirm_property=None,
                                        company=None, db=env.db))
    return response, (response.body.decode("utf-8") if response.status_code == 200 else "")


def _alerts_table(html):
    start = html.find('id="alertas"')
    return html[start:html.find('id="compradores"', start)]


def _create_buyer(env, user, company_id=None, name="Nuevo Comprador"):
    from app.web.routes.alerts import create_buyer
    request = _request(env, user, "/buyers/create", "POST", form={})
    return asyncio.run(create_buyer(request, name=name, phone_country_code=None, phone_country_code_other=None,
                                    phone_number=None, phone=None, email=None, notes=None,
                                    company_id=company_id, db=env.db))


def _create_alert(env, user, **form):
    from app.web.routes.alerts import create_alert
    data = dict(
        property_id=None, buyer_id=None, buyer_name=None, buyer_phone_country_code=None,
        buyer_phone_number=None, buyer_phone=None, buyer_email=None, source="Llamada",
        alert_type="LEAD_INTERES", message=None, priority="NORMAL", business_type="Venta",
        confirm_duplicate=None, confirm_new_buyer="1", agent_id=None, assignment_reason=None,
        company_id=None,
    )
    data.update(form)
    request = _request(env, user, "/alerts/create", "POST", form={})
    return asyncio.run(create_alert(request, db=env.db, **data))


# ---------------------------------------------------------------------------
# Listado y detalle
# ---------------------------------------------------------------------------

def test_agente_en_dos_empresas_ve_las_alertas_de_ambas_con_distintivo(env):
    moyza_alert, moes_alert = _setup_dual(env)

    response, html = _list(env, env.users["ana"], cookie_company="MOYZA")
    assert response.status_code == 200
    table = _alerts_table(html)
    assert "Juan Comprador" in table and "Marta MOES" in table
    # Distintivo de la empresa de cada alerta, y de cada comprador
    assert 'title="Alerta de MOYZA"' in table and 'title="Alerta de MOES PREMIUM"' in table
    assert 'title="Comprador de MOES PREMIUM"' in html
    # Sin banner ni botón de cambio de empresa
    assert "compradores asignados en" not in html and "comprador asignado en" not in html
    assert 'action="/switch-company"' not in html
    assert response.context["other_company_alerts"] == []
    # Contadores con las dos empresas
    assert response.context["pending_count"] + response.context["in_progress_count"] == 2
    # Alta de comprador con select de empresa (la principal, MOYZA, preseleccionada)
    assert 'id="cbCompany"' in html
    assert [c.code for c in response.context["creation_companies"]] == ["MOYZA", "MOES"]


def test_agente_abre_el_detalle_de_la_alerta_de_la_otra_empresa(env):
    _, moes_alert = _setup_dual(env)
    env.users["ana"].primary_company_id = env.moyza.id

    response, html = _detail(env, env.users["ana"], moes_alert)
    assert response.status_code == 200
    assert 'title="Alerta de MOES PREMIUM"' in html
    # Su propiedad de MOES enlaza a la ficha (empresa del usuario) y sin "Cambia de empresa"
    assert response.context["property_other_company"] is False
    assert f'href="/properties/{env.props["moes"].id}"' in html
    assert "Cambia de empresa para ver la ficha" not in html


def test_agente_con_una_sola_empresa_sin_distintivo(env):
    _property_alert(env, "ana", "ana")
    env.agents_by_email = {a.email: a for a in env.agents.values()}

    response, html = _list(env, env.users["ana"])
    assert response.status_code == 200
    assert "Juan Comprador" in _alerts_table(html)
    assert 'title="Alerta de' not in html
    assert response.context["creation_companies"] == []
    assert 'id="cbCompany"' not in html


# ---------------------------------------------------------------------------
# Altas con empresa
# ---------------------------------------------------------------------------

def test_agente_crea_un_comprador_eligiendo_empresa(env):
    from app.models.buyer import Buyer
    _setup_dual(env)

    response = _create_buyer(env, env.users["ana"], company_id=str(env.moes.id), name="Lucía Nueva")
    assert response.status_code == 302 and _flash(response)["category"] == "success"
    buyer = env.db.query(Buyer).filter_by(name="Lucía Nueva").one()
    assert buyer.company_id == env.moes.id

    # Sin elegir: la principal (por defecto la primera, MOYZA)
    _create_buyer(env, env.users["ana"], name="Pedro Principal")
    assert env.db.query(Buyer).filter_by(name="Pedro Principal").one().company_id == env.moyza.id

    # Una empresa que no es suya: error y nada creado
    response = _create_buyer(env, env.users["ana"], company_id="999", name="Fuera")
    assert _flash(response)["category"] == "error"
    assert env.db.query(Buyer).filter_by(name="Fuera").first() is None


def test_admin_no_puede_crear_comprador_en_otra_empresa_que_la_activa(env):
    from app.models.buyer import Buyer
    response = _create_buyer(env, env.admin, company_id=str(env.moes.id), name="Admin Cruzado")
    assert _flash(response)["category"] == "error"
    assert env.db.query(Buyer).filter_by(name="Admin Cruzado").first() is None
    _create_buyer(env, env.admin, name="Admin Normal")
    assert env.db.query(Buyer).filter_by(name="Admin Normal").one().company_id == env.moyza.id


def test_busqueda_general_con_comprador_nuevo_en_la_empresa_elegida(env):
    from app.models.property_alert import PropertyAlert
    _setup_dual(env)

    response = _create_alert(env, env.users["ana"], buyer_name="Rosa Busca", company_id=str(env.moes.id))
    assert _flash(response)["category"] == "success"
    alert = env.db.query(PropertyAlert).filter_by(lead_name="Rosa Busca").one()
    assert alert.origin == AlertOrigin.SEARCH
    assert alert.company_id == env.moes.id and alert.buyer.company_id == env.moes.id
    assert alert.agent_id == env.agents["ana"].id


def test_alerta_con_propiedad_va_a_la_empresa_de_la_propiedad(env):
    from app.models.property_alert import PropertyAlert
    _setup_dual(env)

    # Comprador nuevo sobre su propiedad de MOES: alerta y comprador en MOES
    response = _create_alert(env, env.users["ana"], buyer_name="Iván Ref", property_id=env.props["moes"].id)
    assert _flash(response)["category"] == "success"
    alert = env.db.query(PropertyAlert).filter_by(lead_name="Iván Ref").one()
    assert alert.company_id == env.moes.id and alert.buyer.company_id == env.moes.id

    # Comprador existente de MOYZA sobre la propiedad de MOES: no se mezclan
    response = _create_alert(env, env.users["ana"], buyer_id=env.buyer.id, property_id=env.props["moes"].id,
                             confirm_new_buyer=None)
    flash = _flash(response)
    assert flash["category"] == "error" and "asóciala desde la Propuesta" in flash["message"]


# ---------------------------------------------------------------------------
# Vista por empresa (opción por usuario) y admin
# ---------------------------------------------------------------------------

def test_agente_con_company_switch_enabled_mantiene_el_comportamiento_anterior(env):
    moyza_alert, moes_alert = _setup_dual(env, switch=True)

    response, html = _list(env, env.users["ana"], cookie_company="MOYZA")
    table = _alerts_table(html)
    assert "Juan Comprador" in table and "Marta MOES" not in table
    assert 'title="Alerta de' not in html
    # Banner con el cambio de empresa
    assert "Tienes 1 comprador asignado en MOES PREMIUM" in html
    assert 'action="/switch-company"' in html and 'name="code" value="MOES"' in html
    assert response.context["creation_companies"] == []

    # La de MOES no se abre con MOYZA activa; con MOES activa, sí
    response, _ = _detail(env, env.users["ana"], moes_alert, cookie_company="MOYZA")
    assert response.status_code == 302 and _flash(response)["message"] == "Alerta no encontrada"
    response, _ = _detail(env, env.users["ana"], moes_alert, cookie_company="MOES")
    assert response.status_code == 200


def test_admin_sin_cambios(env):
    moyza_alert, moes_alert = _setup_dual(env)

    response, html = _list(env, env.admin, cookie_company="MOYZA")
    table = _alerts_table(html)
    assert "Juan Comprador" in table and "Marta MOES" not in table
    assert 'title="Alerta de' not in html
    assert response.context["creation_companies"] == []
    response, _ = _detail(env, env.admin, moes_alert, cookie_company="MOYZA")
    assert response.status_code == 302

    response, html = _list(env, env.admin, cookie_company="MOES")
    table = _alerts_table(html)
    assert "Marta MOES" in table and "Juan Comprador" not in table


# ---------------------------------------------------------------------------
# Cola secuencial
# ---------------------------------------------------------------------------

def test_cola_por_empresa_unida_en_la_vista_unificada(env):
    from app.models.property_alert import PropertyAlert
    from app.services import alert_assignment_service as svc
    from app.services.alert_view import get_locked_alert_ids

    moyza_alert, moes_alert = _setup_dual(env)
    # Segunda de MOES, posterior: bloqueada por la primera de MOES (sin seguimiento)
    later = PropertyAlert(company_id=env.moes.id, origin=AlertOrigin.SEARCH, buyer_id=moes_alert.buyer_id,
                          lead_name="Marta MOES 2", business_type="Alquiler", status=AlertStatus.PENDING,
                          priority="NORMAL", created_by=env.admin.id, created_at=T0 + timedelta(hours=2))
    env.db.add(later)
    svc.assign(env.db, later, env.agents["ana"], env.admin, None, is_new=True, now=T0 + timedelta(hours=2))
    env.db.commit()

    ana = env.agents["ana"].id
    # MOES no bloquea por la de MOYZA (más antigua y sin gestión): la cola es por empresa
    assert get_locked_alert_ids(ana, env.db, env.moes.id) == {later.id}
    assert get_locked_alert_ids(ana, env.db, env.moyza.id) == set()
    assert get_locked_alert_ids(ana, env.db, [env.moyza.id, env.moes.id]) == {later.id}

    response, html = _list(env, env.users["ana"])
    assert response.context["locked_alert_ids"] == {later.id}
    response, _ = _detail(env, env.users["ana"], later)
    assert response.status_code == 302
