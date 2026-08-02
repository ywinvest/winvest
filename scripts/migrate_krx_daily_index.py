import os
import sys
import pandas as pd
import FinanceDataReader as fdr
import argparse
from datetime import datetime
import time

# Ensure parent directory is in sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlmodel import Session
from sqlalchemy.dialects.postgresql import insert
from db import engine
from models import KrxDailyIndex, KrxDailyIndexIndicator
import market

# SIGNAL_MAP is removed as it's now handled by the presentation layer

def chunked_iterable(iterable, size):
    """Yield successive chunks from iterable."""
    for i in range(0, len(iterable), size):
        yield iterable[i:i + size]

def migrate_market_data(start_year: int, end_year: int):
    start_date = f"{start_year}-01-01"
    end_date = f"{end_year}-12-31"
    
    market_codes = {"KS11": "KOSPI", "KQ11": "KOSDAQ"}
    
    start_time = time.time()
    
    for code, market_name in market_codes.items():
        print(f"\n--- Migrating {market_name} ({code}) from {start_date} to {end_date} ---")
        try:
            df = fdr.DataReader(code, start_date, end_date)
            if df.empty:
                print(f"No data for {market_name}")
                continue
                
            print(f"Loaded {len(df)} rows from FDR.")
            
            # Calculate indicators (drops NA values caused by MA/RSI windows)
            df = market.add_indicators(df)
            df = df.dropna()
            
            print(f"Calculated indicators. {len(df)} rows remaining after dropna.")
            
            # Convert to dictionary records
            df = df.reset_index()
            df['Date'] = df['Date'].dt.strftime('%Y-%m-%d')
            
            market_records = []
            indicator_records = []
            
            for index, row in df.iterrows():
                market_records.append({
                    "date": row['Date'],
                    "market": code,
                    "open": float(row['Open']),
                    "high": float(row['High']),
                    "low": float(row['Low']),
                    "close": float(row['Close']),
                    "volume": int(row['Volume']),
                    "change": float(row.get('Change', 0.0))
                })
                
                indicator_records.append({
                    "date": row['Date'],
                    "market": code,
                    "ma5": float(row['MA5']),
                    "ma20": float(row['MA20']),
                    "ma60": float(row['MA60']),
                    "ma120": float(row['MA120']),
                    "rsi": float(row['RSI']),
                    "adx": float(row['ADX']),
                    "di": bool(row['DI'])
                })
                
            chunk_size = 4000
            
            with Session(engine) as session:
                # Insert KrxDailyIndex
                print(f"Inserting {len(market_records)} records into KrxDailyIndex...")
                for i, chunk in enumerate(chunked_iterable(market_records, chunk_size)):
                    stmt = insert(KrxDailyIndex).values(chunk)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=['date', 'market'],
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
                
                # Insert KrxDailyIndexIndicator
                print(f"Inserting {len(indicator_records)} records into KrxDailyIndexIndicator...")
                for i, chunk in enumerate(chunked_iterable(indicator_records, chunk_size)):
                    stmt = insert(KrxDailyIndexIndicator).values(chunk)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=['date', 'market'],
                        set_={
                            'ma5': stmt.excluded.ma5,
                            'ma20': stmt.excluded.ma20,
                            'ma60': stmt.excluded.ma60,
                            'ma120': stmt.excluded.ma120,
                            'rsi': stmt.excluded.rsi,
                            'adx': stmt.excluded.adx,
                            'di': stmt.excluded.di,
                        }
                    )
                    session.exec(stmt)
                session.commit()
                
            print(f"✅ Successfully migrated {market_name}")
            
        except Exception as e:
            print(f"❌ Failed to process {market_name}: {e}")
            import traceback
            traceback.print_exc()

    elapsed = time.time() - start_time
    print(f"\n🎉 Market Migration Completed Successfully! (⏱️ {elapsed:.2f} seconds)")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate KRX daily market index data (KOSPI/KOSDAQ).")
    parser.add_argument("--start-year", type=int, default=2015, help="Start year to load.")
    parser.add_argument("--end-year", type=int, default=datetime.today().year, help="End year to load.")
    args = parser.parse_args()
    
    sys.stdout.reconfigure(line_buffering=True)
    migrate_market_data(args.start_year, args.end_year)
