import os
import sys
import time
from datetime import datetime, timedelta
import argparse
import FinanceDataReader as fdr

# Add root project path to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlmodel import Session, select
from db import engine
from models import KrxDailyStock
from scripts.init_krx_daily_stocks import init_marcap

def get_trading_days(limit=2):
    """최근 2영업일의 날짜를 DB에서 가져옵니다."""
    with Session(engine) as session:
        statement = select(KrxDailyStock.date).distinct().order_by(KrxDailyStock.date.desc()).limit(limit)
        dates = session.exec(statement).all()
        return dates

def find_tickers_with_stock_changes(today_date, yesterday_date):
    """전일 대비 상장주식수(stocks)가 변동된 종목을 찾습니다."""
    with Session(engine) as session:
        stmt_today = select(KrxDailyStock.code, KrxDailyStock.stocks).where(KrxDailyStock.date == today_date)
        today_data = {code: stocks for code, stocks in session.exec(stmt_today).all()}
        
        stmt_yesterday = select(KrxDailyStock.code, KrxDailyStock.stocks).where(KrxDailyStock.date == yesterday_date)
        yesterday_data = {code: stocks for code, stocks in session.exec(stmt_yesterday).all()}
        
        changed_tickers = []
        for code, stocks_today in today_data.items():
            if code in yesterday_data:
                stocks_yesterday = yesterday_data[code]
                if stocks_today != stocks_yesterday:
                    changed_tickers.append(code)
                    
        return changed_tickers

def sync_daily():
    print("=" * 60)
    print(f"🔄 Starting Daily Sync & Adjusted Price Check")
    print("=" * 60)
    
    print("\n[Step 1] Syncing marcap raw prices...")
    init_marcap(datetime.today().year)
    
    trading_dates = get_trading_days(2)
    if len(trading_dates) < 2:
        print("Not enough trading days in DB to compare stock changes. Exiting.")
        return
        
    today_date = trading_dates[0]
    yesterday_date = trading_dates[1]
    print(f"\n[Step 2] Comparing stocks between {yesterday_date} and {today_date}...")
    
    changed_tickers = find_tickers_with_stock_changes(today_date, yesterday_date)
    
    if not changed_tickers:
        print("✅ No corporate actions (stock splits, etc.) detected today.")
    else:
        print(f"⚠️ Detected {len(changed_tickers)} tickers with stock changes: {changed_tickers}")
        
        start_date = (datetime.strptime(today_date, "%Y-%m-%d") - timedelta(days=730)).strftime("%Y-%m-%d")
        
        with Session(engine) as session:
            for ticker in changed_tickers:
                print(f"  -> Backfilling adjusted prices for {ticker} via FDR...")
                try:
                    df = fdr.DataReader(ticker, start_date, today_date)
                    if df is not None and not df.empty:
                        df = df.reset_index()
                        df['Date'] = df['Date'].dt.strftime('%Y-%m-%d')
                        updates = [{"date": row['Date'], "code": ticker, "adj_open": int(row['Open']), "adj_high": int(row['High']), "adj_low": int(row['Low']), "adj_close": int(row['Close'])} for _, row in df.iterrows()]
                        if updates:
                            session.bulk_update_mappings(KrxDailyStock, updates)
                            session.commit()
                except Exception as e:
                    print(f"❌ Failed to backfill {ticker}: {e}")
                    session.rollback()
            
    print("\n🎉 Daily Sync Completed Successfully!")

if __name__ == "__main__":
    sync_daily()
