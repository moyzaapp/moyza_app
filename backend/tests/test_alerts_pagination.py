"""
Paginación en servidor de /alerts (PLAN_PAGINACION_ALERTAS.md).

- Funciones puras de `app.web.routes.alerts` (paginate_params, normalize_per_page,
  effective_alert_statuses): sin base de datos.
- Macro `pagination` de components/ui_macros.html: render con el entorno de
  plantillas de la app.
- Ruta `alerts_page`: se llama en proceso contra una SQLite en memoria con los
  modelos reales, así que no necesita la app levantada ni PostgreSQL.

    cd backend && python -m pytest tests/test_alerts_pagination.py -q
"""
import asyncio
import re
from datetime import datetime, timedelta
from urllib.parse import parse_qs

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.datastructures import QueryParams
from starlette.requests import Request

from app.core.constants import AlertStatus
from app.web.routes.alerts import (
    DEFAULT_PAGE_SIZE,
    PAGE_SIZES,
    PER_PAGE_COOKIE,
    alerts_page,
    effective_alert_statuses,
    normalize_per_page,
    paginate_params,
)


# ---------------------------------------------------------------------------
# Función pura de paginación
# ---------------------------------------------------------------------------

def test_tamanos_de_pagina_y_defecto():
    assert PAGE_SIZES == (50, 100, 200, 300)
    assert DEFAULT_PAGE_SIZE == 100


@pytest.mark.parametrize("value, expected", [
    (50, 50), ("100", 100), ("200", 200), (" 300 ", 300),
    (None, 100), ("", 100), ("abc", 100), ("25", 100), (0, 100), (-50, 100), ("1000", 100),
])
def test_per_page_invalido_va_a_100(value, expected):
    assert normalize_per_page(value) == expected


def test_primera_pagina():
    p = paginate_params(1, 100, 1218)
    assert p == {
        "page": 1, "per_page": 100, "total": 1218, "pages": 13, "offset": 0,
        "start": 1, "end": 100, "has_prev": False, "has_next": True,
    }


def test_pagina_intermedia_y_ultima():
    p = paginate_params(2, 50, 633)
    assert (p["offset"], p["start"], p["end"], p["has_prev"], p["has_next"]) == (50, 51, 100, True, True)

    last = paginate_params(13, 50, 633)
    assert last["pages"] == 13
    assert (last["offset"], last["start"], last["end"]) == (600, 601, 633)
    assert last["has_prev"] and not last["has_next"]


def test_total_exacto_no_crea_pagina_vacia():
    p = paginate_params(3, 100, 300)
    assert p["pages"] == 3
    assert (p["start"], p["end"], p["has_next"]) == (201, 300, False)


@pytest.mark.parametrize("page", [999, "999"])
def test_pagina_fuera_de_rango_va_a_la_ultima(page):
    p = paginate_params(page, 100, 250)
    assert p["page"] == 3
    assert (p["offset"], p["start"], p["end"]) == (200, 201, 250)


@pytest.mark.parametrize("page", [None, "", "abc", "2.5", 0, -3, "-1"])
def test_pagina_no_valida_va_a_la_primera(page):
    p = paginate_params(page, 100, 250)
    assert p["page"] == 1
    assert p["offset"] == 0


def test_sin_resultados():
    p = paginate_params(5, 100, 0)
    assert p == {
        "page": 1, "per_page": 100, "total": 0, "pages": 1, "offset": 0,
        "start": 0, "end": 0, "has_prev": False, "has_next": False,
    }


def test_per_page_invalido_en_paginacion():
    assert paginate_params(1, "7", 1000)["per_page"] == 100


# ---------------------------------------------------------------------------
# Estados efectivos
# ---------------------------------------------------------------------------

def test_sin_filtros_solo_abiertas():
    assert effective_alert_statuses([], "") == [AlertStatus.PENDING, AlertStatus.IN_PROGRESS]
    assert effective_alert_statuses([], "   ") == [AlertStatus.PENDING, AlertStatus.IN_PROGRESS]


def test_texto_sin_estados_busca_en_todos():
    assert effective_alert_statuses([], "garcia") is None


