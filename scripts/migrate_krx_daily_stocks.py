import os
import sys
import pandas as pd
import argparse
from datetime import datetime

# Add root project path to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
from sqlmodel import Session
from sqlalchemy.dialects.postgresql import insert
from db import engine
from models import KrxDailyStock

def chunked_iterable(iterable, size):
    """Yield successive chunks from iterable."""
    for i in range(0, len(iterable), size):
        yield iterable[i:i + size]

def load_to_supabase(start_year: int, end_year: int):
    start_time = time.time()
    
    years = list(range(start_year, end_year + 1))
    
    # 2025, 2026년을 최우선으로 처리하도록 재배열
    priority_years = [2025, 2026]
    years = [y for y in priority_years if y in years] + [y for y in years if y not in priority_years]
        
    print("=" * 60)
    print(f"🚀 Starting Marcap Data Load to Supabase (PostgreSQL) ({years})")
    print("=" * 60)

    for year in years:
        year_start_time = time.time()
        print(f"\n--- Processing Year: {year} ---")
        url = f"https://github.com/FinanceData/marcap/raw/master/data/marcap-{year}.parquet"
        try:
            df = pd.read_parquet(url)
            print(f"Loaded {len(df)} rows for {year} into memory.")
            
            df = df.reset_index()
            df['Date'] = df['Date'].dt.strftime('%Y-%m-%d')
            
            df = df.fillna(0)
            
            df_db = df[['Date', 'Code', 'Name', 'Market', 'Open', 'High', 'Low', 'Close', 'Volume', 'Amount', 'Changes', 'ChangesRatio', 'Marcap', 'Stocks', 'Rank']].copy()
            df_db.rename(columns={
                'Date': 'date',
                'Code': 'code',
                'Name': 'name',
                'Market': 'market',
                'Open': 'open',
                'High': 'high',
                'Low': 'low',
                'Close': 'close',
                'Volume': 'volume',
                'Amount': 'amount',
                'Changes': 'changes',
                'ChangesRatio': 'changes_ratio',
                'Marcap': 'marcap',
                'Stocks': 'stocks',
                'Rank': 'rank'
            }, inplace=True)
            
            records = df_db.to_dict(orient='records')
            if not records:
                print(f"No records to insert for {year}.")
                continue
                
            print(f"Converted to {len(records)} dictionary records.")
            
            # PostgreSQL has a hard limit of 65,535 parameters per query.
            # With 15 columns, 65535 / 15 = 4369 max rows per chunk.
            # We set chunk size to 4,000 for maximum safe throughput.
            chunk_size = 4000
            total_chunks = (len(records) + chunk_size - 1) // chunk_size
            print(f"Inserting into Supabase in {total_chunks} chunks of {chunk_size}...")
            
            with Session(engine) as session:
                for i, chunk in enumerate(chunked_iterable(records, chunk_size)):
                    stmt = insert(KrxDailyStock).values(chunk)
                    stmt = stmt.on_conflict_do_nothing(index_elements=['date', 'code'])
                    session.exec(stmt)
                    session.commit()
                    if (i + 1) % 5 == 0 or (i + 1) == total_chunks:
                        print(f"  -> Inserted chunk {i+1} / {total_chunks} for {year}")
                    
            year_elapsed = time.time() - year_start_time
            print(f"✅ Year {year} completed successfully. (⏱️ {year_elapsed:.2f} seconds)")
            
        except Exception as e:
            print(f"❌ Failed to process {year} data: {e}")

    print("\n🎉 All Supabase Loads Completed Successfully!")
    elapsed = time.time() - start_time
    print(f"\n🎉 Daily Stock Supabase Ingestion Completed Successfully! (⏱️ {elapsed:.2f} seconds)")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load KRX daily stock data into Supabase (PostgreSQL).")
    # 기본값은 2015부터 현재까지
    parser.add_argument("--start-year", type=int, default=2015, help="Start year to load.")
    parser.add_argument("--end-year", type=int, default=datetime.today().year, help="End year to load.")
    args = parser.parse_args()
    
    # Check if we are actually pointing to PostgreSQL
    from db import engine
    if engine.url.drivername != "postgresql+psycopg2" and "postgresql" not in engine.url.drivername:
        print("⚠️ WARNING: Your DATABASE_URL does not appear to be a PostgreSQL connection string.")
        print(f"Current DB dialect: {engine.url.drivername}")
        print("Please set your DATABASE_URL in .env to your Supabase connection string before running.")
        print("Example: DATABASE_URL=postgresql://postgres:[PASSWORD]@[HOST]:5432/postgres")
        
    # Unbuffered stdout for real-time logging
    sys.stdout.reconfigure(line_buffering=True)
    load_to_supabase(args.start_year, args.end_year)
