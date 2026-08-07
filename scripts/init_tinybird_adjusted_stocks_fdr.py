import os
import sys
import time
import requests
import argparse
import concurrent.futures
import pandas as pd
from io import StringIO
import FinanceDataReader as fdr
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

TINYBIRD_TOKEN = os.getenv("TINYBIRD_TOKEN")
TINYBIRD_API_URL = os.getenv("TINYBIRD_API_URL", "https://api.tinybird.co")
DATASOURCE_NAME = "krx_daily_adjusted_stocks"

def get_distinct_tickers_from_tinybird() -> list:
    """Fetch distinct tickers from Tinybird's krx_daily_stocks."""
    print("Fetching distinct tickers from Tinybird (krx_daily_stocks)...")
    headers = {'Authorization': f'Bearer {TINYBIRD_TOKEN}'}
    query = "SELECT DISTINCT code FROM krx_daily_stocks WHERE market != 'KONEX'"
    response = requests.get(
        f"{TINYBIRD_API_URL}/v0/sql",
        headers=headers,
        params={'q': query}
    )
    if response.status_code == 200:
        data = response.json()
        tickers = [row['code'] for row in data.get('data', [])]
        print(f"Found {len(tickers)} distinct tickers.")
        return tickers
    else:
        print(f"Failed to fetch tickers: {response.text}")
        return []

def fetch_ticker_data(ticker: str, start_date: str) -> pd.DataFrame:
    try:
        df = fdr.DataReader(ticker, start_date)
        if df is None or df.empty:
            return None
            
        df = df.reset_index()
        df['Date'] = df['Date'].dt.strftime('%Y-%m-%d')
        df['code'] = ticker
        
        df_db = df[['Date', 'code', 'Open', 'High', 'Low', 'Close', 'Volume', 'Change']].copy()
        df_db.rename(columns={
            'Date': 'date',
            'Open': 'open',
            'High': 'high',
            'Low': 'low',
            'Close': 'close',
            'Volume': 'volume',
            'Change': 'change'
        }, inplace=True)
        
        return df_db
    except Exception as e:
        print(f"Error fetching {ticker}: {e}")
        return None

def push_to_tinybird_batch(df_batch: pd.DataFrame):
    if df_batch.empty:
        return 0
        
    csv_buffer = StringIO()
    df_batch.to_csv(csv_buffer, index=False)
    
    headers = {'Authorization': f'Bearer {TINYBIRD_TOKEN}'}
    params = {'name': DATASOURCE_NAME, 'mode': 'append', 'format': 'csv'}
    
    for attempt in range(3):
        try:
            res = requests.post(
                f"{TINYBIRD_API_URL}/v0/datasources",
                headers=headers,
                params=params,
                files={'csv': csv_buffer.getvalue().encode('utf-8')}
            )
            if res.status_code >= 200 and res.status_code < 300:
                return len(df_batch)
            else:
                print(f"Tinybird push error: {res.text}")
                time.sleep(2)
        except Exception as e:
            print(f"Request error: {e}")
            time.sleep(2)
    return 0

def run_load_adjusted(start_date: str, target_ticker: str = None):
    start_time = time.time()
    print("=" * 60)
    print(f"🚀 Starting FDR Adjusted Data Load to Tinybird (From {start_date})")
    print("=" * 60)
    
    if target_ticker:
        active_tickers = [target_ticker]
    else:
        active_tickers = get_distinct_tickers_from_tinybird()
        
    if not active_tickers:
        print("No tickers to process.")
        return

    total_processed = 0
    completed_tickers = 0
    
    batch_dfs = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(fetch_ticker_data, ticker, start_date): ticker for ticker in active_tickers}
        
        for future in concurrent.futures.as_completed(futures):
            ticker = futures[future]
            try:
                df = future.result()
                if df is not None and not df.empty:
                    batch_dfs.append(df)
                
                completed_tickers += 1
                
                # Push in batches of 50 tickers to avoid massive memory usage and tinybird rate limits
                if len(batch_dfs) >= 50 or completed_tickers == len(active_tickers):
                    if batch_dfs:
                        combined_df = pd.concat(batch_dfs, ignore_index=True)
                        pushed_count = push_to_tinybird_batch(combined_df)
                        total_processed += pushed_count
                        batch_dfs = []
                        
                if completed_tickers % 100 == 0:
                    print(f"Processed {completed_tickers}/{len(active_tickers)} tickers... (Pushed {total_processed} rows)")
            except Exception as e:
                print(f"Error processing {ticker}: {e}")

    elapsed = time.time() - start_time
    print("=" * 60)
    print(f"🎉 FDR Adjusted Data Ingestion to Tinybird Completed! (⏱️ Total time: {elapsed:.2f} seconds)")
    print(f"Total rows pushed: {total_processed}")
    print("=" * 60)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=str, default="2025-01-01")
    parser.add_argument("--ticker", type=str, default=None)
    args = parser.parse_args()
    
    sys.stdout.reconfigure(line_buffering=True)
    run_load_adjusted(args.start, args.ticker)
