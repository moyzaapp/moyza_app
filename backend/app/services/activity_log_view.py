"""
Lectura del registro de actividad para la pantalla "Actividad Usuarios".

`user_activity_logs` guarda una fila por petición HTTP (método + ruta), que
tal cual no dice nada a un administrador. Este módulo la traduce:

- `describe(method, path, status_code)`: módulo de la app, acción en lenguaje
  llano ("Registró un comprador"), tipo (vista, cambio, consulta de teléfono,
  sesión, técnico), detalle ("#123", el teléfono consultado) y enlace a la
  ficha cuando existe.
- Ruido técnico (`noise_clause`): sondeos automáticos del navegador
  (contadores de avisos, favicon), autocompletados y marcas de leído. No son
  acciones de nadie; se ocultan salvo en la vista "Todo (incluye técnico)".
  Los sondeos puros (`SKIP_LOG_PATHS`) además dejan de guardarse
  (ActivityMiddleware).
- Filtros en SQL portable (LIKE / IN, sin regex) para que la ruta se pueda
  probar contra SQLite: tipo (`kind_clause`), módulo (`module_clause`),
  período en hora de Madrid (`resolve_period`).
"""
import re
from datetime import date, datetime, time, timedelta

from sqlalchemy import and_, not_, or_

from app.core.business_calendar import madrid_today, to_utc
from app.core.phone import phone_display
from app.models.user_activity_log import UserActivityLog

PAGE_SIZE = 50

# Texto que deja la consulta de teléfono de Propiedades en `path`
# (app/web/routes/properties.py): "/properties?tab=phone_check · tel X · N propiedades"
PHONE_CHECK_PREFIX = "/properties?tab=phone_check"
_PHONE_CHECK = re.compile(r"· tel (?P<phone>\S+) · (?P<count>\d+) propiedad")

# Sondeos automáticos del navegador: no se guardan en el registro
SKIP_LOG_PATHS = (
    "/api/alerts/unread-count",
    "/api/notifications/unread-count",
    "/api/notifications/recent",
    "/api/properties/last-update",
    "/favicon.ico",
)

# Ruido técnico que sí se guarda pero no es una acción del usuario
_NOISE_EXACT = (
    *SKIP_LOG_PATHS,
    "/api/notifications/mark-read",
    "/notifications/mark-all-read",
    "/api/report-logs",
    "/api/report-logs/stats",
    "/api/reminder-logs",
    "/alerts/check-buyer",
    "/alerts/check-duplicate",
    "/alerts/check-search-duplicate",
    "/alerts/search-buyers",
    "/alerts/search-properties",
)
_NOISE_LIKE = ("/api/ai-logs%", "/alerts/%/mark-read", "/notifications/%/open", "/api/v1/health%")

# Módulos (nombres del menú) y los prefijos de ruta que les corresponden
MODULES = {
    "inicio": ("Inicio", ("/dashboard",)),
    "compradores": ("Compradores", ("/alerts", "/buyers")),
    "propiedades": ("Propiedades", ("/properties",)),
    "clientes": ("Clientes", ("/clients",)),
    "visitas": ("Visitas", ("/visits", "/api/v1/visits")),
    "agentes": ("Agentes", ("/agents",)),
    "informes": ("Informes", ("/reports", "/report-logs", "/performance-reports")),
    "resultados": ("Resultados Comerciales", ("/commercial-results",)),
    "usuarios": ("Usuarios", ("/auth",)),
    "sesion": ("Sesión", ("/login", "/logout", "/switch-company")),
}

KINDS = (
    ("relevant", "Actividad relevante"),
    ("changes", "Solo cambios"),
    ("phone", "Consultas de teléfono"),
    ("session", "Accesos y sesión"),
    ("errors", "Errores"),
    ("all", "Todo (incluye técnico)"),
)
DEFAULT_KIND = "relevant"

PERIODS = (("hoy", "Hoy"), ("7d", "7 días"), ("30d", "30 días"))
DEFAULT_PERIOD = "7d"
_PERIOD_DAYS = {"hoy": 1, "7d": 7, "30d": 30}

# Tipo de acción → (etiqueta, tono de badge)
KIND_BADGES = {
    "view": ("Vista", "gray"),
    "change": ("Cambio", "blue"),
    "lookup": ("Consulta", "purple"),
    "session": ("Sesión", "gray"),
    "tech": ("Técnico", "gray"),
}

