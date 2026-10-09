"""
Tests de visitas a propiedades de otros agentes y visitas con dos agentes
(PLAN_VISITAS_AGENTES.md).

- Unitarios (sin base de datos): filtro visits_for_agent, validación de los
  agentes del formulario y agente que firma la ficha.
- Con base de datos (se omiten si no hay conexión): hojas_visita del informe
  de desempeño, dentro de una transacción que se deshace al terminar.
- Integración contra la app levantada (patrón de test_company_isolation.py,
  se omiten si la app no responde): un agente registra una visita en una
  propiedad ajena y la ven él y el captador. Crea datos en MOES y los borra.

Ejecución dentro del contenedor:
    docker exec moyza_backend python -m pytest tests/test_visit_agents.py -q
"""
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from app.models.agent import Agent
from app.models.property import Property
from app.models.property_visit import PropertyVisit
from app.services.company_scope import visit_agent_clause
from app.services.company_scope import visits_for_agent
from app.services.visit_agents import VisitAgentsError
from app.services.visit_agents import parse_visit_agents
from app.services.visit_agents import resolve_visit_agents
from app.services.visit_agents import visit_agents_locked


# ---------------------------------------------------------------------------
# visits_for_agent
# ---------------------------------------------------------------------------

class _CaptureQuery:
    def __init__(self):
        self.criteria = []

    def filter(self, *criteria):
        self.criteria.extend(criteria)
        return self


