from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from db import get_session
import crud.rs

router = APIRouter()
templates = Jinja2Templates(directory="templates")

@router.get("/rs-table", response_class=HTMLResponse)
async def get_rs_table(
    request: Request, 
    date: str = None,
    session: Session = Depends(get_session)
):
    """HTMX 요청을 받아 해당 날짜의 전체 DB 데이터를 읽고 table partial을 렌더링"""
    
    stocks = crud.rs.get_rs_table_data(
        session=session,
        date_str=date
    )

    return templates.TemplateResponse(
        request=request, 
        name="partials/table.html", 
        context={
            "stocks": stocks
        }
    )
