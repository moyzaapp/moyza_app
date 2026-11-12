"""
Pantalla "Actividad Usuarios": traducción del registro a acciones, filtros y
ruta (app/services/activity_log_view.py, app/web/routes/activity_logs.py).

Funciones puras sin base de datos; filtros y ruta en proceso contra la SQLite
en memoria de tests/test_alert_search.py (no necesitan la app levantada).

    docker exec moyza_backend python -m pytest tests/test_activity_log_view.py -q
"""
import asyncio
from datetime import date, datetime, timedelta

from tests import test_alert_search
from tests.test_alert_search import _request

from app.services import activity_log_view as view

env = test_alert_search.env

NOW = datetime(2026, 11, 11, 10, 0)  # UTC; en Madrid, 11/11/2026 11:00


# ---------------------------------------------------------------------------
# describe / outcome
# ---------------------------------------------------------------------------

def test_describe_traduce_rutas_conocidas():
    info = view.describe("POST", "/alerts/create", 303)
    assert (info["module"], info["label"], info["kind"]) == (
        "Compradores", "Registró una alerta de comprador", "change")

    info = view.describe("GET", "/properties/15", 200)
    assert info["label"] == "Abrió la ficha de una propiedad"
    assert (info["detail"], info["href"], info["kind"]) == ("#15", "/properties/15", "view")

    # Un cambio enseña el id pero no enlaza (puede ser un borrado)
    info = view.describe("POST", "/alerts/7/delete", 303)
    assert (info["detail"], info["href"]) == ("#7", None)


def test_describe_consulta_de_telefono():
    info = view.describe("GET", "/properties?tab=phone_check · tel 34600112233 · 2 propiedades", 200)
    assert info["kind"] == "lookup" and info["module"] == "Propiedades"
    assert "600" in info["detail"] and "2 propiedades en cartera" in info["detail"]

    info = view.describe("GET", "/properties?tab=phone_check · tel 34600112233 · 1 propiedades", 200)
    assert "1 propiedad en cartera" in info["detail"]

    info = view.describe("GET", "/properties?tab=phone_check · tel +41791234567 · 0 propiedades", 200)
    assert "sin propiedades en cartera" in info["detail"]


def test_describe_login_segun_resultado():
    assert view.describe("POST", "/login", 303)["label"] == "Inició sesión"
    assert view.describe("POST", "/login", 200)["label"] == "Intento de acceso fallido"
    assert view.describe("GET", "/logout", 303)["kind"] == "session"


def test_describe_ruido_y_rutas_sin_regla():
    for path in ("/api/alerts/unread-count", "/favicon.ico", "/alerts/check-buyer",
                 "/alerts/9/mark-read", "/api/ai-logs/stats/summary"):
        assert view.describe("GET", path, 200)["kind"] == "tech", path

    info = view.describe("GET", "/ruta/desconocida", 200)
    assert (info["module"], info["label"]) == ("Sistema", "Abrió una página")
    assert view.describe("POST", "/alerts/3/algo-nuevo", 303)["module"] == "Compradores"


def test_outcome():
    assert view.outcome(200) is None and view.outcome(303) is None and view.outcome(None) is None
    assert view.outcome(403) == ("Sin permiso", "amber")
    assert view.outcome(404) == ("No encontrado", "amber")
    assert view.outcome(400) == ("Rechazado", "amber")
    assert view.outcome(500) == ("Error del sistema", "red")


# ---------------------------------------------------------------------------
# Período y paginación
# ---------------------------------------------------------------------------

def test_periodo_por_defecto_y_atajos():
    span = view.resolve_period(None, None, None, now=NOW)
    assert span["period"] == "7d"
    assert (span["date_from"], span["date_to"]) == (date(2026, 11, 5), date(2026, 11, 11))
    # Medianoche de Madrid en noviembre (UTC+1), fin excluido
    assert span["start"] == datetime(2026, 11, 4, 23, 0)
    assert span["end"] == datetime(2026, 11, 11, 23, 0)

    assert view.resolve_period("hoy", None, None, now=NOW)["date_from"] == date(2026, 11, 11)
    assert view.resolve_period("raro", None, None, now=NOW)["period"] == "7d"


def test_periodo_con_fechas():
    span = view.resolve_period("hoy", "2026-10-20", "2026-10-01", now=NOW)
    assert span["period"] == "custom"
    assert (span["date_from"], span["date_to"]) == (date(2026, 10, 1), date(2026, 10, 20))

    # Un rango que coincide con un atajo cuenta como el atajo
    assert view.resolve_period(None, "2026-11-05", "2026-11-11", now=NOW)["period"] == "7d"
    # Una sola fecha o una fecha mal escrita: se ignoran
    assert view.resolve_period("30d", "2026-10-01", "no-es-fecha", now=NOW)["period"] == "30d"


def test_paginate():
    p = view.paginate("3", 120)
    assert (p["page"], p["pages"], p["start"], p["end"]) == (3, 3, 101, 120)
    assert view.paginate("99", 120)["page"] == 3
    assert view.paginate("abc", 0) | {} == view.paginate(1, 0)
    assert view.paginate(1, 0)["start"] == 0


