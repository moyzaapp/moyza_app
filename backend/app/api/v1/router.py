from fastapi import APIRouter

from app.api.v1.endpoints import users, auth, clients

api_router = APIRouter()

api_router.include_router(users.router, prefix="/users", tags=["Users"])
api_router.include_router(auth.router, prefix="/auth", tags=["Auth"])
api_router.include_router(clients.router, prefix="/clients", tags=["Clients"])