# (método o None, patrón, módulo, acción). `(\d+)` es el id que se enseña como
# detalle; gana la primera regla que coincide.
_RULES = [
    ("GET", r"/(dashboard)?", "Inicio", "Abrió Inicio"),

    ("GET", r"/login", "Sesión", "Abrió la pantalla de acceso"),
    ("GET", r"/logout", "Sesión", "Cerró sesión"),
    ("POST", r"/switch-company", "Sesión", "Cambió de empresa"),

    ("GET", r"/alerts", "Compradores", "Abrió el listado de compradores"),
    ("GET", r"/alerts-dashboard", "Compradores", "Abrió el panel de alertas"),
    ("GET", r"/alerts/assignments", "Compradores", "Abrió el historial de asignaciones"),
    ("GET", r"/alerts/(\d+)", "Compradores", "Abrió una alerta"),
    ("POST", r"/alerts/create", "Compradores", "Registró una alerta de comprador"),
    ("POST", r"/alerts/reassign-bulk", "Compradores", "Reasignó varias alertas"),
    ("POST", r"/alerts/(\d+)/reassign", "Compradores", "Reasignó una alerta"),
    ("POST", r"/alerts/(\d+)/cede", "Compradores", "Cedió una alerta"),
    ("POST", r"/alerts/(\d+)/complete", "Compradores", "Completó una alerta"),
    ("POST", r"/alerts/(\d+)/reactivate", "Compradores", "Reactivó una alerta"),
    ("POST", r"/alerts/(\d+)/delete", "Compradores", "Eliminó una alerta"),
    ("POST", r"/alerts/(\d+)/follow-up", "Compradores", "Añadió un seguimiento"),
    ("POST", r"/alerts/(\d+)/register-contact", "Compradores", "Registró un contacto"),
    ("POST", r"/alerts/(\d+)/link-property", "Compradores", "Asoció una propiedad a la alerta"),
    ("POST", r"/alerts/(\d+)/send-property", "Compradores", "Envió propiedad al comprador"),
    ("POST", r"/alerts/(\d+)/search-profile", "Compradores", "Guardó el perfil de búsqueda"),
    ("GET", r"/buyers/(\d+)", "Compradores", "Abrió la ficha de un comprador"),
    ("POST", r"/buyers/create", "Compradores", "Registró un comprador"),
    ("POST", r"/buyers/(\d+)/update-contact", "Compradores", "Actualizó el contacto de un comprador"),
    ("POST", r"/buyers/(\d+)/send-property", "Compradores", "Envió propiedad al comprador"),
    ("POST", r"/buyers/(\d+)/search-criteria", "Compradores", "Guardó el perfil de búsqueda de un comprador"),
    ("POST", r"/buyers/(\d+)/delete", "Compradores", "Eliminó un comprador"),

    ("GET", r"/properties", "Propiedades", "Abrió el listado de propiedades"),
    ("GET", r"/properties/(\d+)", "Propiedades", "Abrió la ficha de una propiedad"),
    ("POST", r"/properties/create", "Propiedades", "Creó una propiedad"),
    ("POST", r"/properties/update", "Propiedades", "Editó una propiedad"),
    ("POST", r"/properties/delete/(\d+)", "Propiedades", "Eliminó una propiedad"),
    ("POST", r"/properties/(\d+)/generate-report", "Propiedades", "Generó el informe de una propiedad"),
    ("POST", r"/properties/(\d+)/interactions/create", "Propiedades", "Registró una interacción"),

    ("GET", r"/clients", "Clientes", "Abrió el listado de clientes"),
    ("POST", r"/clients/create", "Clientes", "Creó un cliente"),
    ("POST", r"/clients/update", "Clientes", "Editó un cliente"),
    ("POST", r"/clients/delete/(\d+)", "Clientes", "Eliminó un cliente"),

    ("GET", r"/visits", "Visitas", "Abrió el listado de visitas"),
    ("GET", r"/visits/select-property", "Visitas", "Empezó una visita (elegir propiedad)"),
    ("GET", r"/visits/new/(\d+)", "Visitas", "Abrió el formulario de visita"),
    ("POST", r"/visits/create/(\d+)", "Visitas", "Registró una visita"),
    ("GET", r"/visits/edit/(\d+)", "Visitas", "Abrió una visita para editarla"),
    ("POST", r"/visits/update/(\d+)", "Visitas", "Editó una visita"),
    ("POST", r"/visits/delete", "Visitas", "Eliminó una visita"),
    ("GET", r"/visits/preview/(\d+)", "Visitas", "Revisó la hoja de visita"),
    ("GET", r"/visits/signature/(\d+)", "Visitas", "Abrió la firma del cliente"),
    ("GET", r"/visits/agent-signatures/(\d+)", "Visitas", "Abrió la firma de los agentes"),
    ("GET", r"/visits/complete/(\d+)", "Visitas", "Terminó la hoja de visita"),
    ("GET", r"/visits/(\d+)/download", "Visitas", "Descargó la hoja de visita"),
    ("POST", r"/visits/(\d+)/generate-pdf", "Visitas", "Generó el PDF de la visita"),
    ("POST", r"/visits/(\d+)/send-whatsapp", "Visitas", "Envió la hoja de visita por WhatsApp"),
    ("POST", r"/visits/(\d+)/remove-companion", "Visitas", "Quitó al agente acompañante"),
    ("POST", r"/api/v1/visits/(\d+)/accept-terms", "Visitas", "Aceptación de condiciones de la visita"),
    ("POST", r"/api/v1/visits/(\d+)/save-signature", "Visitas", "Firma del cliente guardada"),
    ("POST", r"/api/v1/visits/(\d+)/confirm-agent-signatures", "Visitas", "Firmas de los agentes confirmadas"),
    ("POST", r"/api/v1/visits/(\d+)/finalize", "Visitas", "Hoja de visita finalizada"),

    ("GET", r"/agents", "Agentes", "Abrió el listado de agentes"),
    ("POST", r"/agents/create", "Agentes", "Creó un agente"),
    ("POST", r"/agents/update", "Agentes", "Editó un agente"),
    ("POST", r"/agents/delete/(\d+)", "Agentes", "Eliminó un agente"),
    ("POST", r"/agents/(\d+)/deactivate", "Agentes", "Dio de baja a un agente"),
    ("POST", r"/agents/(\d+)/reactivate", "Agentes", "Reactivó a un agente"),
    ("POST", r"/agents/(\d+)/upload-signature", "Agentes", "Subió la firma de un agente"),
    ("GET", r"/agents/(\d+)/offboarding", "Agentes", "Revisó la baja de un agente"),

    ("GET", r"/auth", "Usuarios", "Abrió la gestión de usuarios"),
    ("POST", r"/auth/users/create", "Usuarios", "Creó un usuario"),
    ("POST", r"/auth/users/update", "Usuarios", "Editó un usuario"),
    ("POST", r"/auth/users/password", "Usuarios", "Cambió una contraseña"),
    ("POST", r"/auth/users/delete/(\d+)", "Usuarios", "Eliminó un usuario"),
    ("POST", r"/auth/users/(\d+)/deactivate", "Usuarios", "Dio de baja a un usuario"),
    ("POST", r"/auth/users/(\d+)/reactivate", "Usuarios", "Reactivó a un usuario"),
    ("GET", r"/auth/users/(\d+)/offboarding", "Usuarios", "Revisó la baja de un usuario"),

    ("GET", r"/reports", "Informes", "Abrió los informes"),
    ("POST", r"/reports/upload", "Informes", "Subió un informe"),
    ("POST", r"/reports/delete/?", "Informes", "Eliminó un informe"),
    ("GET", r"/reports/download/(\d+)", "Informes", "Descargó un informe"),
    ("POST", r"/reports/(\d+)/send-whatsapp", "Informes", "Envió un informe por WhatsApp"),
    ("GET", r"/report-logs", "Informes", "Abrió los logs de reportes"),
    ("POST", r"/api/report-logs/(\d+)/retry", "Informes", "Reintentó el envío de un informe"),
    ("GET", r"/performance-reports", "Informes", "Abrió los informes de rendimiento"),

    ("GET", r"/commercial-results", "Resultados Comerciales", "Abrió Resultados Comerciales"),
    ("GET", r"/commercial-results/(\d+)/metric/[\w-]+", "Resultados Comerciales", "Consultó el detalle de un indicador"),
    ("POST", r"/commercial-results/(\d+)/targets", "Resultados Comerciales", "Guardó los objetivos de un agente"),
    ("POST", r"/commercial-results/(\d+)/notes", "Resultados Comerciales", "Guardó observaciones para un agente"),
    ("POST", r"/commercial-results/closings", "Resultados Comerciales", "Registró un cierre"),
    ("POST", r"/commercial-results/closings/(\d+)/delete", "Resultados Comerciales", "Eliminó un cierre"),

    ("GET", r"/notifications", "Notificaciones", "Abrió las notificaciones"),
    ("GET", r"/ai-logs-dashboard", "Sistema", "Abrió Consumo IA"),
    ("GET", r"/activity-logs", "Sistema", "Abrió Actividad Usuarios"),
]
_COMPILED = [(method, re.compile(pattern + r"$"), module, label) for method, pattern, module, label in _RULES]

