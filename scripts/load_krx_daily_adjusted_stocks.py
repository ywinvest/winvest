import os
import sys
import time
import argparse
import concurrent.futures
from functools import partial
from sqlmodel import Session, select
from sqlalchemy import text
import FinanceDataReader as fdr

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import threading
from db import engine
from models import KrxDailyAdjustedStock
from sqlalchemy.dialects.postgresql import insert as pg_insert

# Supabase session connection pooler is limited to 15.
# We limit max concurrent DB writes to 10.
db_semaphore = threading.Semaphore(10)

def fetch_and_insert_ticker(ticker, start_date):
    """
    Worker function: Fetches data from FDR and instantly inserts into Supabase.
    This fully utilizes Supabase's concurrent write capabilities without blocking other threads.
    """
    try:
        df = fdr.DataReader(ticker, start_date)
        if df.empty:
            return ticker, 0
            
        updates = []
        for date_obj, row in df.iterrows():
            date_str = date_obj.strftime("%Y-%m-%d")
            updates.append({
                "date": date_str,
                "code": ticker,
                "open": int(row['Open']),
                "high": int(row['High']),
                "low": int(row['Low']),
                "close": int(row['Close']),
                "volume": int(row['Volume']),
                "change": float(row['Change'])
            })
            
        # Insert directly in the worker thread (Parallel Writes!), but capped to 10 concurrent connections
        with db_semaphore:
            with Session(engine) as session:
                chunk_size = 4000
                for i in range(0, len(updates), chunk_size):
                    chunk = updates[i:i+chunk_size]
                    stmt = pg_insert(KrxDailyAdjustedStock).values(chunk)
                    stmt = stmt.on_conflict_do_nothing(index_elements=['date', 'code'])
                    session.exec(stmt)
                session.commit()
            
        return ticker, len(updates)
    except Exception as e:
        print(f"❌ Failed to process ticker {ticker}: {e}")
        return ticker, 0

def run_load_adjusted(start_date: str, target_ticker: str = None):
    start_time = time.time()
    
    if target_ticker:
        active_tickers = [target_ticker]
    else:
        # Get active tickers from FDR
        try:
            df_listing = fdr.StockListing('KRX')
            active_tickers = df_listing['Code'].tolist()
        except Exception as e:
            print(f"Failed to get active tickers from FDR: {e}")
            return

    print(f"Starting parallel adjusted data load for {len(active_tickers)} active stocks from {start_date}...")
    
    fetch_func = partial(fetch_and_insert_ticker, start_date=start_date)
    total_processed = 0
    completed_tickers = 0
    
    # 1. Parallel Fetching & 2. Parallel DB Update (Supabase handles concurrency perfectly)
    with concurrent.futures.ThreadPoolExecutor(max_workers=30) as executor:
        # Map returns results in the order of iterables, but we can process as they complete using submit
        futures = {executor.submit(fetch_func, ticker): ticker for ticker in active_tickers}
        
        for future in concurrent.futures.as_completed(futures):
            ticker = futures[future]
            try:
                res_ticker, count = future.result()
                total_processed += count
                completed_tickers += 1
                
                if completed_tickers % 50 == 0:
                    print(f"Processed {completed_tickers}/{len(active_tickers)} tickers... (Total updated rows: {total_processed})")
            except Exception as e:
                print(f"Error processing {ticker}: {e}")

    elapsed = time.time() - start_time
    print(f"\n🎉 Active Stocks Adjusted Data Load Completed! Inserted/Updated {total_processed} rows in ⏱️ {elapsed:.2f} seconds.")

if __name__ == "__main__":
    from constants import PRICE_LIMIT_EXPANSION_DATE
    parser = argparse.ArgumentParser()
    # 2015-06-15: 상하한가 30% 확대 시행일
    parser.add_argument("--start", type=str, default=PRICE_LIMIT_EXPANSION_DATE)
    parser.add_argument("--ticker", type=str, default=None, help="Specific ticker to load (e.g., '011930')")
    args = parser.parse_args()
    
    # 강제로 Unbuffered 모드로 출력하여 로그 파일에 즉시 쓰이도록 함
    sys.stdout.reconfigure(line_buffering=True)
    
    print("🚀 Starting Adjusted Data Load process (parallel architecture)...")
    run_load_adjusted(args.start, target_ticker=args.ticker)
