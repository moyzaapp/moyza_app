"""
Métricas de rendimiento por petición: tiempo total, número de consultas SQL y
tiempo total en base de datos.

- Cabecera `Server-Timing` en cada respuesta HTML/JSON: se ve en el navegador
  (DevTools → Red → la petición → pestaña "Tiempos").
- Línea de log `app.perf` por petición. Las peticiones lentas o con muchas
  consultas se registran como WARNING para encontrarlas fácilmente.

Las consultas se cuentan con eventos de SQLAlchemy sobre el engine y se
acumulan en un objeto guardado en un ContextVar. El objeto es mutable y se
comparte con las tareas hijas (middlewares, threadpool), así que todas las
consultas de la petición suman al mismo contador.
"""

import logging
import time
from contextvars import ContextVar
from typing import Optional

from sqlalchemy import event
from sqlalchemy.engine import Engine


logger = logging.getLogger("app.perf")

# Umbrales a partir de los cuales una petición se registra como WARNING
SLOW_REQUEST_MS = 1000
MANY_QUERIES = 50

SKIP_PREFIXES = ("/static", "/storage", "/docs", "/redoc", "/openapi")


class RequestStats:
    __slots__ = ("queries", "db_seconds")

    def __init__(self):
        self.queries = 0
        self.db_seconds = 0.0


_current_stats: ContextVar[Optional[RequestStats]] = ContextVar("request_stats", default=None)


def install_query_counter(engine: Engine) -> None:
    """Registra los eventos que cuentan consultas y su duración."""

    @event.listens_for(engine, "before_cursor_execute")
    def _before(conn, cursor, statement, parameters, context, executemany):
        conn.info.setdefault("query_start", []).append(time.perf_counter())

    @event.listens_for(engine, "after_cursor_execute")
    def _after(conn, cursor, statement, parameters, context, executemany):
        started = conn.info["query_start"].pop()
        stats = _current_stats.get()
        if stats is not None:
            stats.queries += 1
            stats.db_seconds += time.perf_counter() - started


class RequestMetricsMiddleware:
    """Middleware ASGI puro: mide la petición completa (incluidos los demás middlewares)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"].startswith(SKIP_PREFIXES):
            await self.app(scope, receive, send)
            return

        stats = RequestStats()
        token = _current_stats.set(stats)
        started = time.perf_counter()
        status_code = 500

        async def send_with_timing(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                total_ms = (time.perf_counter() - started) * 1000
                header = (
                    f"app;dur={total_ms:.0f}, "
                    f"db;dur={stats.db_seconds * 1000:.0f};desc=\"{stats.queries} consultas\""
                )
                message.setdefault("headers", [])
                message["headers"].append((b"server-timing", header.encode("latin-1")))
            await send(message)

        try:
            await self.app(scope, receive, send_with_timing)
        finally:
            total_ms = (time.perf_counter() - started) * 1000
            _current_stats.reset(token)

            level = (
                logging.WARNING
                if total_ms >= SLOW_REQUEST_MS or stats.queries >= MANY_QUERIES
                else logging.INFO
            )
            logger.log(
                level,
                "%s %s -> %s | %.0f ms | %d consultas | %.0f ms en BD",
                scope["method"], scope["path"], status_code,
                total_ms, stats.queries, stats.db_seconds * 1000,
            )