def test_estados_marcados_se_respetan():
    assert effective_alert_statuses(["COMPLETED"], "") == ["COMPLETED"]
    assert effective_alert_statuses(["COMPLETED", "CANCELLED"], "garcia") == ["COMPLETED", "CANCELLED"]


def test_estados_invalidos_se_ignoran():
    assert effective_alert_statuses(["NOPE"], "") == [AlertStatus.PENDING, AlertStatus.IN_PROGRESS]
    assert effective_alert_statuses(["NOPE"], "garcia") is None
    assert effective_alert_statuses(["PENDING", "PENDING", "NOPE"], "") == ["PENDING"]


# ---------------------------------------------------------------------------
# Macro de paginación
# ---------------------------------------------------------------------------

def _render_pagination(p, query, **kwargs):
    from app.web.template_env import templates
    macros = templates.env.get_template("components/ui_macros.html").module
    return str(macros.pagination(p, QueryParams(query), **kwargs))


def test_macro_conserva_query_string_y_multivalor():
    html = _render_pagination(
        paginate_params(2, 50, 633),
        "q=garcia&status_filter=PENDING&status_filter=COMPLETED&agent_id=3&per_page=50&page=2&b_q=ana",
        param="page", label="alertas",
    )
    hrefs = re.findall(r'href="([^"]+)"', html)
    assert hrefs, html
    for href in hrefs:
        params = parse_qs(href.replace("&amp;", "&").lstrip("?"))
        assert params["q"] == ["garcia"]
        assert params["status_filter"] == ["PENDING", "COMPLETED"]
        assert params["agent_id"] == ["3"]
        assert params["per_page"] == ["50"]
        assert params["b_q"] == ["ana"]
        assert len(params["page"]) == 1
    pages = sorted({int(parse_qs(h.replace("&amp;", "&").lstrip("?"))["page"][0]) for h in hrefs})
    # Anterior (1), 1..4 (actual ±2), última (13), Siguiente (3)
    assert pages == [1, 2, 3, 4, 13]
    assert 'aria-label="Paginación de alertas"' in html
    assert re.search(r'aria-current="page"[^>]*>2<', html)
    assert "Mostrando" in html and "51–100" in html and "633" in html


def test_macro_pagina_de_compradores_no_toca_page():
    html = _render_pagination(
        paginate_params(1, 100, 250), "page=4&per_page=100", param="b_page", label="compradores",
        anchor="compradores",
    )
    href = re.search(r'href="([^"]+)" rel="next"', html).group(1)
    path, _, anchor = href.partition("#")
    params = parse_qs(path.replace("&amp;", "&").lstrip("?"))
    assert params == {"page": ["4"], "per_page": ["100"], "b_page": ["2"]}
    assert anchor == "compradores"


def test_macro_extremos_deshabilitados():
    html = _render_pagination(paginate_params(1, 50, 120), "", label="alertas")
    assert html.count('aria-disabled="true"') == 1  # Anterior
    assert re.search(r'<a role="link" aria-disabled="true"[^>]*>\s*<svg[^>]*>.*?</svg>\s*Anterior', html, re.S)
    last = _render_pagination(paginate_params(3, 50, 120), "page=3", label="alertas")
    assert re.search(r'<a role="link" aria-disabled="true"[^>]*>\s*Siguiente', last)


def test_macro_una_sola_pagina_y_vacio():
    one = _render_pagination(paginate_params(1, 100, 40), "", label="alertas")
    assert "1–40" in one and "href=" not in one
    empty = _render_pagination(paginate_params(1, 100, 0), "", label="alertas")
    assert "Sin resultados" in empty and "href=" not in empty


# ---------------------------------------------------------------------------
# Ruta /alerts en proceso contra SQLite en memoria
# ---------------------------------------------------------------------------

N_PENDING = 120
N_IN_PROGRESS = 6
N_COMPLETED = 10
N_CANCELLED = 3
N_BUYERS = 130


