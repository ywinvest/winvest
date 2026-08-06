from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from datetime import datetime, timedelta
from db import get_session
from models import KrxDailyStock, KrxDailyStockIndicator, KrxDailyIndex, KrxDailyIndexIndicator
import market

router = APIRouter()
templates = Jinja2Templates(directory="templates")

SIGNAL_MAP = {
  "green": "양호🟢",
  "yellow": "주의🟡",
  "red": "경고🔴"
}

def get_market_status(market_code: str, session: Session = Depends(get_session)):
    try:
        # Get the latest 2 days of market status
        market_data_list = session.exec(
            select(KrxDailyIndex)
            .where(KrxDailyIndex.market == market_code)
            .order_by(KrxDailyIndex.date.desc())
            .limit(2)
        ).all()
        
        if len(market_data_list) < 2:
            return {"status_msg": "데이터 부족", "change": 0.0, "close": 0.0, "signal": "red", "signal_text": "오류"}
            
        today_market = market_data_list[0]
        yesterday_market = market_data_list[1]
        
        today_ind = session.exec(
            select(KrxDailyIndexIndicator)
            .where(KrxDailyIndexIndicator.market == market_code)
            .where(KrxDailyIndexIndicator.date == today_market.date)
        ).first()
        
        yesterday_ind = session.exec(
            select(KrxDailyIndexIndicator)
            .where(KrxDailyIndexIndicator.market == market_code)
            .where(KrxDailyIndexIndicator.date == yesterday_market.date)
        ).first()

        if not today_ind or not yesterday_ind:
            return {"status_msg": "지표 데이터 없음", "change": 0.0, "close": 0.0, "signal": "red", "signal_text": "오류"}

        today_ma5_up = today_market.close > today_ind.ma5
        today_ma20_up = today_market.close > today_ind.ma20
        
        today_signal_raw = market.get_signal(
            today_ma20_up, today_ind.adx, today_ind.di, today_ma5_up
        )
        
        yesterday_ma5_up = yesterday_market.close > yesterday_ind.ma5
        yesterday_ma20_up = yesterday_market.close > yesterday_ind.ma20
        
        yesterday_signal_raw = market.get_signal(
            yesterday_ma20_up, yesterday_ind.adx, yesterday_ind.di, yesterday_ma5_up
        )
        
        today_signal_text = SIGNAL_MAP[today_signal_raw]
        yesterday_signal_text = SIGNAL_MAP[yesterday_signal_raw]
        
        if today_signal_text == yesterday_signal_text:
            status_msg = f"{today_signal_text} 유지"
        else:
            status_msg = f"{yesterday_signal_text} ➡ {today_signal_text} 전환"

        return {
            "status_msg": status_msg,
            "change": today_market.change,
            "close": today_market.close,
            "signal": today_signal_raw,
            "signal_text": today_signal_text
        }
    except Exception as e:
        return {"status_msg": f"오류: {e}", "change": 0.0, "close": 0.0, "signal": "red", "signal_text": "실패"}

def format_market_cap(marcap):
    if marcap is None or marcap == 0:
        return "정보없음"
    if marcap >= 1e12:
        return f"{marcap/1e12:.1f}조"
    else:
        return f"{marcap/1e8:.0f}억"

