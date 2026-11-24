"""
Excel de compradores para administración (PLAN_EXPORT_EXCEL_COMPRADORES.md
§2.5 y §6).

Integración contra la app levantada (patrón de test_metric_detail.py; se omiten
si la app no responde):

- El admin descarga un `.xlsx` con una sola hoja, «Compradores», y sus
  cabeceras («Agentes» tras «Email»; sin «Creado por», «Alertas» ni
  «Última alerta»), con el nombre de
  fichero esperado.
- Filtro por fecha de alta, `hasta` inclusivo (comprador a las 23:30 de
  Madrid); el límite inferior en hora de Madrid.
- Solo la empresa activa: lo de MOES no sale en el export de MOYZA.
- Un agente recibe la redirección de `require_admin_role`.
- `desde > hasta` se intercambia; una fecha inválida redirige a /alerts.
- Columna «Agentes» y filtro `agente` (D8): por alerta (cualquier estado),
  por `created_by` (usuario con el email del agente) y por el perfil; dos
  `agente` suman; inválidos, de otra empresa o dados de baja se ignoran.

Los datos van en marzo de 2021 (lejos de los datos demo) con el prefijo del
TAG y se borran al terminar.

    docker exec moyza_backend python -m pytest tests/test_buyer_export.py -q
"""
import os
import urllib.error
import urllib.request
from datetime import datetime
from io import BytesIO

import pytest
from openpyxl import load_workbook

from tests.test_commercial_results import _server_up
from tests.test_alerts_unmanaged_filter import _flashes

BASE_URL = os.getenv("MOYZA_TEST_BASE_URL", "http://localhost:8000")
ADMIN_EMAIL = os.getenv("MOYZA_TEST_ADMIN_EMAIL", "admin@moyza.com")
TAG = "PYTEST-EXPORT"
AGENT_EMAIL = "pytest.export.agente@example.com"
AGENT2_EMAIL = "pytest.export.agente2@example.com"
INACTIVE_EMAIL = "pytest.export.baja@example.com"
MOES_AGENT_EMAIL = "pytest.export.moes@example.com"
RANGE = "desde=2021-03-10&hasta=2021-03-12"
FILENAME = "compradores_moyza_2021-03-10_2021-03-12.xlsx"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

BUYER_HEADERS = [
    "Fecha de alta", "Nombre", "Teléfono", "Email", "Agentes", "Tipo de negocio",
    "Tipo de inmueble", "Provincia", "Zonas/ciudades", "Presupuesto mín.", "Presupuesto máx.",
    "Notas",
]
AGENT_NAME = f"{TAG} AGENTE"
AGENT2_NAME = f"{TAG} AGENTE DOS"
INACTIVE_NAME = f"{TAG} AGENTE BAJA"

pytestmark = pytest.mark.skipif(
    not _server_up(),
    reason=f"La app no responde en {BASE_URL}; tests de integración omitidos",
)


class Client:
    """GET con cookies de sesión y empresa, sin seguir redirecciones; cuerpo en bytes."""

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    def __init__(self, email: str, company: str):
        from app.core.security import create_access_token
        self.cookie = f"access_token={create_access_token({'sub': email})}; active_company={company}"
        self.opener = urllib.request.build_opener(self._NoRedirect)

    def get(self, path):
        req = urllib.request.Request(BASE_URL + path)
        req.add_header("Cookie", self.cookie)
        try:
            resp = self.opener.open(req, timeout=30)
            return resp.status, resp.read(), {k.lower(): v for k, v in resp.headers.items()}
        except urllib.error.HTTPError as e:
            return e.code, e.read(), {k.lower(): v for k, v in e.headers.items()}


def _madrid(year, month, day, hour, minute=0):
    """Hora de Madrid -> UTC naive, como se guarda en base de datos."""
    from app.core.business_calendar import to_utc
    return to_utc(datetime(year, month, day, hour, minute))


