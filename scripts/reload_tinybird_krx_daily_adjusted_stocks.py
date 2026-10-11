import os
import sys
import time
import argparse
import socket
import concurrent.futures
import requests

from functools import partial
from datetime import datetime

import pandas as pd
import FinanceDataReader as fdr
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import rs
from http_utils import create_retry_session
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

def get_tickers_with_first_trading_date_from_tinybird(start_date: str) -> pd.DataFrame:
    """Fetch tickers and their first trading date from Tinybird's krx_daily_stocks.

    Returns a DataFrame with columns ['Code', 'FirstTradingDate'], where FirstTradingDate is the
    earliest recorded trading date for the ticker in krx_daily_stocks on/after start_date.
    This is used to drop anomalous pre-listing/pre-market rows that Naver Finance returns for some stocks.

    Tinybird aborts queries after 10s (HTTP 408) and one aggregate over many years exceeds
    that, so query one year at a time (filtering on `date`, the leading sorting key) and
    combine the per-year minimums here.
    """
    print("Fetching tickers and first trading dates from Tinybird (krx_daily_stocks)...")
    headers = {'Authorization': f'Bearer {TINYBIRD_TOKEN}'}
    # Retries 429/5xx; 408 (server-side 10s limit) is not retried since it would hit the same limit.
    session = create_retry_session(
        allowed_methods=["GET"],
        status_forcelist=[429, 500, 502, 503, 504],
    )

    start = pd.Timestamp(start_date)
    today = pd.Timestamp.today().normalize()
    first_seen = {}
    for year in range(start.year, today.year + 1):
        chunk_start = max(start, pd.Timestamp(year=year, month=1, day=1))
        chunk_end = pd.Timestamp(year=year + 1, month=1, day=1)  # exclusive
        query = (
            "SELECT code, toString(min(date)) AS first_date FROM krx_daily_stocks "
            f"WHERE date >= '{chunk_start:%Y-%m-%d}' AND date < '{chunk_end:%Y-%m-%d}' "
            "AND market != 'KONEX' GROUP BY code FORMAT JSON"
        )
        # Raises on non-2xx or exhausted retries so we never continue (or truncate) with no tickers.
        response = session.get(
            f"{TINYBIRD_API_URL}/v0/sql",
            headers=headers,
            params={'q': query},
            timeout=60,
        )
        response.raise_for_status()
        rows = response.json().get('data', [])
        for row in rows:
            code, first_date = row['code'], row['first_date']
            # ISO dates compare correctly as strings; keep the earliest across years.
            if code not in first_seen or first_date < first_seen[code]:
                first_seen[code] = first_date
        print(f"  {year}: {len(rows)} tickers (cumulative {len(first_seen)})")

    df = pd.DataFrame(
        {'Code': list(first_seen.keys()), 'FirstTradingDate': pd.to_datetime(list(first_seen.values()))}
    ).sort_values('Code').reset_index(drop=True)
    print(f"Found {len(df)} distinct tickers.")
    return df

def process_stock(row, start_date):
    code = row['Code']
    first_trading_date = row.get('FirstTradingDate')

    # Fetch from the later of start_date and first_trading_date to avoid fetching pre-listing data
    fetch_start = max(pd.Timestamp(start_date), first_trading_date)
    
    try:
        df = fdr.DataReader(code, fetch_start)
        if df is None or df.empty:
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
        print(f"Error processing {code}: {e}")
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

def push_to_tinybird_batch(df_batch: pd.DataFrame, session: requests.Session | None = None):
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
    
    upload_session = session or create_retry_session(allowed_methods=["POST"], status_forcelist=[429])
    try:
        response = upload_session.post(
            f"{TINYBIRD_API_URL}/v0/datasources",
            headers=headers,
            params=params,
            files={'csv': csv_data.encode('utf-8')},
            timeout=120
        )
        if not response.ok:
            print(f"Failed to push batch ({response.status_code}): {response.text}")
            return 0
        return len(df_batch)
    except requests.exceptions.RetryError as e:
        print(f"❌ Upload failed: Max retries reached for 429 Rate Limit: {e}")
        return 0
    except Exception as e:
        print(f"Failed to push batch: {e}")
        return 0