@router.get("/market-status", response_class=HTMLResponse)
def market_status(request: Request, session: Session = Depends(get_session)):
    print("market_status API called")
    # 1. KOSPI & KOSDAQ Status
    kospi = get_market_status('KS11', session)
    print("get_market_status KS11 done")
    kosdaq = get_market_status('KQ11', session)
    print("get_market_status KQ11 done")
    
    # 2. Get the latest date in DB
    latest_date_result = None
    try:
        print("Querying latest date")
        latest_date_result = session.exec(
            select(KrxDailyStockIndicator.date).order_by(KrxDailyStockIndicator.date.desc()).limit(1)
        ).first()
    except Exception as e:
        print(f"Database query failed: {e}")
    
    kospi_top_stock = None
    kosdaq_top_stock = None
    
    if latest_date_result:
        # KOSPI TOP 5 RS
        kospi_rs_top5_list = []
        statement = (
            select(KrxDailyStock, KrxDailyStockIndicator)
            .join(KrxDailyStockIndicator, (KrxDailyStock.code == KrxDailyStockIndicator.code) & (KrxDailyStock.date == KrxDailyStockIndicator.date))
            .where(KrxDailyStockIndicator.date == latest_date_result)
            .where(KrxDailyStock.market == 'KOSPI')
            .where(KrxDailyStock.marcap >= 200_000_000_000)
            .where(~KrxDailyStock.name.like('%스팩%'))
            .where(~KrxDailyStock.code.regexp_match(r'.*[579KLMNO]$'))
            .order_by(
                KrxDailyStockIndicator.rs.desc(),
                KrxDailyStockIndicator.rs_1m.desc(),
                KrxDailyStockIndicator.rs_3m.desc(),
                KrxDailyStockIndicator.rs_6m.desc(),
                KrxDailyStockIndicator.rs_12m.desc()
            )
            .limit(5)
        )
        kospi_rs_top5 = session.exec(statement).all()
        if kospi_rs_top5:
            # find max by changes_ratio
            best_kospi = max(kospi_rs_top5, key=lambda x: x[0].changes_ratio)
            for row in kospi_rs_top5:
                kospi_rs_top5_list.append({
                    "name": row[0].name,
                    "code": row[0].code,
                    "close": row[0].close,
                    "changes_ratio": row[0].changes_ratio,
                    "marcap_formatted": format_market_cap(row[0].marcap),
                    "amount_formatted": format_market_cap(row[0].amount),
                    "rs": row[1].rs,
                    "is_top_gainer": row == best_kospi
                })
            
        # KOSDAQ TOP 5 RS
        kosdaq_rs_top5_list = []
        statement_kq = (
            select(KrxDailyStock, KrxDailyStockIndicator)
            .join(KrxDailyStockIndicator, (KrxDailyStock.code == KrxDailyStockIndicator.code) & (KrxDailyStock.date == KrxDailyStockIndicator.date))
            .where(KrxDailyStockIndicator.date == latest_date_result)
            .where(KrxDailyStock.market.like('%KOSDAQ%'))
            .where(KrxDailyStock.marcap >= 200_000_000_000)
            .where(~KrxDailyStock.name.like('%스팩%'))
            .where(~KrxDailyStock.code.regexp_match(r'.*[579KLMNO]$'))
            .order_by(
                KrxDailyStockIndicator.rs.desc(),
                KrxDailyStockIndicator.rs_1m.desc(),
                KrxDailyStockIndicator.rs_3m.desc(),
                KrxDailyStockIndicator.rs_6m.desc(),
                KrxDailyStockIndicator.rs_12m.desc()
            )
            .limit(5)
        )
        kosdaq_rs_top5 = session.exec(statement_kq).all()
        if kosdaq_rs_top5:
            best_kosdaq = max(kosdaq_rs_top5, key=lambda x: x[0].changes_ratio)
            for row in kosdaq_rs_top5:
                kosdaq_rs_top5_list.append({
                    "name": row[0].name,
                    "code": row[0].code,
                    "close": row[0].close,
                    "changes_ratio": row[0].changes_ratio,
                    "marcap_formatted": format_market_cap(row[0].marcap),
                    "amount_formatted": format_market_cap(row[0].amount),
                    "rs": row[1].rs,
                    "is_top_gainer": row == best_kosdaq
                })

    if not latest_date_result:
        latest_date_result = "2026-06-28 (Mock Data)"
        kospi_rs_top5_list = [
            {"name": "삼성전자", "code": "005930", "close": 84500, "changes_ratio": 2.5, "marcap_formatted": "500조", "amount_formatted": "1.5조", "rs": 98.5, "is_top_gainer": False},
            {"name": "SK하이닉스", "code": "000660", "close": 235000, "changes_ratio": 5.2, "marcap_formatted": "120조", "amount_formatted": "2.1조", "rs": 97.2, "is_top_gainer": True},
            {"name": "현대차", "code": "005380", "close": 285000, "changes_ratio": -1.2, "marcap_formatted": "50조", "amount_formatted": "3000억", "rs": 95.1, "is_top_gainer": False},
            {"name": "NAVER", "code": "035420", "close": 172000, "changes_ratio": 0.5, "marcap_formatted": "30조", "amount_formatted": "1500억", "rs": 93.4, "is_top_gainer": False},
            {"name": "카카오", "code": "035720", "close": 42000, "changes_ratio": -0.8, "marcap_formatted": "25조", "amount_formatted": "1200억", "rs": 92.0, "is_top_gainer": False},
        ]
        kosdaq_rs_top5_list = [
            {"name": "에코프로비엠", "code": "247540", "close": 195000, "changes_ratio": 8.5, "marcap_formatted": "30조", "amount_formatted": "8000억", "rs": 99.1, "is_top_gainer": True},
            {"name": "에코프로", "code": "086520", "close": 95000, "changes_ratio": 4.2, "marcap_formatted": "25조", "amount_formatted": "5000억", "rs": 98.4, "is_top_gainer": False},
            {"name": "셀트리온헬스케어", "code": "091990", "close": 68000, "changes_ratio": -2.1, "marcap_formatted": "15조", "amount_formatted": "2000억", "rs": 96.5, "is_top_gainer": False},
            {"name": "포스코DX", "code": "022100", "close": 38000, "changes_ratio": 1.5, "marcap_formatted": "10조", "amount_formatted": "3500억", "rs": 95.2, "is_top_gainer": False},
            {"name": "엘앤에프", "code": "066970", "close": 150000, "changes_ratio": -0.5, "marcap_formatted": "8조", "amount_formatted": "1000억", "rs": 94.8, "is_top_gainer": False},
        ]

    return templates.TemplateResponse(
        request, 
        "partials/market_status.html", 
        {
            "kospi": kospi, 
            "kosdaq": kosdaq,
            "kospi_rs_top5": kospi_rs_top5_list if 'kospi_rs_top5_list' in locals() else [],
            "kosdaq_rs_top5": kosdaq_rs_top5_list if 'kosdaq_rs_top5_list' in locals() else [],
            "latest_date": latest_date_result
        }
    )
