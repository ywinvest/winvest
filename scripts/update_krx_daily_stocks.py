import os
import sys
import time
import argparse
import pandas as pd
from datetime import datetime
import concurrent.futures
import threading
from functools import partial

# Add root project path to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlmodel import Session
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from db import engine
from models import KrxDailyStock, KrxDailyAdjustedStock
import FinanceDataReader as fdr

db_semaphore = threading.Semaphore(10)

def chunked_iterable(iterable, size):
    """Yield successive chunks from iterable."""
    for i in range(0, len(iterable), size):
        yield iterable[i:i + size]

def fetch_and_insert_adjusted_ticker(ticker, target_date_str):
    """Worker function for adjusted stocks"""
    try:
        df = fdr.DataReader(ticker, target_date_str, target_date_str)
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

def update_daily_stock(target_date_str=None):
    start_time = time.time()
    
    print("=" * 60)
    print("🚀 Starting Daily Stock Data Update (Phase 1: Raw, Phase 2: Adjusted)")
    print("=" * 60)
    
    t1 = time.time()
    today_str = datetime.today().strftime('%Y%m%d')
    
    if target_date_str:
        dt = datetime.strptime(target_date_str, '%Y%m%d')
        target_str = dt.strftime('%Y%m%d')
    else:
        dt = datetime.today()
        target_str = today_str
        
    latest_trading_date = dt.strftime('%Y-%m-%d')
    
    if target_str != today_str:
        print(f"⚠️ Target date ({latest_trading_date}) is not today.")
        print("Historical data updates should be done via load_krx_daily_stocks.py and load_krx_daily_adjusted_stocks.py.")
        print("Skipping daily update.")
        return
        
    print(f"1. Fetching today's data ({latest_trading_date}) via FDR StockListing...")
    df = fdr.StockListing('KRX')
    print(f"  -> Fetching KRX listing took {time.time() - t1:.2f} seconds.")
    
    # 필수 컬럼 리네임 (ChagesRatio 오타 주의)
    df.rename(columns={
        'Code': 'code', 'Name': 'name', 'Market': 'market',
        'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close',
        'Volume': 'volume', 'Amount': 'amount', 'Changes': 'changes',
        'ChagesRatio': 'changes_ratio', 'Marcap': 'marcap', 'Stocks': 'stocks'
    }, inplace=True)
    
    df = df.dropna(subset=['close', 'marcap'])
    df = df[df['close'] > 0]
    
    df['date'] = latest_trading_date
    df['rank'] = df['marcap'].rank(method='min', ascending=False).astype(int)
    
    df = df[['date', 'code', 'name', 'market', 'open', 'high', 'low', 'close', 'volume', 'amount', 'changes', 'changes_ratio', 'marcap', 'stocks', 'rank']]
    
    # 2. Delete existing raw data for the date
    print(f"\n2. Deleting any existing raw data for {latest_trading_date} to overwrite...")
    t2 = time.time()
    with Session(engine) as session:
        session.exec(text(f"DELETE FROM krx_daily_stocks WHERE date = '{latest_trading_date}'"))
        session.commit()
    print(f"  -> Deleting took {time.time() - t2:.2f} seconds.")
    
    # 3. Insert raw data
    records = df.to_dict(orient='records')
    print(f"\n3. Inserting {len(records)} raw records for {latest_trading_date} into krx_daily_stocks...")
    
    chunk_size = 100
    total_chunks = (len(records) + chunk_size - 1) // chunk_size
    t3 = time.time()
    for i, chunk in enumerate(chunked_iterable(records, chunk_size)):
        with Session(engine) as session:
            session.exec(pg_insert(KrxDailyStock).values(chunk))
            session.commit()
        if (i + 1) % 10 == 0 or (i + 1) == total_chunks:
            print(f"  -> Inserted raw chunk {i+1} / {total_chunks}")
    print(f"  -> Raw DB insertion took {time.time() - t3:.2f} seconds.")
    
    # 4. Phase 2: Adjusted Stocks
    active_tickers = df['code'].tolist()
    print(f"\n4. Fetching Adjusted Stock data for {len(active_tickers)} tickers on {latest_trading_date}...")
    t4 = time.time()
    
    # Delete existing adjusted data for the date
    with Session(engine) as session:
        session.exec(text(f"DELETE FROM krx_daily_adjusted_stocks WHERE date = '{latest_trading_date}'"))
        session.commit()
        
    fetch_func = partial(fetch_and_insert_adjusted_ticker, target_date_str=latest_trading_date)
    total_processed = 0
    completed_tickers = 0
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=30) as executor:
        futures = {executor.submit(fetch_func, ticker): ticker for ticker in active_tickers}
        for future in concurrent.futures.as_completed(futures):
            ticker = futures[future]
            try:
                res_ticker, count = future.result()
                total_processed += count
                completed_tickers += 1
                if completed_tickers % 500 == 0 or completed_tickers == len(active_tickers):
                    print(f"  -> Processed {completed_tickers}/{len(active_tickers)} tickers...")
            except Exception as e:
                print(f"Error processing {ticker}: {e}")

    print(f"  -> Adjusted DB insertion took {time.time() - t4:.2f} seconds.")
    
    elapsed = time.time() - start_time
    print(f"\n🎉 Daily Stock Update (Raw + Adjusted) Completed in ⏱️ {elapsed:.2f} seconds!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Update KRX Daily Stock (Raw + Adjusted)")
    parser.add_argument("--date", type=str, help="Target date in YYYYMMDD format. Leave empty for today.")
    args = parser.parse_args()
    
    sys.stdout.reconfigure(line_buffering=True)
    update_daily_stock(args.date)
