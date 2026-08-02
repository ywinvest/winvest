from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from routes.views.dashboard import router as dashboard_router
from routes.api.rs import router as rs_router
from routes.api.market import router as market_router

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(dashboard_router)
app.include_router(rs_router, prefix="/api")
app.include_router(market_router, prefix="/api")
