from fastapi import APIRouter, Request, Response, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from db import get_session
import crud.rs

router = APIRouter()
templates = Jinja2Templates(directory="templates")

@router.get("/rs-table", response_class=HTMLResponse)
def get_rs_table(
    request: Request, 
    response: Response,
    date: str = None
):
    """HTMX 요청을 받아 해당 날짜의 전체 DB 데이터를 읽고 table partial을 렌더링"""
    
    # Vercel Edge Cache 적용: 데이터베이스 조회 결과(HTML 테이블 조각)를 CDN에 캐싱 (12시간 유지)
    response.headers["Cache-Control"] = "public, s-maxage=43200, stale-while-revalidate=86400"
    
    stocks = crud.rs.get_rs_table_data(
        date_str=date
    )

    return templates.TemplateResponse(
        request=request, 
        name="partials/table.html", 
        context={
            "stocks": stocks
        }
    )
