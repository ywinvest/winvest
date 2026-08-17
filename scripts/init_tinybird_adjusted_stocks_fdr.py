import os
import sys
import time
import argparse
import socket
import concurrent.futures
import requests

# Patch requests to enforce a global timeout since fdr doesn't expose it
original_get = requests.get
original_post = requests.post

def patched_get(*args, **kwargs):
    kwargs.setdefault('timeout', 10)
    return original_get(*args, **kwargs)

def patched_post(*args, **kwargs):
    kwargs.setdefault('timeout', 10)
    return original_post(*args, **kwargs)

requests.get = patched_get
requests.post = patched_post

from functools import partial
from datetime import datetime

import pandas as pd
import FinanceDataReader as fdr
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import rs
import requests
import numpy as np

load_dotenv()

TINYBIRD_TOKEN = os.getenv("TINYBIRD_TOKEN")
TINYBIRD_API_URL = os.getenv("TINYBIRD_API_URL", "https://api.tinybird.co")
DATASOURCE_NAME = "krx_daily_adjusted_stocks"

def truncate_datasource(datasource_name: str):
    print(f"🧹 Truncating {datasource_name}...")
    headers = {'Authorization': f'Bearer {TINYBIRD_TOKEN}'}
    response = requests.post(
        f"{TINYBIRD_API_URL}/v0/datasources/{datasource_name}/truncate",
        headers=headers
    )
    if response.ok:
        print(f"✅ Successfully truncated {datasource_name}.")
    else:
        print(f"❌ Failed to truncate ({response.status_code}): {response.text}")

def get_distinct_tickers_from_tinybird() -> list:
    """Fetch distinct tickers from Tinybird's krx_daily_stocks."""
    print("Fetching distinct tickers from Tinybird (krx_daily_stocks)...")
    headers = {'Authorization': f'Bearer {TINYBIRD_TOKEN}'}
    query = "SELECT DISTINCT code FROM krx_daily_stocks WHERE market != 'KONEX' FORMAT JSON"
    response = requests.get(
        f"{TINYBIRD_API_URL}/v0/sql",
        headers=headers,
        params={'q': query}
    )
    if response.ok:
        data = response.json()
        tickers = [row['code'] for row in data.get('data', [])]
        print(f"Found {len(tickers)} distinct tickers.")
        return tickers
    else:
        print(f"Failed to fetch tickers: {response.text}")
        return []

def process_stock(row, start_date):
    code = row['Code']
    listing_date = row.get('ListingDate')
    
    df = None
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # Add a small random delay to prevent rate-limiting from Naver Finance
            time.sleep(np.random.uniform(0.1, 0.3))
            df = fdr.DataReader(code, start_date)
            break
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(1)
            else:
                print(f"Error processing {code} after {max_retries} attempts: {e}")
                return None
                
    if df is None or df.empty:
        return None
        
    try:
        if not pd.isna(listing_date):
            df = df[df.index >= listing_date]
            if df.empty:
                return None
        
        df = rs.calculate_indicators(df)
        
        # Add Moving Averages (MA)
        df['MA5'] = df['Close'].rolling(window=5).mean()
        df['MA10'] = df['Close'].rolling(window=10).mean()
        df['MA20'] = df['Close'].rolling(window=20).mean()
        df['MA60'] = df['Close'].rolling(window=60).mean()
        df['MA120'] = df['Close'].rolling(window=120).mean()
        df['MA240'] = df['Close'].rolling(window=240).mean()
        
        df['Code'] = code
        return df
    except Exception as e:
        print(f"Error processing {code} after fetch: {e}")
        return None
def parallel_process_stocks(all_stocks, start_date):
    process_func = partial(process_stock, start_date=start_date)
    results = []
    
    total = len(all_stocks)
    completed = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(process_func, row) for _, row in all_stocks.iterrows()]
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result is not None:
                results.append(result)
                
            completed += 1
            if completed % 100 == 0 or completed == total:
                print(f"Processed {completed}/{total} tickers...")

    return pd.concat(results) if results else pd.DataFrame()

