import os
import sys
import time
import argparse
import pandas as pd
from datetime import datetime

# Add root project path to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlmodel import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert
from db import engine
from models import KrxDailyStock
import FinanceDataReader as fdr

def chunked_iterable(iterable, size):
    """Yield successive chunks from iterable."""
    for i in range(0, len(iterable), size):
        yield iterable[i:i + size]

def update_daily_stock(target_date_str=None):
    start_time = time.time()
    
    print("=" * 60)
    print("🚀 Starting Daily Stock Data Update (Raw Marcap Data)")
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
    
    # if target_str != today_str:
    #     print(f"⚠️ Target date ({latest_trading_date}) is not today.")
    #     print("Historical data updates should be done via migrate_krx_daily_stocks.py.")
    #     print("Skipping daily update.")
    #     return
        
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
    
    records = df.to_dict(orient='records')
    print(f"\n2. Inserting {len(records)} raw records for {latest_trading_date} into krx_daily_stocks...")
    
    chunk_size = 100
    total_chunks = (len(records) + chunk_size - 1) // chunk_size
    t3 = time.time()
    for i, chunk in enumerate(chunked_iterable(records, chunk_size)):
        with Session(engine) as session:
            stmt = pg_insert(KrxDailyStock).values(chunk)
            stmt = stmt.on_conflict_do_nothing(index_elements=['date', 'code'])
            session.exec(stmt)
            session.commit()
        if (i + 1) % 10 == 0 or (i + 1) == total_chunks:
            print(f"  -> Inserted raw chunk {i+1} / {total_chunks}")
    print(f"  -> Raw DB insertion took {time.time() - t3:.2f} seconds.")
    
    elapsed = time.time() - start_time
    print(f"\n🎉 Daily Stock Update (Raw) Completed in ⏱️ {elapsed:.2f} seconds!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Update KRX Daily Stock (Raw)")
    parser.add_argument("--date", type=str, help="Target date in YYYYMMDD format. Leave empty for today.")
    args = parser.parse_args()
    
    sys.stdout.reconfigure(line_buffering=True)
    update_daily_stock(args.date)