def _cleanup(db):
    from sqlalchemy import select
    from app.models.agent import Agent
    from app.models.alert_follow_up import AlertFollowUp
    from app.models.buyer import Buyer
    from app.models.buyer_search_criteria import BuyerSearchCriteria
    from app.models.property import Property
    from app.models.property_alert import PropertyAlert
    from app.models.user import User

    db.rollback()
    alerts = select(PropertyAlert.id).where(PropertyAlert.lead_name.like(f"{TAG}%"))
    db.query(AlertFollowUp).filter(AlertFollowUp.alert_id.in_(alerts)).delete(synchronize_session=False)
    db.query(PropertyAlert).filter(PropertyAlert.lead_name.like(f"{TAG}%")).delete(synchronize_session=False)
    buyers = select(Buyer.id).where(Buyer.name.like(f"{TAG}%"))
    db.query(BuyerSearchCriteria).filter(BuyerSearchCriteria.buyer_id.in_(buyers)).delete(
        synchronize_session=False)
    db.query(Buyer).filter(Buyer.name.like(f"{TAG}%")).delete(synchronize_session=False)
    db.query(Property).filter(Property.title.like(f"{TAG}%")).delete(synchronize_session=False)
    db.query(User).filter(User.email.in_([AGENT_EMAIL, AGENT2_EMAIL])).delete(synchronize_session=False)
    for email in (AGENT_EMAIL, AGENT2_EMAIL, INACTIVE_EMAIL, MOES_AGENT_EMAIL):
        found = db.query(Agent).filter(Agent.email == email).first()
        if found:
            found.companies.clear()
            db.delete(found)
    db.commit()


