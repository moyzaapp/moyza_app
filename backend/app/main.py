import os

from fastapi import FastAPI

from app.db.base import Base
from app.db.session import engine

from app.api.v1.endpoints.users import router as users_router
from app.api.v1.endpoints.auth import router as auth_router

app = FastAPI(
    title="MOYZA API"
)

if os.getenv("DB_AUTOCREATE", "false").lower() == "true":
    Base.metadata.create_all(bind=engine)

app.include_router(users_router, prefix="/api/v1/users", tags=["Users"])
app.include_router(auth_router, prefix="/api/v1/auth", tags=["Auth"])

@app.get("/")
def root():

    return {
        "message": "MOYZA API"
    }