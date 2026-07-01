import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.logging_config import setup_logging
from app.db.base import Base
from app.db.session import engine
from app.api.v1.router import api_router
from app.web.routes import dashboard, clients, agents, auth, properties, reports, report_logs, ai_logs, visits
from app.web.middleware.auth import AuthMiddleware
from app.web.middleware.flash import FlashMiddleware
from app.jobs.scheduler import start_scheduler, shutdown_scheduler

# Configurar logging antes de inicializar la app
setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Maneja el ciclo de vida de la aplicación."""
    # Startup
    logger.info("Iniciando aplicación MOYZA")
    start_scheduler()
    yield
    # Shutdown
    logger.info("Deteniendo aplicación MOYZA")
    shutdown_scheduler()


app = FastAPI(title="MOYZA API", lifespan=lifespan)

if os.getenv("DB_AUTOCREATE", "false").lower() == "true":
    Base.metadata.create_all(bind=engine)

app.add_middleware(AuthMiddleware)
app.add_middleware(FlashMiddleware)

app.include_router(api_router, prefix="/api/v1")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.mount("/storage", StaticFiles(directory="storage"), name="storage")
app.mount("/signatures", StaticFiles(directory="signatures"), name="signatures")
app.include_router(dashboard.router)
app.include_router(clients.router)
app.include_router(agents.router)
app.include_router(auth.router)
app.include_router(properties.router)
app.include_router(visits.router)
app.include_router(reports.router)
app.include_router(report_logs.router)
app.include_router(ai_logs.router)


@app.get("/")
def root():
    return {"message": "MOYZA API"}