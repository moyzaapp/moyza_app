from fastapi import APIRouter
from app.api.v1.endpoints import clients
from app.api.v1.endpoints import auth

api_router = APIRouter()
api_router.include_router(clients.router, prefix="/clients", tags=["clients"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])