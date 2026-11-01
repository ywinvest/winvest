from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.api.deps import templates
from app.crud.rs import get_rs_table_data

router = APIRouter(prefix="/api/stock", tags=["rs"])

PARTIAL_CACHE_HEADERS = {
    "Cache-Control": "public, s-maxage=43200, stale-while-revalidate=86400"
}


@router.get("/rs-table", response_class=HTMLResponse)
def get_rs_table(
    request: Request,
    date: str | None = None,
):
    """HTMX 요청을 받아 해당 날짜의 전체 RS 데이터를 읽고 table partial을 렌더링"""
    stocks = get_rs_table_data(date_str=date)
    return templates.TemplateResponse(
        request=request,
        name="partials/table.html",
        context={"stocks": stocks},
        headers=PARTIAL_CACHE_HEADERS,
    )