def format_for_tinybird(df: pd.DataFrame) -> pd.DataFrame:
    df_formatted = df.rename(columns={
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
    df_formatted = df_formatted.fillna(0)
    
    # Cast integers
    int_columns = ['open', 'high', 'low', 'close', 'volume', 'rs', 'rs_1m', 'rs_3m', 'rs_6m', 'rs_12m']
    df_formatted[int_columns] = df_formatted[int_columns].astype('int64')
    
    float_columns = ['change', 'ma5', 'ma10', 'ma20', 'ma60', 'ma120', 'ma240']
    df_formatted[float_columns] = df_formatted[float_columns].astype('float64')
    
    # Ensure correct column order
    final_cols = ['date', 'code', 'open', 'high', 'low', 'close', 'volume', 'change', 'rs', 'rs_1m', 'rs_3m', 'rs_6m', 'rs_12m', 'ma5', 'ma10', 'ma20', 'ma60', 'ma120', 'ma240']
    df_formatted = df_formatted[final_cols]
    
    df_formatted['date'] = df_formatted['date'].dt.strftime('%Y-%m-%d')
    return df_formatted

def load_adjusted_stocks_to_tinybird(start_date: str):
    # 1. Fetch all tickers with their first trading date recorded in krx_daily_stocks
    all_stocks = get_tickers_with_first_trading_date_from_tinybird(start_date)
    print(f"Total tickers found: {len(all_stocks)}")
    
    # 2. Parallel fetch prices
    print("Fetching historical price data...")
    combined_df = parallel_process_stocks(all_stocks, start_date)
    if combined_df.empty:
        print("No data fetched. Exiting.")
        return
        
    print(f"Data fetched! Total rows: {len(combined_df)}")
    
    # 3. Calculate RS indicators
    print("Calculating RS indicators...")
    rs_calc_df = rs.calculate_relative_strength(combined_df)
    
    # Reset index so Date becomes a column
    rs_calc_df = rs_calc_df.reset_index()
    if 'Date' not in rs_calc_df.columns and 'index' in rs_calc_df.columns:
        rs_calc_df = rs_calc_df.rename(columns={'index': 'Date'})
    
    # 4. Format for Tinybird schema
    print("Formatting for Tinybird schema...")
    df_db = format_for_tinybird(rs_calc_df)
    
    # 5. Push to Tinybird in batches
    print("Pushing to Tinybird...")
    total_pushed = 0
    batch_size = 500000
    upload_session = create_retry_session(allowed_methods=["POST"], status_forcelist=[429])
    
    for i in range(0, len(df_db), batch_size):
        batch = df_db.iloc[i:i+batch_size]
        pushed = push_to_tinybird_batch(batch, session=upload_session)
        total_pushed += pushed
        print(f"  -> Pushed {i+len(batch)} / {len(df_db)} rows...")
        
    print(f"✅ Finished! Successfully loaded {total_pushed} rows into Tinybird.")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=str, default="2024-01-01", help="Start date (YYYY-MM-DD)")
    args = parser.parse_args()
    
    start_time = time.time()
    
    print("=" * 60)
    print(f"🚀 Starting FDR Adjusted Data Load to Tinybird (From {args.start})")
    print("=" * 60)

    truncate_datasource(DATASOURCE_NAME)
    load_adjusted_stocks_to_tinybird(args.start)
    
    elapsed = time.time() - start_time
    print("=" * 60)
    print(f"🎉 FDR Adjusted Data Load to Tinybird Completed! (⏱️ Total time: {elapsed:.2f}s)")
    print("=" * 60)

if __name__ == "__main__":
    main()