# Fichas a las que se puede enlazar desde el detalle "#id"
_DETAIL_LINKS = (
    (re.compile(r"/alerts/(\d+)"), "/alerts/{}"),
    (re.compile(r"/buyers/(\d+)"), "/buyers/{}"),
    (re.compile(r"/properties/(\d+)"), "/properties/{}"),
)


def _is_noise(path: str) -> bool:
    if path in _NOISE_EXACT:
        return True
    return any(
        re.fullmatch(re.escape(pattern).replace("%", ".*"), path) for pattern in _NOISE_LIKE
    )


def _module_for(path: str) -> str:
    for label, prefixes in MODULES.values():
        if any(path == p or path.startswith(p + "/") for p in prefixes):
            return label
    return "Sistema"


def describe(method: str, path: str, status_code=None) -> dict:
    """Fila del registro en lenguaje llano.

    Devuelve `module`, `label`, `kind` (clave de KIND_BADGES), `detail` (texto
    corto o None) y `href` (ficha a la que enlaza el detalle, o None).
    """
    method = (method or "").upper()
    path = path or ""

    if path.startswith(PHONE_CHECK_PREFIX):
        match = _PHONE_CHECK.search(path)
        if match:
            count = int(match.group("count"))
            found = "sin propiedades en cartera" if not count else (
                "1 propiedad en cartera" if count == 1 else f"{count} propiedades en cartera"
            )
            detail = f"{phone_display(match.group('phone'))} · {found}"
            return {"module": "Propiedades", "label": "Consultó un teléfono de propietario",
                    "kind": "lookup", "detail": detail, "href": None}
        return {"module": "Propiedades", "label": "Abrió Consultar teléfono",
                "kind": "view", "detail": None, "href": None}

    if method == "POST" and path == "/login":
        # El acceso correcto redirige; el fallido vuelve a pintar el formulario
        ok = status_code is not None and 300 <= status_code < 400
        return {"module": "Sesión", "label": "Inició sesión" if ok else "Intento de acceso fallido",
                "kind": "session", "detail": None, "href": None}

    if _is_noise(path):
        return {"module": _module_for(path), "label": "Petición automática",
                "kind": "tech", "detail": None, "href": None}

    for rule_method, pattern, module, label in _COMPILED:
        if rule_method and rule_method != method:
            continue
        match = pattern.match(path)
        if not match:
            continue
        detail, href = None, None
        ids = [group for group in match.groups() if group and group.isdigit()]
        if ids:
            detail = f"#{ids[0]}"
            if method == "GET":
                for link_pattern, template in _DETAIL_LINKS:
                    if link_pattern.fullmatch(path):
                        href = template.format(ids[0])
        kind = "session" if module == "Sesión" else ("view" if method == "GET" else "change")
        return {"module": module, "label": label, "kind": kind, "detail": detail, "href": href}

    # Ruta sin regla: se enseña tal cual, sin inventar una acción
    return {"module": _module_for(path),
            "label": "Abrió una página" if method == "GET" else "Envió un formulario",
            "kind": "view" if method == "GET" else "change", "detail": None, "href": None}


