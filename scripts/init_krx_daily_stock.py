import os
import sys
import pandas as pd
import argparse
from datetime import datetime

# Add root project path to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
from sqlmodel import Session
from sqlalchemy.dialects.sqlite import insert
from db import engine
from models import KrxDailyStock

def chunked_iterable(iterable, size):
    """Yield successive chunks from iterable."""
    for i in range(0, len(iterable), size):
        yield iterable[i:i + size]

def init_marcap(target_year=None):
    start_time = time.time()
    
    if target_year:
        years = [target_year]
    else:
        years = [datetime.today().year]
        
    print("=" * 60)
    print(f"🚀 Starting Marcap Initial Data Load ({years}) - Optimized")
    print("=" * 60)

    for year in years:
        print(f"\n--- Processing Year: {year} ---")
        url = f"https://github.com/FinanceData/marcap/raw/master/data/marcap-{year}.parquet"
        try:
            df = pd.read_parquet(url)
            print(f"Loaded {len(df)} rows for {year} into memory.")
            
            # Date is the index. Let's reset it to make it a column
            df = df.reset_index()
            
            # Format Date
            df['Date'] = df['Date'].dt.strftime('%Y-%m-%d')
            
            # Fill NaN values with 0 for numeric columns
            df = df.fillna(0)
            
            # Select required columns and rename to match model
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
            print(f"Converted to {len(records)} dictionary records.")
            
            # Bulk insert in chunks using SQLAlchemy Core
            # Reduced chunk_size to 1000 to avoid SQLite "too many SQL variables" error with ON CONFLICT
            chunk_size = 1000
            total_chunks = (len(records) + chunk_size - 1) // chunk_size
            print(f"Inserting into Turso DB in {total_chunks} chunks of {chunk_size}...")
            
            for i, chunk in enumerate(chunked_iterable(records, chunk_size)):
                with Session(engine) as session:
                    stmt = insert(KrxDailyStock).values(chunk)
                    stmt = stmt.on_conflict_do_nothing(index_elements=['date', 'code'])
                    session.execute(stmt)
                    session.commit()
                # Print progress every 10 chunks to reduce log spam
                if (i + 1) % 10 == 0 or (i + 1) == total_chunks:
                    print(f"  -> Inserted chunk {i+1} / {total_chunks} for {year}")
                    
            print(f"✅ Year {year} completed successfully.")
            
        except Exception as e:
            print(f"❌ Failed to process {year} data: {e}")

    print("\n🎉 All Marcap Initial Loads Completed Successfully!")
    elapsed = time.time() - start_time
    print(f"\n🎉 Daily Stock Initialization Completed Successfully! (⏱️ {elapsed:.2f} seconds)")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Initialize KRX daily stock data from Marcap.")
    parser.add_argument("--year", type=int, help="Year to initialize (e.g., 2025). Defaults to current year if not provided.")
    args = parser.parse_args()
    
    init_marcap(args.year)
