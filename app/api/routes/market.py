from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.api.deps import templates
from app.crud.market import get_market_dashboard_data

router = APIRouter(prefix="/api", tags=["market"])

PARTIAL_CACHE_HEADERS = {
    "Cache-Control": "public, s-maxage=3600, stale-while-revalidate=86400"
}


@router.get("/market-status", response_class=HTMLResponse)
def market_status(request: Request):
    """HTMX 요청을 받아 KOSPI/KOSDAQ 시장 상태 및 RS Top 5 파셜을 렌더링"""
    context = get_market_dashboard_data()
    return templates.TemplateResponse(
        request=request,
        name="partials/market_status.html",
        context=context,
        headers=PARTIAL_CACHE_HEADERS,
    )