def outcome(status_code) -> tuple[str, str] | None:
    """(etiqueta, tono) del resultado, o None si la petición fue bien."""
    if status_code is None or status_code < 400:
        return None
    if status_code in (401, 403):
        return "Sin permiso", "amber"
    if status_code == 404:
        return "No encontrado", "amber"
    if status_code < 500:
        return "Rechazado", "amber"
    return "Error del sistema", "red"


# ---------------------------------------------------------------------------
# Filtros SQL
# ---------------------------------------------------------------------------

def noise_clause():
    """Ruido técnico: sondeos, autocompletados y marcas de leído."""
    path = UserActivityLog.path
    return or_(path.in_(_NOISE_EXACT), *[path.like(pattern) for pattern in _NOISE_LIKE])


def phone_clause():
    """Consultas de teléfono con número (no la simple apertura de la pestaña)."""
    return UserActivityLog.path.like(PHONE_CHECK_PREFIX + " · tel %")


def change_clause():
    """Cambios hechos por un usuario: todo lo que no es GET, sin ruido ni login."""
    return and_(
        UserActivityLog.method != "GET",
        not_(noise_clause()),
        UserActivityLog.path != "/login",
    )


def view_clause():
    """Páginas abiertas (GET), sin ruido ni consultas de teléfono."""
    return and_(UserActivityLog.method == "GET", not_(noise_clause()), not_(phone_clause()))


