from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.api.deps import templates

router = APIRouter(tags=["views"])

PAGE_CACHE_HEADERS = {
    "Cache-Control": "public, s-maxage=3600, stale-while-revalidate=86400"
}


@router.get("/")
async def index():
    """루트 경로 접속 시 /market 으로 리다이렉트"""
    return RedirectResponse(url="/market")


@router.get("/market", response_class=HTMLResponse)
async def market_dashboard(request: Request):
    """시장 상황 대시보드 페이지 서빙"""
    return templates.TemplateResponse(
        request=request,
        name="pages/market.html",
        headers=PAGE_CACHE_HEADERS,
    )


@router.get("/stock")
@router.get("/rs")
async def stock_index(date: str | None = None):
    """종목 기본 경로(/stock) 및 구 경로(/rs) 접속 시 /stock/rs 로 리다이렉트"""
    target_url = f"/stock/rs?date={date}" if date else "/stock/rs"
    return RedirectResponse(url=target_url)


@router.get("/stock/rs", response_class=HTMLResponse)
async def stock_rs_dashboard(request: Request, date: str | None = None):
    """종목 상대강도(RS) 대시보드 페이지 서빙"""
    return templates.TemplateResponse(
        request=request,
        name="pages/rs.html",
        context={"date": date},
        headers=PAGE_CACHE_HEADERS,
    )
