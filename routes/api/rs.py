from fastapi import APIRouter, Request, Depends, Query
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
    date: str = Query(default=None),
    search: str = Query(default=None),
    market: str = Query(default=None),
    min_marcap: int = Query(default=None),
    sort_col: str = Query(default="rs"),
    sort_order: str = Query(default="desc"),
    page: int = Query(default=1),
    session: Session = Depends(get_session)
):
    """HTMX 요청을 받아 해당 날짜의 전체 DB 데이터를 읽고 table partial을 렌더링"""
    limit = 50
    offset = (page - 1) * limit
    
    stocks = crud.rs.get_rs_table_data(
        session=session,
        date_str=date,
        search=search,
        market=market,
        min_marcap=min_marcap,
        sort_col=sort_col,
        sort_order=sort_order,
        limit=limit,
        offset=offset
    )

    next_page = page + 1 if len(stocks) == limit else None

    template_name = "partials/rows.html" if page > 1 else "partials/table.html"

    return templates.TemplateResponse(
        request=request, 
        name=template_name, 
        context={
            "stocks": stocks,
            "next_page": next_page,
            "search": search,
            "market": market,
            "min_marcap": min_marcap,
            "sort_col": sort_col,
            "sort_order": sort_order
        }
    )