@pytest.fixture(scope="module")
def data():
    """Compradores y alertas de MOYZA dentro y fuera del 10-12/03/2021, y de MOES dentro."""
    from app.db.session import SessionLocal
    from app.models.agent import Agent
    from app.models.alert_follow_up import AlertFollowUp
    from app.models.buyer import Buyer
    from app.models.buyer_search_criteria import BuyerSearchCriteria
    from app.models.company import Company
    from app.models.property import Property
    from app.models.property_alert import PropertyAlert
    from app.models.role import Role
    from app.models.user import User

    db = SessionLocal()
    _cleanup(db)
    moyza = db.query(Company).filter_by(code="MOYZA").one()
    moes = db.query(Company).filter_by(code="MOES").one()
    role = db.query(Role).filter(Role.name.ilike("agent")).first()
    admin = db.query(User).filter(User.email == ADMIN_EMAIL).one()

    agent = Agent(name=AGENT_NAME, email=AGENT_EMAIL)
    agent.companies.append(moyza)
    agent2 = Agent(name=AGENT2_NAME, email=AGENT2_EMAIL)
    agent2.companies.append(moyza)
    inactive = Agent(name=INACTIVE_NAME, email=INACTIVE_EMAIL, is_active=False)
    inactive.companies.append(moyza)
    moes_agent = Agent(name=f"{TAG} MOES", email=MOES_AGENT_EMAIL)
    moes_agent.companies.append(moes)
    user = User(email=AGENT_EMAIL, full_name=f"{TAG} usuario", hashed_password="pytest-sin-login",
                role_id=role.id if role else None, is_active=True)
    user.companies.append(moyza)
    user2 = User(email=AGENT2_EMAIL, full_name=f"{TAG} usuario dos", hashed_password="pytest-sin-login",
                 role_id=role.id if role else None, is_active=True)
    user2.companies.append(moyza)
    prop = Property(title=f"{TAG} Piso en el Centro", referencia="PYT-EXP-1", city="Jaén",
                    address="Calle Secreta 12, 3ºB, 23001 Jaén", company_id=moyza.id,
                    business_type="Venta")
    db.add_all([agent, agent2, inactive, moes_agent, user, user2, prop])
    db.flush()

    def buyer(name, company, created, notes="Prefiere planta alta", created_by=None):
        item = Buyer(name=f"{TAG} {name}", phone="600111222", email="comprador@example.com",
                     notes=notes, company_id=company.id, created_at=created,
                     created_by=created_by or admin.id)
        db.add(item)
        db.flush()
        return item

    def alert(name, company, agent_id, created, buyer_item=None, follow_ups=(), status="PENDING", **extra):
        item = PropertyAlert(company_id=company.id, agent_id=agent_id, lead_name=f"{TAG} {name}",
                             status=status, created_by=admin.id, created_at=created,
                             assigned_at=created, buyer_id=buyer_item.id if buyer_item else None,
                             business_type="Venta", **extra)
        db.add(item)
        db.flush()
        for action, when in follow_ups:
            db.add(AlertFollowUp(alert_id=item.id, action_type=action, created_at=when,
                                 created_by=admin.id))
        return item

    inside = buyer("DENTRO", moyza, _madrid(2021, 3, 11, 10))
    db.add(BuyerSearchCriteria(buyer_id=inside.id, business_type="Venta", property_types=["Piso", "Casa"],
                               province="Jaén", cities=["Jaén"], zones=["Centro"],
                               min_price=100000, max_price=200000))
    buyer("FUERA", moyza, _madrid(2021, 3, 9, 23, 30))
    # `hasta` inclusivo: 23:30 de Madrid del último día dentro, 00:30 del siguiente fuera
    buyer("ULTIMA HORA", moyza, _madrid(2021, 3, 12, 23, 30))
    buyer("DIA SIGUIENTE", moyza, _madrid(2021, 3, 13, 0, 30))
    # 00:30 de Madrid del día 10 = 23:30 UTC del día 9: dentro solo si el límite
    # inferior se calcula en hora de Madrid. Notas con «=» y un salto manual
    # de Word (\x0b): texto literal, sin fórmula y sin romper el export.
    buyer("PRIMERA HORA", moyza, _madrid(2021, 3, 10, 0, 30), notes="=1+\x0b llamar")
    buyer("MOES", moes, _madrid(2021, 3, 11, 10))
    # Compradores de agentes (D8) por cada vía: «DENTRO» por sus alertas
    # (pendientes: cuenta cualquier estado), «CREADO» por `created_by` (usuario
    # con el email del agente) y «PERFIL» por el agente de su perfil, que además
    # tiene una alerta del agente dos. «DE DOS» lo creó el usuario del agente
    # dos y «DE BAJA» tiene en su perfil a un agente dado de baja.
    buyer("CREADO", moyza, _madrid(2021, 3, 11, 11), created_by=user.id)
    profile = buyer("PERFIL", moyza, _madrid(2021, 3, 11, 12))
    db.add(BuyerSearchCriteria(buyer_id=profile.id, agent_id=agent.id, business_type="Venta"))
    buyer("DE DOS", moyza, _madrid(2021, 3, 11, 13), created_by=user2.id)
    retired = buyer("DE BAJA", moyza, _madrid(2021, 3, 11, 14))
    db.add(BuyerSearchCriteria(buyer_id=retired.id, agent_id=inactive.id))

    # Alerta antigua del comprador: D8 cuenta alertas de cualquier fecha para el filtro por agente
    alert("ANTIGUA", moyza, agent.id, _madrid(2020, 5, 1, 9), inside, origin="search")
    alert("CONTACTADO", moyza, agent.id, _madrid(2021, 3, 11, 10, 5), inside,
          follow_ups=[("CONTACTADO", _madrid(2021, 3, 11, 11)),
                      ("SIN_RESPUESTA", _madrid(2021, 3, 11, 12))],
          origin="property", property_id=prop.id, source="Idealista")
    alert("ULTIMA HORA", moyza, agent.id, _madrid(2021, 3, 12, 23, 30), inside, origin="search")
    alert("DIA SIGUIENTE", moyza, agent.id, _madrid(2021, 3, 13, 0, 30), origin="search")
    alert("ALERTA MOES", moes, moes_agent.id, _madrid(2021, 3, 11, 10), origin="search")
    alert("PERFIL DOS", moyza, agent2.id, _madrid(2021, 3, 11, 12, 5), profile, origin="search",
          status="IN_PROGRESS")
    db.commit()

    yield {"agent": agent.id, "agent2": agent2.id,
           "inactive": inactive.id, "moes_agent": moes_agent.id}

    _cleanup(db)
    db.close()


@pytest.fixture(scope="module")
def export(data):
    """Libro del 10 al 12/03/2021 de MOYZA descargado por el admin."""
    status, body, headers = Client(ADMIN_EMAIL, "MOYZA").get(f"/alerts/export.xlsx?{RANGE}")
    assert status == 200
    return {"headers": headers, "wb": load_workbook(BytesIO(body))}