@pytest.fixture(scope="module")
def sqlite_db():
    import app.db.base as db_base
    from app.models.agent import Agent
    from app.models.buyer import Buyer
    from app.models.company import Company
    from app.models.property import Property
    from app.models.property_alert import PropertyAlert
    from app.models.role import Role
    from app.models.user import User

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    db_base.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    company = Company(code="MOYZA", name="MOYZA", primary_color="#000000")
    admin_role = Role(name="admin")
    agent_role = Role(name="agent")
    admin = User(email="admin@example.com", full_name="Admin", hashed_password="x", role=admin_role)
    agent_user = User(email="agente@example.com", full_name="Agente", hashed_password="x", role=agent_role)
    agent = Agent(name="Agente Uno", email="agente@example.com")
    admin.companies.append(company)
    agent_user.companies.append(company)
    agent.companies.append(company)
    db.add_all([company, admin, agent_user, agent])
    db.flush()

    prop = Property(title="Piso Centro", address="Calle Real 1", city="Jaen",
                    company_id=company.id, agent_id=agent.id)
    db.add(prop)
    buyers = [Buyer(name=f"Comprador-{i:03d}", company_id=company.id, created_by=admin.id)
              for i in range(N_BUYERS)]
    db.add_all(buyers)
    db.flush()

    now = datetime(2026, 10, 1, 12, 0, 0)
    alerts = []
    # Pendientes: la 000 es la más reciente (sale primero)
    for i in range(N_PENDING):
        alerts.append(PropertyAlert(
            property_id=prop.id, agent_id=agent.id, created_by=admin.id,
            lead_name=f"Interesado-{i:03d}", status=AlertStatus.PENDING, priority="NORMAL",
            created_at=now - timedelta(minutes=i), buyer_id=buyers[i].id,
            business_type="Venta" if i % 2 == 0 else "Alquiler",
        ))
    # El resto, más antiguas que todas las pendientes
    for prefix, status, count in (("Proceso", AlertStatus.IN_PROGRESS, N_IN_PROGRESS),
                                  ("Cerrada", AlertStatus.COMPLETED, N_COMPLETED),
                                  ("Anulada", AlertStatus.CANCELLED, N_CANCELLED)):
        for i in range(count):
            alerts.append(PropertyAlert(
                property_id=prop.id, agent_id=agent.id, created_by=admin.id,
                lead_name=f"{prefix}-{i:03d}", status=status, priority="NORMAL",
                created_at=now - timedelta(days=1, minutes=i),
            ))
    db.add_all(alerts)
    db.commit()

    yield {"db": db, "company": company, "admin": admin, "agent_user": agent_user}

    db.close()
    engine.dispose()


def _get(data, query="", user="admin", cookie=""):
    """Llama a alerts_page como lo haría FastAPI con esa query string."""
    headers = [(b"host", b"testserver")]
    if cookie:
        headers.append((b"cookie", cookie.encode()))
    company = data["company"]
    request = Request({
        "type": "http", "method": "GET", "scheme": "http", "server": ("testserver", 80),
        "path": "/alerts", "root_path": "", "query_string": query.encode(), "headers": headers,
        "state": {"user": data[user], "company": company, "allowed_companies": [company]},
    })
    params = parse_qs(query, keep_blank_values=True)

    def one(name, default=None):
        return params[name][0] if name in params else default

    response = asyncio.run(alerts_page(
        request,
        q=one("q", ""),
        status_filter=params.get("status_filter", []),
        agent_id=one("agent_id"),
        page=one("page"),
        per_page=one("per_page"),
        b_q=one("b_q", ""),
        b_page=one("b_page"),
        db=data["db"],
    ))
    return response, response.body.decode("utf-8")


def _alerts_table(html):
    start = html.index('id="panel-alerts"')
    return html[start:html.index('id="compradores"', start)]


def _buyers_table(html):
    start = html.index('id="compradores"')
    return html[start:html.index("<!-- Modal", start)]


