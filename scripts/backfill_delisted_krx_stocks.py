import os
import sys
import argparse
from datetime import datetime, timedelta
import pandas as pd
import FinanceDataReader as fdr

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
from sqlmodel import Session, select
from db import engine
from models import KrxDailyStock

def backfill_delisted_stocks(start_date: str, end_date: str):
    print("=" * 60)
    print(f"🚀 Starting Backfill for DELISTED Stocks via FDR ({start_date} ~ {end_date})")
    print("=" * 60)
    
    start_time = time.time()
    
    try:
        df_listing = fdr.StockListing('KRX')
        active_tickers = set(df_listing['Code'].tolist())
    except Exception as e:
        print(f"Failed to get active tickers from FDR: {e}")
        return
        
    with Session(engine) as session:
        statement = select(KrxDailyStock.code).distinct()
        all_db_tickers = set(session.exec(statement).all())
        
    delisted_tickers = list(all_db_tickers - active_tickers)
    
    print(f"Found {len(all_db_tickers)} total tickers in DB.")
    print(f"Found {len(active_tickers)} active tickers.")
    print(f"Identified {len(delisted_tickers)} DELISTED tickers.")
    
    total_processed = 0
    with Session(engine) as session:
        for idx, ticker in enumerate(delisted_tickers, 1):
            try:
                df = fdr.DataReader(ticker, start_date, end_date)
                
                if df is None or df.empty:
                    continue
                    
                df = df.reset_index()
                df['Date'] = df['Date'].dt.strftime('%Y-%m-%d')
                
                updates = []
                for _, row in df.iterrows():
                    updates.append({
                        "date": row['Date'],
                        "code": ticker,
                        "adj_open": int(row['Open']),
                        "adj_high": int(row['High']),
                        "adj_low": int(row['Low']),
                        "adj_close": int(row['Close'])
                    })
                
                if updates:
                    session.bulk_update_mappings(KrxDailyStock, updates)
                    session.commit()
                    total_processed += len(updates)
                
                if idx % 10 == 0:
                    print(f"Processed {idx}/{len(delisted_tickers)} tickers... (Total updated rows: {total_processed})")
                    
            except Exception as e:
                # 상폐 종목은 데이터가 없는 경우가 많으므로 조용히 넘어갑니다.
                session.rollback()
                
    elapsed = time.time() - start_time
    print(f"\n🎉 Delisted Stocks Backfill Completed! Updated {total_processed} rows in ⏱️ {elapsed:.2f} seconds.")

if __name__ == "__main__":
    from constants import PRICE_LIMIT_EXPANSION_DATE
    parser = argparse.ArgumentParser()
    # 2015-06-15: 상하한가 30% 확대 시행일
    parser.add_argument("--start", type=str, default=PRICE_LIMIT_EXPANSION_DATE)
    parser.add_argument("--end", type=str, default=datetime.today().strftime('%Y-%m-%d'))
    args = parser.parse_args()
    backfill_delisted_stocks(args.start, args.end)