def error_clause():
    """Acciones rechazadas o fallidas. Sin ruido: un sondeo con la sesión
    caducada (401) no es un error de nadie."""
    return and_(UserActivityLog.status_code >= 400, not_(noise_clause()))


def kind_clause(kind: str):
    """Condición del filtro "Tipo"; None = sin condición (`all`)."""
    if kind == "all":
        return None
    if kind == "changes":
        return change_clause()
    if kind == "phone":
        return phone_clause()
    if kind == "session":
        return or_(
            UserActivityLog.path.in_(("/logout", "/switch-company")),
            and_(UserActivityLog.path == "/login", UserActivityLog.method == "POST"),
        )
    if kind == "errors":
        return error_clause()
    return not_(noise_clause())


def module_clause(module: str):
    """Condición del filtro "Módulo", o None si no es un módulo conocido."""
    entry = MODULES.get(module)
    if not entry:
        return None
    path = UserActivityLog.path
    conditions = []
    for prefix in entry[1]:
        conditions += [path == prefix, path.like(prefix + "/%"), path.like(prefix + "?%")]
    if module == "inicio":
        conditions.append(path == "/")
    return or_(*conditions)


def _parse_date(value) -> date | None:
    try:
        return date.fromisoformat(str(value).strip())
    except (TypeError, ValueError):
        return None


def resolve_period(period, date_from, date_to, now: datetime | None = None) -> dict:
    """Período del listado, en días de Madrid.

    Dos fechas válidas (`date_from`/`date_to`, ISO) mandan sobre `period`
    ("hoy", "7d", "30d"); si llegan al revés se intercambian. Devuelve
    `period` (clave o "custom"), `date_from`, `date_to` (date, ambos
    incluidos) y `start` / `end` en UTC naive (`end` excluido) para filtrar
    `created_at`.
    """
    today = madrid_today(now)
    start_day, end_day = _parse_date(date_from), _parse_date(date_to)

    if start_day and end_day:
        if start_day > end_day:
            start_day, end_day = end_day, start_day
        key = "custom"
        # Un rango escrito a mano que coincide con un atajo cuenta como el atajo
        for preset, days in _PERIOD_DAYS.items():
            if end_day == today and start_day == today - timedelta(days=days - 1):
                key = preset
    else:
        key = period if period in _PERIOD_DAYS else DEFAULT_PERIOD
        end_day = today
        start_day = today - timedelta(days=_PERIOD_DAYS[key] - 1)

    return {
        "period": key,
        "date_from": start_day,
        "date_to": end_day,
        "start": to_utc(datetime.combine(start_day, time.min)),
        "end": to_utc(datetime.combine(end_day + timedelta(days=1), time.min)),
    }


def paginate(page, total: int, per_page: int = PAGE_SIZE) -> dict:
    """Misma forma que `paginate_params` de alertas (la que pinta `ui.pagination`)."""
    try:
        page = int(str(page).strip())
    except (TypeError, ValueError):
        page = 1
    total = max(int(total or 0), 0)
    pages = max((total + per_page - 1) // per_page, 1)
    page = min(max(page, 1), pages)
    offset = (page - 1) * per_page
    return {
        "page": page, "per_page": per_page, "total": total, "pages": pages, "offset": offset,
        "start": offset + 1 if total else 0, "end": min(offset + per_page, total),
        "has_prev": page > 1, "has_next": page < pages,
    }