def test_ruta_vista_por_defecto_solo_abiertas(sqlite_db):
    response, html = _get(sqlite_db)
    ctx = response.context
    assert ctx["default_status_view"] is True
    assert ctx["effective_statuses"] == [AlertStatus.PENDING, AlertStatus.IN_PROGRESS]
    assert ctx["total_alerts"] == N_PENDING + N_IN_PROGRESS
    assert ctx["alert_pagination"]["per_page"] == 100
    assert len(ctx["alerts"]) == 100
    assert {a.status for a in ctx["alerts"]} <= {AlertStatus.PENDING, AlertStatus.IN_PROGRESS}

    # Casillas marcadas según los estados efectivos y aviso de vista por defecto
    for value in ("PENDING", "IN_PROGRESS"):
        assert re.search(rf'value="{value}"\s+checked', html)
    for value in ("COMPLETED", "CANCELLED"):
        assert not re.search(rf'value="{value}"\s+checked', html)
    assert "Marca Completada o Cancelada para verlas" in html
    assert "Mostrando" in html and f"1–100</span> de <span class=\"font-medium text-gray-900 tabular-nums\">{N_PENDING + N_IN_PROGRESS}" in html

    # Sin per_page explícito no se toca la cookie
    assert PER_PAGE_COOKIE not in response.headers.get("set-cookie", "")


def test_ruta_pagina_2_de_50_conserva_filtros(sqlite_db):
    query = "q=Interesado&status_filter=PENDING&status_filter=IN_PROGRESS&per_page=50&page=2"
    response, html = _get(sqlite_db, query)
    ctx = response.context

    names = [a.lead_name for a in ctx["alerts"]]
    assert names == [f"Interesado-{i:03d}" for i in range(50, 100)]
    assert ctx["total_alerts"] == N_PENDING
    table = _alerts_table(html)
    assert "Interesado-050" in table and "Interesado-099" in table
    assert "Interesado-049" not in table and "Interesado-100" not in table

    # Los enlaces de paginación (alertas y compradores) conservan los filtros
    hrefs = [h.replace("&amp;", "&") for h in re.findall(r'href="(\?[^"]+)"', html)]
    assert hrefs
    for href in hrefs:
        params = parse_qs(href.split("#")[0].lstrip("?"))
        assert params["q"] == ["Interesado"]
        assert params["status_filter"] == ["PENDING", "IN_PROGRESS"]
        assert params["per_page"] == ["50"]

    # per_page explícito: se recuerda en la cookie (1 año, lax)
    cookie = response.headers.get("set-cookie", "")
    assert f"{PER_PAGE_COOKIE}=50" in cookie
    assert "Max-Age=31536000" in cookie and "SameSite=lax" in cookie


def test_ruta_contadores_antes_del_filtro_de_estado(sqlite_db):
    response, _ = _get(sqlite_db, "status_filter=COMPLETED")
    ctx = response.context
    assert ctx["total_alerts"] == N_COMPLETED
    assert {a.status for a in ctx["alerts"]} == {AlertStatus.COMPLETED}
    # Las tarjetas siguen siendo totales por estado, no los del filtro
    assert ctx["pending_count"] == N_PENDING
    assert ctx["in_progress_count"] == N_IN_PROGRESS
    assert ctx["completed_count"] == N_COMPLETED


def test_ruta_texto_sin_estados_busca_en_todos(sqlite_db):
    response, html = _get(sqlite_db, "q=Cerrada")
    ctx = response.context
    assert ctx["default_status_view"] is False
    assert ctx["effective_statuses"] == []
    assert ctx["total_alerts"] == N_COMPLETED
    assert not re.search(r'name="status_filter" value="[A-Z_]+"\s+checked', html)
    # Las tarjetas cuentan bajo el filtro de texto
    assert (ctx["pending_count"], ctx["completed_count"]) == (0, N_COMPLETED)


def test_ruta_pagina_fuera_de_rango_y_no_numerica(sqlite_db):
    response, _ = _get(sqlite_db, "page=999&per_page=50")
    p = response.context["alert_pagination"]
    assert p["page"] == p["pages"] == 3
    assert len(response.context["alerts"]) == N_PENDING + N_IN_PROGRESS - 100

    response, _ = _get(sqlite_db, "page=abc&per_page=xyz")
    assert response.context["alert_pagination"]["page"] == 1
    assert response.context["per_page"] == 100
    assert f"{PER_PAGE_COOKIE}=100" in response.headers.get("set-cookie", "")


