"""
Tests de ruta de Resultados Comerciales (PLAN_RESULTADOS_COMERCIALES.md, fase 5).

Integración contra la app levantada (patrón de test_company_isolation.py; se
omiten si la app no responde): redirecciones de las rutas antiguas, pestañas
y períodos, formulario de objetivos con solo los campos del período,
validación y aislamiento por empresa al cambiar de empresa. Crean un agente
en MOYZA y MOES, una propiedad en MOES y un usuario agente; lo borran todo
al final.

Ejecución dentro del contenedor:
    docker exec moyza_backend python -m pytest tests/test_commercial_results.py -q
"""
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

import pytest

BASE_URL = os.getenv("MOYZA_TEST_BASE_URL", "http://localhost:8000")
ADMIN_EMAIL = os.getenv("MOYZA_TEST_ADMIN_EMAIL", "admin@moyza.com")
TAG = "PYTEST-RESULTADOS"
AGENT_EMAIL = "pytest.resultados.agente@example.com"


def _server_up() -> bool:
    try:
        urllib.request.urlopen(BASE_URL + "/", timeout=3)
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _server_up(),
    reason=f"La app no responde en {BASE_URL}; tests de integración omitidos",
)


class Client:
    """Peticiones con cookies de sesión y empresa, sin seguir redirecciones."""

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    def __init__(self, email: str, company: str):
        from app.core.security import create_access_token
        token = create_access_token({"sub": email})
        self.cookie = f"access_token={token}; active_company={company}"
        self.opener = urllib.request.build_opener(self._NoRedirect)

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

    def post(self, path, data):
        return self._request("POST", path, data)


@pytest.fixture(scope="module")
def setup():
    """Agente en las dos empresas con una captación de venta solo en MOES."""
    from app.db.session import SessionLocal
    from app.models.agent import Agent
    from app.models.company import Company
    from app.models.property import Property
    from app.models.role import Role
    from app.models.user import User

    db = SessionLocal()
    moyza = db.query(Company).filter_by(code="MOYZA").one()
    moes = db.query(Company).filter_by(code="MOES").one()
    role = db.query(Role).filter(Role.name.ilike("agent")).first()

    agent = Agent(name=f"{TAG} AGENTE", email=AGENT_EMAIL)
    agent.companies.extend([moyza, moes])
    user = User(email=AGENT_EMAIL, full_name=f"{TAG} usuario", hashed_password="pytest-sin-login",
                role_id=role.id if role else None, is_active=True)
    user.companies.append(moyza)
    db.add_all([agent, user])
    db.flush()
    prop = Property(title=f"{TAG} PROP", company_id=moes.id, agent_id=agent.id,
                    business_type="Venta", market_entry_date=datetime.utcnow())
    db.add(prop)
    db.commit()

    data = {"agent_id": agent.id, "property_id": prop.id, "moyza_id": moyza.id, "moes_id": moes.id}
    yield data

    from app.models.agent_performance_report import AgentPerformanceReport
    from app.models.agent_performance_target import AgentPerformanceTarget
    db.query(AgentPerformanceTarget).filter_by(agent_id=agent.id).delete(synchronize_session=False)
    db.query(AgentPerformanceReport).filter_by(agent_id=agent.id).delete(synchronize_session=False)
    db.query(Property).filter(Property.id == prop.id).delete(synchronize_session=False)
    db.query(User).filter(User.email == AGENT_EMAIL).delete(synchronize_session=False)
    db.query(Agent).filter(Agent.email == AGENT_EMAIL).delete(synchronize_session=False)
    db.commit()
    db.close()


@pytest.fixture(scope="module")
def moyza():
    return Client(ADMIN_EMAIL, "MOYZA")


@pytest.fixture(scope="module")
def moes():
    return Client(ADMIN_EMAIL, "MOES")


