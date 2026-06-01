from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="templates")

@router.get("/")
async def index():
    """루트 경로 접속 시 /rs 로 리다이렉트"""
    return RedirectResponse(url="/rs")

@router.get("/rs", response_class=HTMLResponse)
async def dashboard(request: Request, date: str | None = None):
    """메인 대시보드 페이지 서빙"""
    return templates.TemplateResponse(
        request=request, name="index.html", context={"date": date}
    )