def push_to_tinybird_batch(df_batch: pd.DataFrame):
    if df_batch.empty:
        return 0
        
    csv_data = df_batch.to_csv(index=False, header=True)
    headers = {
        'Authorization': f'Bearer {TINYBIRD_TOKEN}'
    }
    params = {
        'name': DATASOURCE_NAME,
        'mode': 'append',
        'format': 'csv'
    }
    
    # Try up to 3 times to handle 429 Too Many Requests
    for attempt in range(3):
        response = requests.post(
            f"{TINYBIRD_API_URL}/v0/datasources",
            headers=headers,
            params=params,
            files={'csv': csv_data.encode('utf-8')},
            timeout=120
        )
        if response.ok:
            return len(df_batch)
        elif response.status_code == 429:
            print(f"  Rate limited. Retrying after 5 seconds...")
            time.sleep(5)
        else:
            break
            
    print(f"Failed to push batch: {response.text}")
    return 0

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=str, default="2024-01-01", help="Start date (YYYY-MM-DD)")
    args = parser.parse_args()
    
    print("=" * 60)
    print(f"🚀 Starting FDR Adjusted Data Load to Tinybird (From {args.start})")
    print("=" * 60)
    
    truncate_datasource(DATASOURCE_NAME)
    
    # 1. Fetch all stock listings
    active_tickers = get_distinct_tickers_from_tinybird()
    all_stocks = pd.DataFrame({'Code': active_tickers})
    
    # 상장일 정보 가져오기 (from woo2_backtest.py)
    print("Fetching ListingDate info...")
    df_listing = fdr.StockListing('KRX-DESC', args.start)[['Code', 'ListingDate']]
    all_stocks = all_stocks.merge(df_listing, on='Code', how='left')
    
    print(f"Total tickers found: {len(all_stocks)}")
    
    # 2. Parallel fetch prices
    print("Fetching historical price data...")
    combined_df = parallel_process_stocks(all_stocks, args.start)
    
    if combined_df.empty:
        print("No data fetched. Exiting.")
        return
        
    print(f"Data fetched! Total rows: {len(combined_df)}")
    
    # 3. Calculate RS indicators
    print("Calculating RS indicators...")
    # `rs.calculate_relative_strength` expects 'Code' instead of 'code' based on woo2.py
    # It adds 'RS', 'RS_1M', 'RS_3M', 'RS_6M', 'RS_12M' to the dataframe
    rs_calc_df = rs.calculate_relative_strength(combined_df)
    
    # Now reset the index so Date becomes a column
    rs_calc_df = rs_calc_df.reset_index()
    if 'Date' not in rs_calc_df.columns and 'index' in rs_calc_df.columns:
        rs_calc_df = rs_calc_df.rename(columns={'index': 'Date'})
    
    # 4. Format for Tinybird schema
    print("Formatting for Tinybird schema...")
    df_db = rs_calc_df.rename(columns={
        'Date': 'date',
        'Code': 'code',
        'Open': 'open',
        'High': 'high',
        'Low': 'low',
        'Close': 'close',
        'Volume': 'volume',
        'Change': 'change',
        'RS': 'rs',
        'RS_1M': 'rs_1m',
        'RS_3M': 'rs_3m',
        'RS_6M': 'rs_6m',
        'RS_12M': 'rs_12m',
        'MA5': 'ma5',
        'MA10': 'ma10',
        'MA20': 'ma20',
        'MA60': 'ma60',
        'MA120': 'ma120',
        'MA240': 'ma240'
    })
    
    # Fill NAs
    df_db = df_db.fillna(0)
    
    # Cast integers
    int_columns = ['open', 'high', 'low', 'close', 'volume', 'rs', 'rs_1m', 'rs_3m', 'rs_6m', 'rs_12m']
    df_db[int_columns] = df_db[int_columns].astype('int64')
    
    float_columns = ['change', 'ma5', 'ma10', 'ma20', 'ma60', 'ma120', 'ma240']
    df_db[float_columns] = df_db[float_columns].astype('float64')
    
    # Ensure correct column order
    final_cols = ['date', 'code', 'open', 'high', 'low', 'close', 'volume', 'change', 'rs', 'rs_1m', 'rs_3m', 'rs_6m', 'rs_12m', 'ma5', 'ma10', 'ma20', 'ma60', 'ma120', 'ma240']
    df_db = df_db[final_cols]
    
    df_db['date'] = df_db['date'].dt.strftime('%Y-%m-%d')
    
    # 5. Push to Tinybird
    print("Pushing to Tinybird...")
    total_pushed = 0
    batch_size = 500000
    
    for i in range(0, len(df_db), batch_size):
        batch = df_db.iloc[i:i+batch_size]
        pushed = push_to_tinybird_batch(batch)
        total_pushed += pushed
        print(f"  -> Pushed {i+len(batch)} / {len(df_db)} rows...")
        
    print(f"✅ Finished! Successfully loaded {total_pushed} rows into Tinybird.")

if __name__ == "__main__":
    start_time = time.time()
    main()
    print(f"Elapsed time: {time.time() - start_time:.2f} seconds")