def _rows(ws) -> list:
    """Filas de datos de una hoja como dicts {cabecera: valor}."""
    values = list(ws.iter_rows(values_only=True))
    header = values[0]
    return [dict(zip(header, row)) for row in values[1:]]


def _by(rows, column) -> dict:
    return {row[column]: row for row in rows}


def _download(query) -> tuple:
    """(status, libro o None) del export de MOYZA del 10 al 12/03/2021 con `query` extra."""
    status, body, _ = Client(ADMIN_EMAIL, "MOYZA").get(f"/alerts/export.xlsx?{RANGE}{query}")
    return status, (load_workbook(BytesIO(body)) if status == 200 else None)


def _names(wb) -> set:
    """Nombres de los compradores del TAG en la hoja (fuera los de otros datos)."""
    return {row["Nombre"] for row in _rows(wb["Compradores"]) if row["Nombre"].startswith(TAG)}


ALL_NAMES = {f"{TAG} {name}" for name in
             ("DENTRO", "PRIMERA HORA", "ULTIMA HORA", "CREADO", "PERFIL", "DE DOS", "DE BAJA")}


def test_admin_descarga_xlsx_con_una_hoja(export):
    headers = export["headers"]
    assert headers["content-type"] == XLSX
    assert headers["content-disposition"] == f'attachment; filename="{FILENAME}"'
    wb = export["wb"]
    assert wb.sheetnames == ["Compradores"]
    ws = wb["Compradores"]
    assert [c.value for c in ws[1]] == BUYER_HEADERS
    assert ws.freeze_panes == "A2"
    assert ws.auto_filter.ref


def test_filtro_por_fecha_hasta_inclusivo(export):
    buyers = _by(_rows(export["wb"]["Compradores"]), "Nombre")
    assert f"{TAG} DENTRO" in buyers
    # 00:30 de Madrid del primer día: el límite inferior va en hora de Madrid
    assert f"{TAG} PRIMERA HORA" in buyers
    assert f"{TAG} FUERA" not in buyers
    assert buyers[f"{TAG} ULTIMA HORA"]["Fecha de alta"] == datetime(2021, 3, 12, 23, 30)
    assert f"{TAG} DIA SIGUIENTE" not in buyers


def test_fila_del_comprador(export):
    row = _by(_rows(export["wb"]["Compradores"]), "Nombre")[f"{TAG} DENTRO"]
    assert row["Fecha de alta"] == datetime(2021, 3, 11, 10)
    # D10: sin «Creado por», «Alertas» ni «Última alerta»
    assert not {"Creado por", "Alertas", "Última alerta"} & set(row)
    assert row["Agentes"] == AGENT_NAME
    assert row["Tipo de negocio"] == "Venta"
    assert row["Tipo de inmueble"] == "Piso, Casa"
    assert row["Provincia"] == "Jaén"
    assert row["Zonas/ciudades"] == "Jaén, Centro"
    assert row["Presupuesto mín."] == 100000 and row["Presupuesto máx."] == 200000
    assert row["Notas"] == "Prefiere planta alta"
    ws = export["wb"]["Compradores"]
    data_row = next(r for r in ws.iter_rows(min_row=2) if r[1].value == f"{TAG} DENTRO")
    assert data_row[0].number_format == "dd/mm/yyyy hh:mm"
    assert data_row[9].number_format == "#,##0"
    assert data_row[10].number_format == "#,##0"


def test_columna_agentes(export):
    buyers = _by(_rows(export["wb"]["Compradores"]), "Nombre")
    # Por created_by (usuario con el email del agente)
    assert buyers[f"{TAG} CREADO"]["Agentes"] == AGENT_NAME
    assert buyers[f"{TAG} DE DOS"]["Agentes"] == AGENT2_NAME
    # Perfil del agente y alerta del agente dos: los dos, por nombre
    assert buyers[f"{TAG} PERFIL"]["Agentes"] == f"{AGENT_NAME}, {AGENT2_NAME}"
    # Un agente dado de baja sigue apareciendo (dato histórico)
    assert buyers[f"{TAG} DE BAJA"]["Agentes"] == INACTIVE_NAME
    # Creado por el admin y sin alertas ni perfil: vacío
    assert buyers[f"{TAG} PRIMERA HORA"]["Agentes"] in ("", None)


