from fastapi import FastAPI

from app.db.base import Base
from app.db.session import engine

from app.api.v1.endpoints.users import router as users_router

app = FastAPI(
    title="MOYZA API"
)

Base.metadata.create_all(bind=engine)

app.include_router(
    users_router,
    prefix="/api/v1/users",
    tags=["Users"]
)


@app.get("/")
def root():

    return {
        "message": "MOYZA API"
    }