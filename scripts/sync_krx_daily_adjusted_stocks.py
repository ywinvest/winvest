import os
import sys
import time
import argparse
import pandas as pd
from datetime import datetime
import concurrent.futures
import threading
from functools import partial
import socket

# Add root project path to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlmodel import Session
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from db import engine
from models import KrxDailyAdjustedStock
import FinanceDataReader as fdr

db_semaphore = threading.Semaphore(10)

def chunked_iterable(iterable, size):
    """Yield successive chunks from iterable."""
    for i in range(0, len(iterable), size):
        yield iterable[i:i + size]

def resync_ticker_history(ticker):
    """
    Resync full history for a ticker when a capital reduction / split is detected.
    Overwrites past historical adjusted prices in krx_daily_adjusted_stocks.
    """
    try:
        from constants import PRICE_LIMIT_EXPANSION_DATE
        df_hist = fdr.DataReader(ticker, PRICE_LIMIT_EXPANSION_DATE)
        if df_hist.empty:
            return
        updates = []
        for date_obj, row in df_hist.iterrows():
            updates.append({
                "date": date_obj.strftime("%Y-%m-%d"),
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
                    stmt = stmt.on_conflict_do_update(
                        index_elements=['date', 'code'],
                        set_={
                            'open': stmt.excluded.open,
                            'high': stmt.excluded.high,
                            'low': stmt.excluded.low,
                            'close': stmt.excluded.close,
                            'volume': stmt.excluded.volume,
                            'change': stmt.excluded.change,
                        }
                    )
                    session.exec(stmt)
                session.commit()
        print(f"🔄 Smart Resync: Updated historical adjusted prices for {ticker} (Capital Reduction/Split detected)")
    except Exception as e:
        print(f"❌ Failed smart resync for {ticker}: {e}")

def fetch_and_insert_adjusted_ticker(ticker, target_date_str):
    """Worker function for adjusted stocks with smart anomaly detection"""
    max_retries = 3
    df = None
    for attempt in range(max_retries):
        try:
            socket.setdefaulttimeout(10)
            df = fdr.DataReader(ticker, target_date_str, target_date_str)
            break
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2)
            else:
                print(f"❌ Failed to process ticker {ticker}: {e}")
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

    need_resync = False
    if len(updates) > 0:
        today_vol = updates[0]['volume']
        today_close = updates[0]['close']
        today_change = updates[0]['change'] if not pd.isna(updates[0]['change']) else 0.0
        with db_semaphore:
            with Session(engine) as session:
                prev_row = session.exec(
                    text(f"SELECT close FROM krx_daily_adjusted_stocks WHERE code = '{ticker}' AND date < '{target_date_str}' ORDER BY date DESC LIMIT 1")
                ).first()
                if prev_row:
                    prev_close = prev_row[0]
                    expected_close = prev_close * (1.0 + today_change)
                    # Detect 감자/병합/권리락/무상증자/주식분할:
                    if prev_close > 0:
                        if (today_vol == 0 and today_close != prev_close) or (abs(today_close - expected_close) / prev_close > 0.01):
                            need_resync = True

    with db_semaphore:
        with Session(engine) as session:
            chunk_size = 4000
            for i in range(0, len(updates), chunk_size):
                chunk = updates[i:i+chunk_size]
                stmt = pg_insert(KrxDailyAdjustedStock).values(chunk)
                stmt = stmt.on_conflict_do_update(
                    index_elements=['date', 'code'],
                    set_={
                        'open': stmt.excluded.open,
                        'high': stmt.excluded.high,
                        'low': stmt.excluded.low,
                        'close': stmt.excluded.close,
                        'volume': stmt.excluded.volume,
                        'change': stmt.excluded.change,
                    }
                )
                session.exec(stmt)
            session.commit()

    if need_resync:
        resync_ticker_history(ticker)
        
    return ticker, len(updates)

def update_adjusted_stocks(target_date_str=None):
    start_time = time.time()
    
    print("=" * 60)
    print("🚀 Starting Daily Adjusted Stock Data Update & Anomaly Detection")
    print("=" * 60)
    
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
        print("Historical data updates should be done via migrate_krx_daily_adjusted_stocks.py.")
        print("Skipping daily update.")
        return
        
    active_tickers = []
    with Session(engine) as session:
        rows = session.exec(
            text(f"SELECT code FROM krx_daily_stocks WHERE date = '{latest_trading_date}' AND market != 'KONEX'")
        ).all()
        active_tickers = [row[0] for row in rows]
        
    if not active_tickers:
        print(f"❌ No active tickers found in krx_daily_stocks for {latest_trading_date}.")
        print("Please run sync_krx_daily_stocks.py first.")
        return

    print(f"\n1. Fetching Adjusted Stock data for {len(active_tickers)} tickers on {latest_trading_date}...")
    t4 = time.time()
    
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
    print(f"\n🎉 Daily Adjusted Stock Update Completed in ⏱️ {elapsed:.2f} seconds!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Update KRX Daily Adjusted Stock Data")
    parser.add_argument("--date", type=str, help="Target date in YYYYMMDD format. Leave empty for today.")
    args = parser.parse_args()
    
    sys.stdout.reconfigure(line_buffering=True)
    update_adjusted_stocks(args.date)