def _agent_card(body: str, agent_id: int) -> str:
    """HTML de la tarjeta del agente en la pestaña Rendimiento."""
    start = body.index(f'id="agent-{agent_id}"')
    end = body.find('id="agent-', start + 10)
    return body[start:end if end != -1 else len(body)]


def _text(html: str) -> str:
    html = re.sub(r"<script.*?</script>", " ", html, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


# ---------------------------------------------------------------------------
# Redirecciones de las rutas antiguas
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("old, expected", [
    ("/alerts-dashboard", "/commercial-results?tab=compradores"),
    ("/alerts-dashboard?tab=general", "/commercial-results?tab=compradores"),
    ("/alerts-dashboard?tab=rendimiento&period_type=MONTHLY&period_start=2026-09-01",
     "/commercial-results?tab=rendimiento&period_type=MONTHLY&period_start=2026-09-01"),
    ("/performance-reports", "/commercial-results?tab=rendimiento"),
    ("/performance-reports?period_type=WEEKLY&period_start=2026-08-24",
     "/commercial-results?period_type=WEEKLY&period_start=2026-08-24&tab=rendimiento"),
])
def test_rutas_antiguas_redirigen_301(moyza, old, expected):
    status, _, headers = moyza.get(old)
    assert status == 301
    assert headers.get("location") == expected


# ---------------------------------------------------------------------------
# Pestañas, períodos y permisos
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "/commercial-results",
    "/commercial-results?tab=rendimiento&period_type=WEEKLY",
    "/commercial-results?tab=rendimiento&period_type=MONTHLY&period_start=2026-01-15",
    "/commercial-results?tab=rendimiento&period_type=YEARLY&period_start=2025-01-01",
    "/commercial-results?tab=evolucion",
    "/commercial-results?tab=evolucion&year=2024",
    "/commercial-results?tab=compradores",
    "/commercial-results?tab=desconocida&period_type=XX&period_start=no-fecha",
])
def test_pestanas_y_periodos_renderizan(moyza, moes, setup, path):
    for client in (moyza, moes):
        status, body, _ = client.get(path)
        assert status == 200
        assert "Resultados Comerciales" in body


def test_selector_de_periodo_incluye_anio(moyza, setup):
    body = moyza.get("/commercial-results?tab=rendimiento&period_type=YEARLY")[1]
    text = _text(body)
    for label in ("Semana", "Mes", "Año"):
        assert label in text
    assert 'href="/commercial-results?tab=rendimiento&period_type=YEARLY"' in body
    assert f" {datetime.utcnow().year} " in text


def test_agente_no_accede(setup):
    agent = Client(AGENT_EMAIL, "MOYZA")
    status, _, headers = agent.get("/commercial-results")
    assert status == 302 and headers.get("location") == "/alerts"
    status, _, headers = agent.post(f"/commercial-results/{setup['agent_id']}/targets",
                                    {"period_type": "WEEKLY", "period_start_str": "", "target_bajadas": "1"})
    assert status == 302 and headers.get("location") == "/alerts"


def test_sidebar_renombrado(moyza):
    body = moyza.get("/commercial-results")[1]
    assert "Resultados Comerciales" in body
    assert 'href="/commercial-results"' in body
    assert "Dashboard Compradores" not in body


# ---------------------------------------------------------------------------
# Objetivos: solo los campos del período
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("period_type, expected", [
    ("WEEKLY", {"target_captaciones_crm", "target_bajadas"}),
    ("MONTHLY", {"target_captaciones_crm", "target_bajadas", "target_cierres"}),
    ("YEARLY", {"target_captaciones_crm", "target_bajadas", "target_cierres"}),
])
def test_formulario_de_objetivos_solo_campos_del_periodo(moyza, setup, period_type, expected):
    body = moyza.get(f"/commercial-results?tab=rendimiento&period_type={period_type}")[1]
    card = _agent_card(body, setup["agent_id"])
    fields = set(re.findall(r'name="(target_[a-z_]+)"', card))
    assert fields == expected