def _sql(clause):
    return str(clause.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


class TestVisitsForAgent:

    def test_principal_o_acompanante(self):
        sql = _sql(visit_agent_clause(7))
        assert "property_visits.agent_id = 7" in sql
        assert "property_visits.companion_agent_id = 7" in sql
        assert " OR " in sql

    def test_no_filtra_por_captador(self):
        """El captador que no participó no entra por este filtro."""
        assert "properties" not in _sql(visit_agent_clause(7))

    def test_aplica_el_filtro_a_la_consulta(self):
        query = visits_for_agent(_CaptureQuery(), 3)
        assert len(query.criteria) == 1
        assert _sql(query.criteria[0]) == _sql(visit_agent_clause(3))


# ---------------------------------------------------------------------------
# Validación de agentes del formulario
# ---------------------------------------------------------------------------

def agent(id, name=None):
    return SimpleNamespace(id=id, name=name or f"Agente {id}")


# Agentes de la empresa activa; el 99 es de la otra empresa
COMPANY_AGENTS = {1: agent(1), 2: agent(2), 3: agent(3)}
ALL_AGENTS = {**COMPANY_AGENTS, 99: agent(99)}


def lookup(agent_id):
    return COMPANY_AGENTS.get(agent_id)


def lookup_any(agent_id):
    return ALL_AGENTS.get(agent_id)


def resolve(form, *, admin=False, current=None, fixed=None):
    return resolve_visit_agents(
        form,
        is_admin_user=admin,
        current_agent=current,
        lookup_agent=lookup,
        lookup_any_agent=lookup_any,
        fixed_agent_id=fixed,
    )


class TestResolveVisitAgents:

    def test_agente_solo_es_el_principal(self):
        assert resolve({"visit_mode": "solo"}, current=agent(1)) == (1, None)

    def test_sin_modo_es_solo(self):
        assert resolve({"companion_agent_id": "2"}, current=agent(1)) == (1, None)

    def test_agente_no_puede_suplantar_al_principal(self):
        form = {"agent_id": "2", "visit_mode": "solo"}
        assert resolve(form, current=agent(1)) == (1, None)

    def test_agente_acompanado(self):
        form = {"visit_mode": "acompanado", "companion_agent_id": "2"}
        assert resolve(form, current=agent(1)) == (1, 2)

    def test_acompanante_distinto_del_principal(self):
        form = {"visit_mode": "acompanado", "companion_agent_id": "1"}
        with pytest.raises(VisitAgentsError, match="distinto"):
            resolve(form, current=agent(1))

    def test_acompanante_obligatorio_si_acompanado(self):
        with pytest.raises(VisitAgentsError, match="acompañante"):
            resolve({"visit_mode": "acompanado", "companion_agent_id": ""}, current=agent(1))

    def test_acompanante_de_otra_empresa(self):
        """El acompañante puede ser de cualquier empresa; el principal no."""
        form = {"visit_mode": "acompanado", "companion_agent_id": "99"}
        assert resolve(form, current=agent(1)) == (1, 99)
        form_admin = {"agent_id": "2", "visit_mode": "acompanado", "companion_agent_id": "99"}
        assert resolve(form_admin, admin=True) == (2, 99)

    def test_acompanante_inexistente(self):
        form = {"visit_mode": "acompanado", "companion_agent_id": "12345"}
        with pytest.raises(VisitAgentsError, match="acompañante no existe"):
            resolve(form, current=agent(1))

    def test_usuario_sin_ficha_de_agente(self):
        with pytest.raises(VisitAgentsError, match="ficha de agente"):
            resolve({"visit_mode": "solo"}, current=None)

    def test_agente_de_otra_empresa_no_registra(self):
        """Un agente que solo está en la otra empresa no puede ser principal."""
        with pytest.raises(VisitAgentsError, match="empresa activa"):
            resolve({"visit_mode": "solo"}, current=agent(99))

    def test_admin_elige_principal(self):
        form = {"agent_id": "3", "visit_mode": "acompanado", "companion_agent_id": "2"}
        assert resolve(form, admin=True, current=None) == (3, 2)

    def test_admin_principal_obligatorio(self):
        with pytest.raises(VisitAgentsError, match="Selecciona"):
            resolve({"agent_id": ""}, admin=True)

    def test_admin_principal_de_otra_empresa(self):
        with pytest.raises(VisitAgentsError, match="empresa activa"):
            resolve({"agent_id": "99"}, admin=True)

    def test_edicion_por_agente_conserva_el_principal(self):
        """El captador que edita la visita de otro no se la queda."""
        form = {"agent_id": "1", "visit_mode": "acompanado", "companion_agent_id": "3"}
        assert resolve(form, current=agent(1), fixed=2) == (2, 3)


class TestParseVisitAgentsLocked:

    @pytest.mark.parametrize("status", ["signed", "completed"])
    def test_firmada_no_lee_el_form(self, status):
        visit = SimpleNamespace(visit_status=status, agent_id=1, companion_agent_id=2)
        form = {"agent_id": "3", "visit_mode": "solo"}
        assert visit_agents_locked(visit)
        # request y db no se usan cuando está bloqueada
        assert parse_visit_agents(form, None, None, None, visit=visit, locked=True) == (1, 2)

    @pytest.mark.parametrize("status", ["draft", "preview"])
    def test_borrador_editable(self, status):
        assert not visit_agents_locked(SimpleNamespace(visit_status=status))


# ---------------------------------------------------------------------------
# Agente que firma la ficha
# ---------------------------------------------------------------------------

class TestSigningAgent:

    def test_agente_de_la_visita(self):
        captador = Agent(id=1, name="Captador")
        visitante = Agent(id=2, name="Visitante")
        visit = PropertyVisit(property=Property(title="P", agent=captador), agent=visitante)
        assert visit.signing_agent is visitante

    def test_cae_al_captador_si_no_hay_agente(self):
        captador = Agent(id=1, name="Captador")
        visit = PropertyVisit(property=Property(title="P", agent=captador))
        assert visit.signing_agent is captador

    def test_sin_agente_ni_propiedad(self):
        assert PropertyVisit().signing_agent is None

    def test_participating_agent_ids(self):
        assert PropertyVisit(agent_id=1, companion_agent_id=2).participating_agent_ids == {1, 2}
        assert PropertyVisit(agent_id=1).participating_agent_ids == {1}
        assert PropertyVisit().participating_agent_ids == set()


# ---------------------------------------------------------------------------
# hojas_visita (base de datos, transacción deshecha al final)
# ---------------------------------------------------------------------------

@pytest.fixture
def db_session():
    from app.db.session import SessionLocal
    session = SessionLocal()
    try:
        session.connection()
    except Exception as e:  # pragma: no cover - depende del entorno
        session.close()
        pytest.skip(f"Sin base de datos: {e}")
    # Solo se hace flush, nunca commit: el rollback deja la base como estaba
    yield session
    session.rollback()
    session.close()


def test_hojas_visita_cuenta_a_ambos_agentes_y_no_al_captador(db_session):
    from app.models.company import Company
    from app.services.performance_report_service import PerformanceReportService

    db = db_session
    moyza = db.query(Company).filter_by(code="MOYZA").one()

    captador = Agent(name="PYTEST-VA CAPTADOR", email="pytest.va.captador@example.com")
    principal = Agent(name="PYTEST-VA PRINCIPAL", email="pytest.va.principal@example.com")
    acompanante = Agent(name="PYTEST-VA ACOMP", email="pytest.va.acomp@example.com")
    db.add_all([captador, principal, acompanante])
    db.flush()

    prop = Property(title="PYTEST-VA PROP", company_id=moyza.id, agent_id=captador.id)
    db.add(prop)
    db.flush()

    db.add_all([
        PropertyVisit(property_id=prop.id, visitor_name="V1", agent_id=principal.id,
                      companion_agent_id=acompanante.id),
        PropertyVisit(property_id=prop.id, visitor_name="V2", agent_id=principal.id),
    ])
    db.flush()

    svc = PerformanceReportService(db, moyza.id)
    start = datetime.utcnow() - timedelta(days=1)
    end = datetime.utcnow() + timedelta(days=1)

    def hojas(agent_id):
        return svc.calculate_metrics(agent_id, start, end)["hojas_visita"]

    assert hojas(principal.id) == 2
    assert hojas(acompanante.id) == 1
    assert hojas(captador.id) == 0


# ---------------------------------------------------------------------------
# Integración: visita a una propiedad ajena
# ---------------------------------------------------------------------------

BASE_URL = os.getenv("MOYZA_TEST_BASE_URL", "http://localhost:8000")
TAG = "PYTEST-VISITA-AJENA"


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
def foreign_visit_data():
    """Dos agentes con usuario en MOES y una propiedad captada por el primero."""
    if not _server_up():
        pytest.skip(f"La app no responde en {BASE_URL}; tests de integración omitidos")

    from app.db.session import SessionLocal
    from app.models.company import Company
    from app.models.role import Role
    from app.models.user import User

    db = SessionLocal()
    moes = db.query(Company).filter_by(code="MOES").one()
    role = db.query(Role).filter(Role.name.ilike("agent")).first()

    people = {}
    for key in ("captador", "visitante", "acompanante"):
        email = f"pytest.ajena.{key}@example.com"
        ag = Agent(name=f"{TAG} {key.upper()}", email=email)
        ag.companies.append(moes)
        user = User(email=email, full_name=f"{TAG} {key}", hashed_password="pytest-sin-login",
                    role_id=role.id if role else None, is_active=True)
        user.companies.append(moes)
        db.add_all([ag, user])
        people[key] = ag
    db.flush()

    prop = Property(title=f"{TAG} PROP", address="Calle Test 2", city="Jaen",
                    company_id=moes.id, agent_id=people["captador"].id)
    db.add(prop)
    db.commit()

    data = {key: ag.id for key, ag in people.items()}
    data["property_id"] = prop.id
    yield data

    db.query(PropertyVisit).filter(PropertyVisit.property_id == prop.id).delete(synchronize_session=False)
    db.query(Property).filter(Property.id == prop.id).delete(synchronize_session=False)
    db.query(User).filter(User.email.like("pytest.ajena.%@example.com")).delete(synchronize_session=False)
    db.query(Agent).filter(Agent.email.like("pytest.ajena.%@example.com")).delete(synchronize_session=False)
    db.commit()
    db.close()


def test_visita_en_propiedad_ajena_la_ven_visitante_y_captador(foreign_visit_data):
    from app.db.session import SessionLocal

    visitante = _Client("pytest.ajena.visitante@example.com", "MOES")
    captador = _Client("pytest.ajena.captador@example.com", "MOES")
    prop_id = foreign_visit_data["property_id"]

    # El visitante ve la propiedad ajena en el selector y puede abrir el alta
    status, body, _ = visitante.get("/visits/select-property")
    assert status == 200 and f"{TAG} PROP" in body
    status, body, _ = visitante.get(f"/visits/new/{prop_id}")
    assert status == 200 and "Propiedad captada por" in body

    # Intenta registrarla a nombre del captador: se ignora y queda a su nombre
    status, _, headers = visitante.post(f"/visits/create/{prop_id}", {
        "visitor_name": f"{TAG} CLIENTE",
        "phone_country_code": "34",
        "phone_number": "600000000",
        "purchase_fees": "2500",
        "notes": "test",
        "generate_sheet": "true",
        "agent_id": str(foreign_visit_data["captador"]),
        "visit_mode": "acompanado",
        "companion_agent_id": str(foreign_visit_data["acompanante"]),
    })
    assert status == 302 and "/visits/preview/" in headers.get("location", "")

    db = SessionLocal()
    visit = db.query(PropertyVisit).filter(PropertyVisit.property_id == prop_id).one()
    assert visit.agent_id == foreign_visit_data["visitante"]
    assert visit.companion_agent_id == foreign_visit_data["acompanante"]
    db.close()

    # Aparece en el listado del visitante, del acompañante y del captador
    acompanante = _Client("pytest.ajena.acompanante@example.com", "MOES")
    for client in (visitante, acompanante, captador):
        status, body, _ = client.get("/visits")
        assert status == 200 and f"{TAG} CLIENTE" in body

    assert "Propiedad propia · visita de otro agente" in captador.get("/visits")[1]

    # El captador que no estuvo no suma en hojas_visita; los otros dos sí
    from app.models.company import Company
    from app.services.performance_report_service import PerformanceReportService
    db = SessionLocal()
    moes = db.query(Company).filter_by(code="MOES").one()
    svc = PerformanceReportService(db, moes.id)
    start = datetime.utcnow() - timedelta(days=1)
    end = datetime.utcnow() + timedelta(days=1)
    hojas = {
        key: svc.calculate_metrics(foreign_visit_data[key], start, end)["hojas_visita"]
        for key in ("visitante", "acompanante", "captador")
    }
    db.close()
    assert hojas == {"visitante": 1, "acompanante": 1, "captador": 0}


def test_acompanante_de_otra_empresa_en_el_alta(foreign_visit_data):
    """Una visita de MOES admite como acompañante a un agente solo de MOYZA.

    El select del acompañante agrupa a los agentes por empresa; el principal
    sigue limitado a la empresa activa.
    """
    from app.db.session import SessionLocal
    from app.models.company import Company

    db = SessionLocal()
    moyza = db.query(Company).filter_by(code="MOYZA").one()
    companion = Agent(name=f"{TAG} MOYZA", email="pytest.ajena.moyza@example.com")
    companion.companies.append(moyza)
    db.add(companion)
    db.commit()
    companion_id = companion.id

    try:
        visitante = _Client("pytest.ajena.visitante@example.com", "MOES")
        prop_id = foreign_visit_data["property_id"]

        status, body, _ = visitante.get(f"/visits/new/{prop_id}")
        assert status == 200
        assert '<optgroup label="MOES PREMIUM">' in body
        assert '<optgroup label="MOYZA">' in body
        assert f'<option value="{companion_id}"' in body

        status, _, headers = visitante.post(f"/visits/create/{prop_id}", {
            "visitor_name": f"{TAG} CLIENTE MOYZA",
            "phone_country_code": "34",
            "phone_number": "600000001",
            "purchase_fees": "2500",
            "notes": "test",
            "generate_sheet": "true",
            "visit_mode": "acompanado",
            "companion_agent_id": str(companion_id),
        })
        assert status == 302 and "/visits/preview/" in headers.get("location", "")

        db.expire_all()
        visit = (
            db.query(PropertyVisit)
            .filter(PropertyVisit.property_id == prop_id,
                    PropertyVisit.visitor_name == f"{TAG} CLIENTE MOYZA")
            .one()
        )
        assert visit.agent_id == foreign_visit_data["visitante"]
        assert visit.companion_agent_id == companion_id

        # El nombre del acompañante se muestra igual en el listado de visitas
        status, body, _ = visitante.get("/visits")
        assert status == 200 and f"con {TAG} MOYZA" in body
    finally:
        db.query(PropertyVisit).filter(
            PropertyVisit.companion_agent_id == companion_id
        ).delete(synchronize_session=False)
        db.query(Agent).filter(Agent.id == companion_id).delete(synchronize_session=False)
        db.commit()
        db.close()
