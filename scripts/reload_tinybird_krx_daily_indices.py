import os
import sys
import time
import argparse
import requests
import pandas as pd
import FinanceDataReader as fdr
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import market
from http_utils import create_retry_session

load_dotenv()

TINYBIRD_TOKEN = os.getenv("TINYBIRD_TOKEN")
TINYBIRD_API_URL = os.getenv("TINYBIRD_API_URL", "https://api.tinybird.co")
DATASOURCE_NAME = "krx_daily_indices"

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
        print(f"⚠️ Failed to truncate {datasource_name}: {response.status_code} - {response.text}")

def push_to_tinybird_batch(df_batch: pd.DataFrame, session: requests.Session | None = None) -> int:
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

def format_for_tinybird(df: pd.DataFrame, market_name: str) -> pd.DataFrame:
    df_formatted = df.reset_index()
    if 'Date' not in df_formatted.columns and 'index' in df_formatted.columns:
        df_formatted = df_formatted.rename(columns={'index': 'Date'})
    df_formatted['Date'] = df_formatted['Date'].dt.strftime('%Y-%m-%d')
    df_formatted['Market'] = market_name
    df_formatted['DI'] = df_formatted['DI'].astype(int)

    final_cols = ['Date', 'Market', 'Open', 'High', 'Low', 'Close', 'Volume', 'Change', 'MA5', 'MA20', 'MA60', 'MA120', 'RSI', 'ADX', 'DI']
    df_db = df_formatted[final_cols].copy()
    df_db.rename(columns={col: col.lower() for col in df_db.columns}, inplace=True)
    return df_db

def load_indices_to_tinybird(start_year: int, end_year: int):
    # Fetch with a 1-year warmup buffer so MA120 is fully calculated from the very start of start_year
    warmup_start = f"{max(2014, start_year - 1)}-01-01"
    start_date = f"{start_year}-01-01"
    end_date = f"{end_year}-12-31"
    
    # Query Naver Finance directly to bypass upstream fdr_krx_data_cache bug
    market_codes = {"NAVER:KOSPI": "KOSPI", "NAVER:KOSDAQ": "KOSDAQ"}
    
    all_dfs = []
    
    for code, market_name in market_codes.items():
        print(f"\n--- Processing {market_name} ({code}) ---")
        try:
            df = fdr.DataReader(code, warmup_start, end_date)
            if df.empty:
                print(f"No data for {market_name}")
                continue
                
            print(f"Loaded {len(df)} rows from FDR (NAVER).")
            
            if 'Change' not in df.columns:
                df['Change'] = df['Close'].pct_change().fillna(0.0)
            
            # Calculate technical indicators
            df = market.add_indicators(df)
            df = df.dropna()
            
            # Filter to target start date
            df = df[df.index >= start_date]
            print(f"Calculated indicators. {len(df)} rows remaining in target range ({start_date} ~ {end_date}).")
            
            df_db = format_for_tinybird(df, market_name)
            all_dfs.append(df_db)
            
        except Exception as e:
            print(f"❌ Failed to process {market_name}: {e}")
            import traceback
            traceback.print_exc()

    if not all_dfs:
        print("\n❌ No data processed. Exiting.")
        return
        
    combined_df = pd.concat(all_dfs, ignore_index=True)
    print(f"\nPushing total {len(combined_df)} rows to Tinybird ({DATASOURCE_NAME})...")
    upload_session = create_retry_session(allowed_methods=["POST"], status_forcelist=[429])
    
    # Push in yearly batches to stay well within ClickHouse's 100-partition-per-insert limit (toYYYYMM)
    combined_df['year'] = combined_df['date'].str[:4]
    total_pushed = 0
    for year, group in combined_df.groupby('year', sort=True):
        batch = group.drop(columns=['year'])
        pushed = push_to_tinybird_batch(batch, session=upload_session)
        total_pushed += pushed
        print(f"  -> Pushed {year}: {pushed} rows...")
        
    print(f"✅ Successfully loaded {total_pushed} rows into Tinybird.")

def main():
    parser = argparse.ArgumentParser(description="Load KRX daily market index data (KOSPI/KOSDAQ) to Tinybird.")
    parser.add_argument("--start-year", type=int, default=2014, help="Start year to load.")
    parser.add_argument("--end-year", type=int, default=pd.Timestamp.now().year, help="End year to load.")
    args = parser.parse_args()
    
    # Ensure print statements aren't buffered in logs
    sys.stdout.reconfigure(line_buffering=True)
    
    start_time = time.time()
    years_range = f"{args.start_year} - {args.end_year}"
    
    print("=" * 60)
    print(f"🚀 Starting KRX Daily Index Data Load to Tinybird ({years_range})")
    print("=" * 60)

    truncate_datasource(DATASOURCE_NAME)
    load_indices_to_tinybird(args.start_year, args.end_year)
    
    elapsed = time.time() - start_time
    print("=" * 60)
    print(f"🎉 KRX Daily Index Data Ingestion Completed! (⏱️ Total time: {elapsed:.2f} seconds)")
    print("=" * 60)

if __name__ == "__main__":
    main()