def test_guardar_objetivos_ignora_campos_fuera_del_periodo(moyza, setup):
    from app.db.session import SessionLocal
    from app.models.agent_performance_target import AgentPerformanceTarget

    status, _, headers = moyza.post(f"/commercial-results/{setup['agent_id']}/targets", {
        "period_type": "WEEKLY", "period_start_str": "",
        "target_captaciones_crm": "4", "target_bajadas": "2",
        "target_cierres": "9", "target_contactos": "7", "target_hojas_visita": "5",
    })
    assert status == 302
    assert f"open={setup['agent_id']}" in headers["location"]

    db = SessionLocal()
    target = db.query(AgentPerformanceTarget).filter_by(
        agent_id=setup["agent_id"], company_id=setup["moyza_id"], period_type="WEEKLY").one()
    assert (target.target_captaciones_crm, target.target_bajadas) == (4, 2)
    assert target.target_cierres is None
    assert target.target_contactos is None and target.target_hojas_visita is None
    db.close()


@pytest.mark.parametrize("value", ["-1", "abc", "2.5"])
def test_objetivo_invalido_no_se_guarda(moyza, setup, value):
    from app.db.session import SessionLocal
    from app.models.agent_performance_target import AgentPerformanceTarget

    status, _, _ = moyza.post(f"/commercial-results/{setup['agent_id']}/targets", {
        "period_type": "MONTHLY", "period_start_str": "", "target_bajadas": value,
    })
    assert status == 302
    db = SessionLocal()
    assert db.query(AgentPerformanceTarget).filter_by(
        agent_id=setup["agent_id"], period_type="MONTHLY").count() == 0
    db.close()


def test_tipo_de_periodo_invalido(moyza, setup):
    status, _, headers = moyza.post(f"/commercial-results/{setup['agent_id']}/targets", {
        "period_type": "DAILY", "period_start_str": "", "target_bajadas": "1",
    })
    assert status == 302 and headers["location"] == "/commercial-results?tab=rendimiento"


# ---------------------------------------------------------------------------
# Aislamiento por empresa
# ---------------------------------------------------------------------------

def test_resultados_y_objetivos_cambian_con_la_empresa(moyza, moes, setup):
    agent_id = setup["agent_id"]

    # Objetivo anual de captaciones solo en MOES
    moes.post(f"/commercial-results/{agent_id}/targets", {
        "period_type": "YEARLY", "period_start_str": "", "target_captaciones_crm": "3",
    })

    url = "/commercial-results?tab=rendimiento&period_type=YEARLY"
    moes_card = _text(_agent_card(moes.get(url)[1], agent_id))
    moyza_card = _text(_agent_card(moyza.get(url)[1], agent_id))

    # La captación es de MOES: 1 venta allí, 0 en MOYZA
    assert re.search(r"Captaciones CRM Obj\. 1 V 1 · A 0 obj\. 3 · 33 %", moes_card)
    assert re.search(r"Captaciones CRM Obj\. 0 V 0 · A 0 Sin objetivo", moyza_card)
    assert "Cumplimiento 33 %" in moes_card
    assert "Cumplimiento" not in moyza_card

    # Evolución: el JSON del año también cambia con la empresa
    moes_json = moes.get("/commercial-results?tab=evolucion")[1]
    moyza_json = moyza.get("/commercial-results?tab=evolucion")[1]
    assert f'"id": {agent_id}' in moes_json and f'"id": {agent_id}' in moyza_json
    assert '"target": 3' in moes_json
    assert '"target": 3' not in moyza_json


def test_switch_company_vuelve_a_resultados(moyza):
    next_url = "/commercial-results?tab=evolucion&year=2025"
    status, _, headers = moyza.post("/switch-company", {"code": "MOES", "next": next_url})
    assert status == 303
    assert headers.get("location") == next_url
    assert "active_company=MOES" in headers.get("set-cookie", "")
