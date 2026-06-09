import os
import sys
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# Add root project path to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
from sqlmodel import Session, select, func
from sqlalchemy import insert
from db import engine
from models import KrxDailyStock

def chunked_iterable(iterable, size):
    """Yield successive chunks from iterable."""
    for i in range(0, len(iterable), size):
        yield iterable[i:i + size]

import FinanceDataReader as fdr
import krx_auth
from krx_data import get_pykrx_market_listing
from sqlalchemy import text

def update_daily_stock(target_date_str=None):
    start_time = time.time()
    
    print("=" * 60)
    print("🚀 Starting Daily Stock Data Update (via FinanceDataReader / pykrx)")
    print("=" * 60)
    
    t1 = time.time()
    if target_date_str:
        dt = datetime.strptime(target_date_str, '%Y%m%d')
        latest_trading_date = dt.strftime('%Y-%m-%d')
        print(f"1. Using specified trading date: {target_date_str} -> {latest_trading_date}")
    else:
        # 1. 거래일 확인 (가장 확실한 방법: 시총 1위 삼성전자 주가 데이터의 마지막 날짜)
        print("1. Fetching the latest actual trading date...")
        
        # 이달 1일부터 오늘까지 삼성전자(005930) 주가 조회
        today = datetime.today()
        start_of_month = today.replace(day=1).strftime('%Y-%m-%d')
        df_samsung = fdr.DataReader('005930', start=start_of_month)
        
        # 가져온 데이터 중 가장 마지막 날짜가 최신 거래일
        latest_trading_date = df_samsung.index[-1].strftime('%Y-%m-%d')
        print(f"  -> Latest Trading Date: {latest_trading_date}")
        print(f"  -> Date fetching took {time.time() - t1:.2f} seconds.")
    
    # 2. 덮어쓰기 로직 (오늘 날짜 데이터 삭제)
    print(f"\n2. Deleting any existing data for {latest_trading_date} to overwrite with latest snapshot...")
    t2 = time.time()
    with Session(engine) as session:
        session.execute(text(f"DELETE FROM krx_daily_stock WHERE date = '{latest_trading_date}'"))
        session.commit()
    print(f"  -> Deleting took {time.time() - t2:.2f} seconds.")
        
    # 3. 최신 전 종목 주가 가져오기
    print("\n3. Fetching latest KRX stock listing...")
    t3 = time.time()
    # df = fdr.StockListing('KRX')
    krx_auth.login_krx(os.getenv('KRX_ID'), os.getenv('KRX_PW'))
    df_kospi = get_pykrx_market_listing('KOSPI', latest_trading_date)
    df_kosdaq = get_pykrx_market_listing('KOSDAQ', latest_trading_date)
    df = pd.concat([df_kospi, df_kosdaq], ignore_index=True)
    print(f"  -> Fetching KRX listing for {latest_trading_date} took {time.time() - t3:.2f} seconds.")
    
    # 필수 컬럼 리네임 (ChagesRatio 오타 주의)
    df.rename(columns={
        'Code': 'code', 'Name': 'name', 'Market': 'market',
        'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close',
        'Volume': 'volume', 'Amount': 'amount', 'Changes': 'changes',
        'ChagesRatio': 'changes_ratio', 'Marcap': 'marcap', 'Stocks': 'stocks'
    }, inplace=True)
    
    # 유효한 주식만 필터링 (종가, 시총 0 이상)
    df = df.dropna(subset=['close', 'marcap'])
    df = df[df['close'] > 0]
    
    # 날짜와 시총 순위 컬럼 추가
    df['date'] = latest_trading_date
    df['rank'] = df['marcap'].rank(method='min', ascending=False).astype(int)
    
    df_db = df[['date', 'code', 'name', 'market', 'open', 'high', 'low', 'close', 'volume', 'amount', 'changes', 'changes_ratio', 'marcap', 'stocks', 'rank']].copy()
    
    # 4. DB에 적재
    print(f"\n4. Inserting {len(df_db)} records for {latest_trading_date} into database...")
    records = df_db.to_dict(orient='records')
    
    chunk_size = 100
    total_chunks = (len(records) + chunk_size - 1) // chunk_size
    
    try:
        t4 = time.time()
        for i, chunk in enumerate(chunked_iterable(records, chunk_size)):
            with Session(engine) as session:
                session.execute(insert(KrxDailyStock).values(chunk))
                session.commit()
            if (i + 1) % 10 == 0 or (i + 1) == total_chunks:
                print(f"  -> Inserted chunk {i+1} / {total_chunks}")
        print(f"  -> Database insertion took {time.time() - t4:.2f} seconds.")
                
        print("\n🎉 Daily Stock Update Completed Successfully!")
        elapsed = time.time() - start_time
        print(f"⏱️ Total time taken: {elapsed:.2f} seconds")
        
    except Exception as e:
        print(f"❌ Failed to process data: {e}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Update KRX Daily Stock")
    parser.add_argument("--date", type=str, help="Target date in YYYYMMDD format. Leave empty for auto-detect.")
    args = parser.parse_args()
    
    update_daily_stock(args.date)
