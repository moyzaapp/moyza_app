import os
from fastapi import FastAPI

from app.db.base import Base
from app.db.session import engine
from app.api.v1.router import api_router

app = FastAPI(title="MOYZA API")

if os.getenv("DB_AUTOCREATE", "false").lower() == "true":
    Base.metadata.create_all(bind=engine)

app.include_router(api_router, prefix="/api/v1")

@app.get("/")
def root():
    return {"message": "MOYZA API"}