def test_sin_filtro_salen_todos(export):
    assert _names(export["wb"]) == ALL_NAMES


def test_filtro_por_un_agente(data):
    status, wb = _download(f"&agente={data['agent']}")
    assert status == 200
    assert wb.sheetnames == ["Compradores"]
    # Por alerta (pendientes), por created_by y por el perfil; el resto fuera
    assert _names(wb) == {f"{TAG} DENTRO", f"{TAG} CREADO", f"{TAG} PERFIL"}


def test_filtro_por_dos_agentes_suma(data):
    status, wb = _download(f"&agente={data['agent']}&agente={data['agent2']}")
    assert status == 200
    assert _names(wb) == {f"{TAG} DENTRO", f"{TAG} CREADO", f"{TAG} PERFIL", f"{TAG} DE DOS"}
    status, wb = _download(f"&agente={data['agent2']}")
    assert _names(wb) == {f"{TAG} PERFIL", f"{TAG} DE DOS"}


@pytest.mark.parametrize("value", ["abc", "", "999999999", "99999999999999999999", "%C2%B2", "9" * 5000,
                                   "inactive", "moes_agent"])
def test_agente_invalido_se_ignora(data, value):
    """Id no numérico, inexistente, desbordado, dado de baja o de otra empresa: todos."""
    agent_id = data.get(value, value)
    status, wb = _download(f"&agente={agent_id}")
    assert status == 200
    assert _names(wb) == ALL_NAMES


def test_agente_invalido_junto_a_uno_valido(data):
    status, wb = _download(f"&agente={data['moes_agent']}&agente={data['agent2']}")
    assert status == 200
    assert _names(wb) == {f"{TAG} PERFIL", f"{TAG} DE DOS"}


def test_solo_empresa_activa(export):
    buyers = {row["Nombre"] for row in _rows(export["wb"]["Compradores"])}
    assert f"{TAG} MOES" not in buyers


def test_agente_redirigido(data):
    status, body, headers = Client(AGENT_EMAIL, "MOYZA").get(f"/alerts/export.xlsx?{RANGE}")
    assert status == 303
    assert headers["location"] == "/clients"
    assert not body.startswith(b"PK")


def test_desde_posterior_se_intercambia(data):
    status, body, headers = Client(ADMIN_EMAIL, "MOYZA").get(
        "/alerts/export.xlsx?desde=2021-03-12&hasta=2021-03-10")
    assert status == 200
    assert headers["content-disposition"] == f'attachment; filename="{FILENAME}"'
    names = {row["Nombre"] for row in _rows(load_workbook(BytesIO(body))["Compradores"])}
    assert f"{TAG} DENTRO" in names


def test_fecha_invalida_redirige_con_flash(data):
    status, _, headers = Client(ADMIN_EMAIL, "MOYZA").get("/alerts/export.xlsx?desde=2021-13-45&hasta=2021-03-12")
    assert status == 303
    assert headers["location"] == "/alerts"
    flashes = _flashes(headers)
    assert flashes and flashes[0]["category"] == "error"


def test_fecha_extrema_redirige_sin_error(data):
    status, _, headers = Client(ADMIN_EMAIL, "MOYZA").get("/alerts/export.xlsx?desde=2021-03-10&hasta=9999-12-31")
    assert status == 303
    assert headers["location"] == "/alerts"


def test_textos_literales_sin_formulas_ni_caracteres_de_control(export):
    ws = export["wb"]["Compradores"]
    notes = BUYER_HEADERS.index("Notas")
    cell = next(r for r in ws.iter_rows(min_row=2) if r[1].value == f"{TAG} PRIMERA HORA")[notes]
    assert cell.value == "=1+ llamar"
    assert cell.data_type == "s"


def test_sin_fechas_mes_en_curso(data):
    from app.core.business_calendar import madrid_today
    today = madrid_today()
    status, body, headers = Client(ADMIN_EMAIL, "MOYZA").get("/alerts/export.xlsx")
    assert status == 200
    expected = f"compradores_moyza_{today.replace(day=1).isoformat()}_{today.isoformat()}.xlsx"
    assert headers["content-disposition"] == f'attachment; filename="{expected}"'
    assert load_workbook(BytesIO(body)).sheetnames == ["Compradores"]
