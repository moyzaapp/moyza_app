"""
Excel de compradores para administración (PLAN_EXPORT_EXCEL_COMPRADORES.md §2.5).

Integración contra la app levantada (patrón de test_metric_detail.py; se omiten
si la app no responde):

- El admin descarga un `.xlsx` con las tres hojas y sus cabeceras, con el
  nombre de fichero esperado.
- Filtro por fecha de alta, `hasta` inclusivo (alerta a las 23:30 de Madrid).
- Solo la empresa activa: lo de MOES no sale en el export de MOYZA.
- Un agente recibe la redirección de `require_admin_role`.
- `desde > hasta` se intercambia; una fecha inválida redirige a /alerts.
- Etapa actual con la regla del listado; «Sin iniciar» sin seguimientos.
- Los totales del Resumen cuadran con las otras hojas.

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
MOES_AGENT_EMAIL = "pytest.export.moes@example.com"
RANGE = "desde=2021-03-10&hasta=2021-03-12"
FILENAME = "compradores_moyza_2021-03-10_2021-03-12.xlsx"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

BUYER_HEADERS = [
    "Fecha de alta", "Nombre", "Teléfono", "Email", "Creado por", "Alertas", "Última alerta",
    "Tipo de negocio", "Tipo de inmueble", "Provincia", "Zonas/ciudades", "Presupuesto mín.",
    "Presupuesto máx.", "Notas",
]
ALERT_HEADERS = [
    "Fecha", "Comprador", "Teléfono", "Email", "Origen", "Referencia", "Propiedad", "Fuente",
    "Agente", "Etapa actual", "Estado", "Última gestión", "Nº gestiones", "Fecha de cierre", "Cedida",
]

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
    db.query(User).filter(User.email == AGENT_EMAIL).delete(synchronize_session=False)
    for email in (AGENT_EMAIL, MOES_AGENT_EMAIL):
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

    agent = Agent(name=f"{TAG} AGENTE", email=AGENT_EMAIL)
    agent.companies.append(moyza)
    moes_agent = Agent(name=f"{TAG} MOES", email=MOES_AGENT_EMAIL)
    moes_agent.companies.append(moes)
    user = User(email=AGENT_EMAIL, full_name=f"{TAG} usuario", hashed_password="pytest-sin-login",
                role_id=role.id if role else None, is_active=True)
    user.companies.append(moyza)
    prop = Property(title=f"{TAG} Piso en el Centro", referencia="PYT-EXP-1", city="Jaén",
                    address="Calle Secreta 12, 3ºB, 23001 Jaén", company_id=moyza.id,
                    business_type="Venta")
    db.add_all([agent, moes_agent, user, prop])
    db.flush()

    def buyer(name, company, created, notes="Prefiere planta alta"):
        item = Buyer(name=f"{TAG} {name}", phone="600111222", email="comprador@example.com",
                     notes=notes, company_id=company.id, created_at=created,
                     created_by=admin.id)
        db.add(item)
        db.flush()
        return item

    def alert(name, company, agent_id, created, buyer_item=None, follow_ups=(), **extra):
        item = PropertyAlert(company_id=company.id, agent_id=agent_id, lead_name=f"{TAG} {name}",
                             status="PENDING", created_by=admin.id, created_at=created,
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
    # 00:30 de Madrid del día 10 = 23:30 UTC del día 9: dentro solo si el límite
    # inferior se calcula en hora de Madrid. Notas con «=» y un salto manual
    # de Word (\x0b): texto literal, sin fórmula y sin romper el export.
    buyer("PRIMERA HORA", moyza, _madrid(2021, 3, 10, 0, 30), notes="=1+\x0b llamar")
    buyer("MOES", moes, _madrid(2021, 3, 11, 10))

    # Alerta antigua del comprador: cuenta en «Alertas» pero no sale en la hoja
    alert("ANTIGUA", moyza, agent.id, _madrid(2020, 5, 1, 9), inside, origin="search")
    alert("CONTACTADO", moyza, agent.id, _madrid(2021, 3, 11, 10, 5), inside,
          follow_ups=[("CONTACTADO", _madrid(2021, 3, 11, 11)),
                      ("SIN_RESPUESTA", _madrid(2021, 3, 11, 12))],
          origin="property", property_id=prop.id, source="Idealista")
    alert("ULTIMA HORA", moyza, agent.id, _madrid(2021, 3, 12, 23, 30), inside, origin="search")
    alert("DIA SIGUIENTE", moyza, agent.id, _madrid(2021, 3, 13, 0, 30), origin="search")
    alert("ALERTA MOES", moes, moes_agent.id, _madrid(2021, 3, 11, 10), origin="search")
    db.commit()

    yield {"admin_name": admin.full_name}

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


def _summary(ws) -> dict:
    """{concepto: valor} del Resumen (sin los títulos de bloque)."""
    return {row[0]: row[1] for row in ws.iter_rows(min_row=2, values_only=True) if row[0]}


def _block(ws, title) -> dict:
    """{etiqueta: nº} de un bloque del Resumen («Alertas por fuente», …)."""
    out, inside = {}, False
    for concept, value in ws.iter_rows(min_row=2, values_only=True):
        if concept == title:
            inside = True
        elif inside:
            if concept is None:
                break
            out[concept] = value
    return out


def test_admin_descarga_xlsx_con_tres_hojas(export):
    headers = export["headers"]
    assert headers["content-type"] == XLSX
    assert headers["content-disposition"] == f'attachment; filename="{FILENAME}"'
    wb = export["wb"]
    assert wb.sheetnames == ["Resumen", "Compradores", "Alertas"]
    assert [c.value for c in wb["Resumen"][1]] == ["Concepto", "Valor"]
    assert [c.value for c in wb["Compradores"][1]] == BUYER_HEADERS
    assert [c.value for c in wb["Alertas"][1]] == ALERT_HEADERS
    assert wb["Compradores"].freeze_panes == "A2"
    assert wb["Alertas"].auto_filter.ref


def test_filtro_por_fecha_hasta_inclusivo(export, data):
    buyers = _by(_rows(export["wb"]["Compradores"]), "Nombre")
    assert f"{TAG} DENTRO" in buyers
    assert f"{TAG} PRIMERA HORA" in buyers
    assert f"{TAG} FUERA" not in buyers
    alerts = {row["Comprador"] for row in _rows(export["wb"]["Alertas"])}
    # Las alertas con comprador muestran su nombre; la del día siguiente no sale
    assert f"{TAG} DIA SIGUIENTE" not in alerts
    rows = [r for r in _rows(export["wb"]["Alertas"]) if r["Comprador"] == f"{TAG} DENTRO"]
    dates = sorted(r["Fecha"] for r in rows)
    # La de las 10:05 y la de las 23:30 del último día (hora de Madrid); la antigua no
    assert dates == [datetime(2021, 3, 11, 10, 5), datetime(2021, 3, 12, 23, 30)]


def test_fila_del_comprador(export, data):
    row = _by(_rows(export["wb"]["Compradores"]), "Nombre")[f"{TAG} DENTRO"]
    assert row["Fecha de alta"] == datetime(2021, 3, 11, 10)
    assert row["Creado por"] == data["admin_name"]
    # Todas sus alertas de la empresa, no solo las del periodo
    assert row["Alertas"] == 3
    assert row["Última alerta"] == datetime(2021, 3, 12, 23, 30)
    assert row["Tipo de negocio"] == "Venta"
    assert row["Tipo de inmueble"] == "Piso, Casa"
    assert row["Provincia"] == "Jaén"
    assert row["Zonas/ciudades"] == "Jaén, Centro"
    assert row["Presupuesto mín."] == 100000 and row["Presupuesto máx."] == 200000
    assert row["Notas"] == "Prefiere planta alta"
    ws = export["wb"]["Compradores"]
    data_row = next(r for r in ws.iter_rows(min_row=2) if r[1].value == f"{TAG} DENTRO")
    assert data_row[0].number_format == "dd/mm/yyyy hh:mm"
    assert data_row[11].number_format == "#,##0"


def test_solo_empresa_activa(export):
    buyers = {row["Nombre"] for row in _rows(export["wb"]["Compradores"])}
    alerts = {row["Comprador"] for row in _rows(export["wb"]["Alertas"])}
    agents = {row["Agente"] for row in _rows(export["wb"]["Alertas"])}
    assert f"{TAG} MOES" not in buyers
    assert f"{TAG} ALERTA MOES" not in alerts
    assert f"{TAG} MOES" not in agents


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
    cell = next(r for r in ws.iter_rows(min_row=2) if r[1].value == f"{TAG} PRIMERA HORA")[13]
    assert cell.value == "=1+ llamar"
    assert cell.data_type == "s"


def test_sin_fechas_mes_en_curso(data):
    from app.core.business_calendar import madrid_today
    today = madrid_today()
    status, body, headers = Client(ADMIN_EMAIL, "MOYZA").get("/alerts/export.xlsx")
    assert status == 200
    expected = f"compradores_moyza_{today.replace(day=1).isoformat()}_{today.isoformat()}.xlsx"
    assert headers["content-disposition"] == f'attachment; filename="{expected}"'
    assert load_workbook(BytesIO(body)).sheetnames == ["Resumen", "Compradores", "Alertas"]


def test_etapa_actual_y_columnas_de_la_alerta(export):
    rows = [r for r in _rows(export["wb"]["Alertas"]) if r["Comprador"] == f"{TAG} DENTRO"]
    contacted = next(r for r in rows if r["Fecha"] == datetime(2021, 3, 11, 10, 5))
    untouched = next(r for r in rows if r["Fecha"] == datetime(2021, 3, 12, 23, 30))
    # CONTACTADO y luego SIN_RESPUESTA: la etapa no retrocede
    assert contacted["Etapa actual"] == "Contactado"
    assert contacted["Nº gestiones"] == 2
    assert contacted["Última gestión"] == datetime(2021, 3, 11, 12)
    assert contacted["Origen"] == "Con referencia"
    assert contacted["Referencia"] == "PYT-EXP-1"
    assert contacted["Propiedad"] == f"{TAG} Piso en el Centro · Calle Secreta 12"
    assert contacted["Fuente"] == "Idealista"
    assert contacted["Agente"] == f"{TAG} AGENTE"
    assert contacted["Estado"] == "Pendiente"
    assert contacted["Cedida"] == "No"
    assert untouched["Etapa actual"] == "Sin iniciar"
    assert untouched["Nº gestiones"] == 0
    assert untouched["Origen"] == "Búsqueda general"
    assert untouched["Fuente"] in ("", None)
    assert untouched["Referencia"] in ("", None) and untouched["Propiedad"] in ("", None)


def test_resumen_cuadra_con_las_hojas(export):
    wb = export["wb"]
    summary = _summary(wb["Resumen"])
    buyers = _rows(wb["Compradores"])
    alerts = _rows(wb["Alertas"])
    assert summary["Empresa"]
    assert summary["Periodo"] == "10/03/2021 – 12/03/2021"
    assert summary["Compradores nuevos"] == len(buyers)
    assert summary["Alertas nuevas"] == len(alerts)
    assert summary["Alertas con referencia"] + summary["Alertas de búsqueda general"] == len(alerts)
    assert summary["Alertas con referencia"] == sum(1 for r in alerts if r["Origen"] == "Con referencia")
    for title, column in (("Alertas por fuente", "Fuente"),
                          ("Alertas por agente", "Agente"),
                          ("Alertas por etapa actual", "Etapa actual")):
        block = _block(wb["Resumen"], title)
        assert sum(block.values()) == len(alerts), title
        if column == "Fuente":
            expected = {}
            for r in alerts:
                key = r["Fuente"] or "Sin fuente"
                expected[key] = expected.get(key, 0) + 1
        else:
            expected = {}
            for r in alerts:
                expected[r[column]] = expected.get(r[column], 0) + 1
        assert block == expected, title
        # Ordenado por cantidad descendente
        counts = list(block.values())
        assert counts == sorted(counts, reverse=True), title
