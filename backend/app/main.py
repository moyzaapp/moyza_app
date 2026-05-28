import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.db.base import Base
from app.db.session import engine
from app.api.v1.router import api_router
from app.web.routes import dashboard, clients, agents, auth, properties, reports
from app.web.middleware.auth import AuthMiddleware


app = FastAPI(title="MOYZA API")

if os.getenv("DB_AUTOCREATE", "false").lower() == "true":
    Base.metadata.create_all(bind=engine)

app.add_middleware(AuthMiddleware)

app.include_router(api_router, prefix="/api/v1")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.mount("/storage", StaticFiles(directory="storage"), name="storage")
app.include_router(dashboard.router)
app.include_router(clients.router)
app.include_router(agents.router)
app.include_router(auth.router)
app.include_router(properties.router)
app.include_router(reports.router)


@app.get("/")
def root():
    return {"message": "MOYZA API"}