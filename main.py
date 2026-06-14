from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from db import create_db_and_tables
from routes.views.dashboard import router as dashboard_router
from routes.api.rs import router as rs_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 앱 시작 시 DB 테이블 생성 확인
    create_db_and_tables()
    yield

app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(dashboard_router)
app.include_router(rs_router, prefix="/api")