def test_ruta_per_page_desde_cookie(sqlite_db):
    response, html = _get(sqlite_db, "", cookie=f"{PER_PAGE_COOKIE}=200")
    assert response.context["per_page"] == 200
    assert len(response.context["alerts"]) == N_PENDING + N_IN_PROGRESS
    assert re.search(r'<option value="200"\s+selected', html)
    assert PER_PAGE_COOKIE not in response.headers.get("set-cookie", "")

    # Cookie con un valor manipulado → 100
    response, _ = _get(sqlite_db, "", cookie=f"{PER_PAGE_COOKIE}=5000")
    assert response.context["per_page"] == 100


def test_ruta_compradores_paginados_con_totales(sqlite_db):
    response, html = _get(sqlite_db, "per_page=50&b_page=3&page=2")
    ctx = response.context
    assert [b.name for b in ctx["buyers"]] == [f"Comprador-{i:03d}" for i in range(100, N_BUYERS)]
    assert ctx["buyer_pagination"]["total"] == N_BUYERS
    # Título y desglose por operación: totales de todos los visibles
    assert ctx["total_visible_buyers"] == N_BUYERS
    assert ctx["buyer_operation_counts"] == {"Alquiler": N_PENDING // 2, "Venta": N_PENDING // 2}
    # Columna "Alertas": solo los compradores de la página
    assert set(ctx["buyer_alert_counts"]) == {b.id for b in ctx["buyers"] if int(b.name[-3:]) < N_PENDING}

    buyers_html = _buyers_table(html)
    # La paginación de compradores conserva la página de alertas y cambia solo b_page
    prev_href = re.search(r'href="([^"]+)" rel="prev"', buyers_html).group(1).replace("&amp;", "&")
    params = parse_qs(prev_href.split("#")[0].lstrip("?"))
    assert params == {"per_page": ["50"], "b_page": ["2"], "page": ["2"]}


def test_ruta_buscador_de_compradores(sqlite_db):
    response, html = _get(sqlite_db, "status_filter=COMPLETED&b_q=Comprador-12")
    ctx = response.context
    assert [b.name for b in ctx["buyers"]] == [f"Comprador-{i:03d}" for i in range(120, 130)]
    assert ctx["buyer_pagination"]["total"] == 10
    assert ctx["total_visible_buyers"] == N_BUYERS

    buyers_html = _buyers_table(html)
    # El buscador lleva los filtros de alertas en campos ocultos
    assert '<input type="hidden" name="status_filter" value="COMPLETED">' in buyers_html
    assert '<input type="hidden" name="per_page" value="100">' in buyers_html
    # "Limpiar" quita solo la búsqueda de compradores
    clear = re.search(r'<a href="(/alerts[^"]*)"[^>]*>\s*Limpiar', buyers_html).group(1)
    assert clear.replace("&amp;", "&") == "/alerts?status_filter=COMPLETED#compradores"

    response, html = _get(sqlite_db, "b_q=nadie-se-llama-asi")
    assert response.context["buyers"] == []
    assert "No hay compradores que coincidan" in _buyers_table(html)


def test_ruta_agente_bloqueo_sobre_toda_la_cola(sqlite_db):
    # Ninguna alerta tiene seguimiento: solo la más antigua de la cola está
    # desbloqueada, aunque no esté en la página que se ve.
    response, _ = _get(sqlite_db, "per_page=50&page=2", user="agent_user")
    ctx = response.context
    assert ctx["is_admin"] is False
    assert len(ctx["alerts"]) == 50
    assert len(ctx["locked_alert_ids"]) == N_PENDING + N_IN_PROGRESS - 1
    assert all(a.id in ctx["locked_alert_ids"] for a in ctx["alerts"])


def test_ruta_estado_vacio_vista_por_defecto(sqlite_db):
    response, html = _get(sqlite_db, "agent_id=999")
    assert response.context["total_alerts"] == 0
    table = _alerts_table(html)
    assert "No hay alertas pendientes ni en proceso" in table
    assert "Sin resultados" in table


def test_modal_filtro_usa_autocompletado(sqlite_db):
    _, html = _get(sqlite_db)
    assert 'id="fcBuyerSelect"' not in html
    assert 'id="fcBuyerSearch"' in html
    assert '<input type="hidden" name="buyer_id" id="fcBuyerIdHidden">' in html
    # Ya no se vuelcan todos los compradores en un <option>
    assert not re.search(r"<option[^>]*>\s*Comprador-", html)
