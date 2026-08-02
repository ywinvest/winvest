from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="templates")

@router.get("/")
async def index():
    """루트 경로 접속 시 /market 으로 리다이렉트"""
    return RedirectResponse(url="/market")

@router.get("/market", response_class=HTMLResponse)
async def market_dashboard(request: Request, response: Response):
    """시장 상황 대시보드 페이지 서빙"""
    # Vercel Edge Cache 적용
    response.headers["Cache-Control"] = "public, s-maxage=3600, stale-while-revalidate=86400"
    return templates.TemplateResponse(
        request=request, name="pages/market.html"
    )

@router.get("/rs", response_class=HTMLResponse)
async def dashboard(request: Request, response: Response, date: str | None = None):
    """메인 대시보드 페이지 서빙"""
    # Vercel Edge Cache 적용: HTML 껍데기는 즉시 서빙되게 하여 콜드부팅 시에도 스피너가 보이도록 함
    response.headers["Cache-Control"] = "public, s-maxage=3600, stale-while-revalidate=86400"
    return templates.TemplateResponse(
        request=request, name="pages/rs.html", context={"date": date}
    )
