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

from psycopg2.extras import execute_values

# Transaction Pooler (6543) is now properly configured.
# Safely utilizing Semaphore(3) for 3x concurrent write throughput.
db_semaphore = threading.Semaphore(3)

import socket

def fetch_and_insert_ticker(ticker, start_date):
    """
    Worker function: Fetches data from FDR and instantly inserts into Supabase.
    This fully utilizes Supabase's concurrent write capabilities without blocking other threads.
    """
    try:
        max_retries = 3
        df = None
        for attempt in range(max_retries):
            try:
                # Set a 10-second global socket timeout to prevent TCP blackholing
                socket.setdefaulttimeout(10)
                df = fdr.DataReader(ticker, start_date)
                break
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"⚠️ Timeout/Error for {ticker} (Attempt {attempt+1}/{max_retries}): {e}. Retrying...")
                    time.sleep(2)
                else:
                    print(f"❌ Failed to fetch ticker {ticker} after {max_retries} attempts: {e}")
                    return ticker, 0
                    
        if df is None or df.empty:
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
            
        # Limit concurrent DB writes to 1 (Sequential) because execute_values is so fast (0.1s)
        # Using Semaphore(1) completely prevents Supabase lock contention and Operation timed out!
        with db_semaphore:
            raw_conn = engine.raw_connection()
            try:
                cursor = raw_conn.cursor()
                # Chunk into 500 rows (4,000 params) per UPSERT to prevent PgBouncer statement buffer overflow
                # which is the true cause of 'SSL SYSCALL error: Operation timed out'.
                chunk_size = 500
                for i in range(0, len(updates), chunk_size):
                    chunk = updates[i:i+chunk_size]
                    tuples = [
                        (r['date'], r['code'], r['open'], r['high'], r['low'], r['close'], r['volume'], r['change'])
                        for r in chunk
                    ]
                    
                    query = """
                        INSERT INTO krx_daily_adjusted_stocks (date, code, open, high, low, close, volume, change)
                        VALUES %s
                        ON CONFLICT (date, code) DO UPDATE SET
                            open = EXCLUDED.open,
                            high = EXCLUDED.high,
                            low = EXCLUDED.low,
                            close = EXCLUDED.close,
                            volume = EXCLUDED.volume,
                            change = EXCLUDED.change
                    """
                    execute_values(cursor, query, tuples)
                raw_conn.commit()
            except Exception as inner_e:
                raw_conn.rollback()
                raise inner_e
            finally:
                raw_conn.close()
            
        return ticker, len(updates)
    except Exception as e:
        print(f"❌ Failed to process ticker {ticker}: {e}")
        return ticker, 0

def run_load_adjusted(start_date: str, target_ticker: str = None):
    start_time = time.time()
    
    if target_ticker:
        active_tickers = [target_ticker]
    else:
        # Get all tickers from DB (including delisted stocks, excluding KONEX)
        try:
            with Session(engine) as session:
                rows = session.exec(
                    text("SELECT DISTINCT code FROM krx_daily_stocks WHERE market != 'KONEX'")
                ).all()
                active_tickers = [row[0] for row in rows]
                
            if not active_tickers:
                raise RuntimeError("No tickers found in krx_daily_stocks DB. Please run init_krx_daily_stocks.py first.")
        except Exception as e:
            print(f"Failed to get tickers from DB: {e}")
            return

    print(f"Starting parallel adjusted data load for {len(active_tickers)} active stocks from {start_date}...")
    
    fetch_func = partial(fetch_and_insert_ticker, start_date=start_date)
    total_processed = 0
    completed_tickers = 0
    
    # 1. Parallel Fetching & 2. Parallel DB Update (Supabase handles concurrency perfectly)
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
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
