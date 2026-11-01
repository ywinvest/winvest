from fastapi import APIRouter

from app.api.routes import market, rs, views

api_router = APIRouter()
api_router.include_router(views.router)
api_router.include_router(market.router)
api_router.include_router(rs.router)