# ---------------------------------------------------------------------------
# Filtros SQL y ruta
# ---------------------------------------------------------------------------

def _seed(env):
    from app.models.user_activity_log import UserActivityLog
    ana, bea = env.users["ana"], env.users["bea"]
    recent = datetime.utcnow() - timedelta(hours=1)
    rows = [
        (ana.id, "GET", "/alerts", 200),
        (ana.id, "POST", "/alerts/create", 303),
        (ana.id, "GET", "/properties?tab=phone_check · tel 34600112233 · 2 propiedades", 200),
        (ana.id, "GET", "/properties?tab=phone_check", 200),
        (ana.id, "GET", "/api/alerts/unread-count", 200),
        (None, "GET", "/api/notifications/unread-count", 401),
        (bea.id, "POST", "/login", 303),
        (bea.id, "GET", "/agents/3/offboarding", 404),
        (bea.id, "POST", "/visits/create/5", 303),
    ]
    for user_id, method, path, status in rows:
        env.db.add(UserActivityLog(user_id=user_id, method=method, path=path, status_code=status,
                                   ip_address="10.0.0.1", duration_ms=12, created_at=recent))
    # Fuera del período por defecto (7 días)
    env.db.add(UserActivityLog(user_id=ana.id, method="POST", path="/clients/create", status_code=303,
                               created_at=datetime.utcnow() - timedelta(days=20)))
    env.db.commit()


def _page(env, user=None, **query):
    from app.web.routes.activity_logs import activity_logs
    params = dict(period=None, date_from=None, date_to=None, user_id=None, kind=None,
                  module=None, q=None, page=None)
    params.update(query)
    # La ruta valida al admin con `require_admin_role`, que lee la cookie de sesión
    from app.core.security import create_access_token
    user = user or env.admin
    request = _request(env, user, "/activity-logs")
    token = create_access_token({"sub": user.email})
    request.scope["headers"].append((b"cookie", f"access_token={token}".encode()))
    return asyncio.run(activity_logs(request, db=env.db, **params))


def _paths(response):
    return [row["log"].path for row in response.context["rows"]]


def test_por_defecto_oculta_el_ruido_y_lo_antiguo(env):
    _seed(env)
    response = _page(env)
    paths = _paths(response)
    assert len(paths) == 7
    assert "/api/alerts/unread-count" not in paths
    assert "/api/notifications/unread-count" not in paths
    assert "/clients/create" not in paths
    assert response.context["has_filters"] is False


def test_indicadores_y_resumen_por_usuario(env):
    _seed(env)
    context = _page(env).context
    # El 401 del sondeo no es un error; el 404 de Bea sí
    assert context["kpis"] == {"active_users": 2, "changes": 2, "phone_checks": 1, "errors": 1, "logins": 1}

    stats = {row.full_name: row for row in context["user_stats"]}
    ana, bea = stats["Ana"], stats["Bea"]
    assert (ana.views, ana.changes, ana.phone_checks, ana.errors) == (2, 1, 1, 0)
    assert (bea.views, bea.changes, bea.phone_checks, bea.errors) == (1, 1, 0, 1)


def test_filtros_de_tipo(env):
    _seed(env)
    assert _paths(_page(env, kind="phone")) == [
        "/properties?tab=phone_check · tel 34600112233 · 2 propiedades"]
    assert sorted(_paths(_page(env, kind="changes"))) == ["/alerts/create", "/visits/create/5"]
    assert _paths(_page(env, kind="session")) == ["/login"]
    assert _paths(_page(env, kind="errors")) == ["/agents/3/offboarding"]
    assert len(_paths(_page(env, kind="all"))) == 9
    # Un tipo desconocido cae en el de por defecto
    assert len(_paths(_page(env, kind="loquesea"))) == 7


def test_filtros_de_usuario_modulo_texto_y_periodo(env):
    _seed(env)
    bea_id = env.users["bea"].id
    assert len(_paths(_page(env, user_id=str(bea_id)))) == 3
    assert len(_paths(_page(env, user_id="abc"))) == 7

    assert sorted(_paths(_page(env, module="compradores"))) == ["/alerts", "/alerts/create"]
    assert len(_paths(_page(env, module="propiedades"))) == 2
    assert _paths(_page(env, module="visitas")) == ["/visits/create/5"]

    assert len(_paths(_page(env, q="600112233"))) == 1
    assert len(_paths(_page(env, q="Bea"))) == 3

    response = _page(env, period="30d", kind="changes")
    assert "/clients/create" in _paths(response)
    assert response.context["has_filters"] is True
    assert response.context["base_qs"] == {"period": "30d", "kind": "changes"}


def test_filas_traducidas_y_render(env):
    _seed(env)
    response = _page(env, kind="phone")
    row = response.context["rows"][0]
    assert row["label"] == "Consultó un teléfono de propietario"
    assert row["kind_badge"] == view.KIND_BADGES["lookup"]
    assert row["outcome"] is None

    body = _page(env).body.decode()
    assert "Registró una alerta de comprador" in body
    assert "Resumen por usuario" in body and "Sin permiso" not in body
    assert "No encontrado" in body


def test_solo_admin(env):
    _seed(env)
    response = _page(env, user=env.users["ana"])
    assert response.status_code == 303
