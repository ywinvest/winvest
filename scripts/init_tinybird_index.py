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
import ssl

try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

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
    
    upload_start = time.time()
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
            upload_elapsed = time.time() - upload_start
            print(f"✅ Upload successful. (⏱️ {upload_elapsed:.2f} seconds)")
            return len(df_batch)
        elif response.status_code == 429:
            print(f"⚠️ Rate limited. Retrying after 5 seconds...")
            time.sleep(5)
        else:
            print(f"❌ Upload failed: {response.status_code} - {response.text}")
            break
            
    return 0

def migrate_market_data(start_year: int, end_year: int):
    start_date = f"{start_year}-01-01"
    end_date = f"{end_year}-12-31"
    
    market_codes = {"KS11": "KOSPI", "KQ11": "KOSDAQ"}
    
    start_time = time.time()
    print("=" * 60)
    print(f"🚀 Starting KRX Daily Index Data Load to Tinybird ({start_year} - {end_year})")
    print("=" * 60)
    
    truncate_datasource(DATASOURCE_NAME)
    
    all_dfs = []
    
    for code, market_name in market_codes.items():
        print(f"\n--- Processing {market_name} ({code}) ---")
        try:
            df = fdr.DataReader(code, start_date, end_date)
            if df.empty:
                print(f"No data for {market_name}")
                continue
                
            print(f"Loaded {len(df)} rows from FDR.")
            
            if 'Change' not in df.columns:
                df['Change'] = df['Close'].pct_change(fill_method=None).fillna(0.0)
            
            # Calculate indicators (drops NA values caused by MA/RSI windows)
            df = market.add_indicators(df)
            df = df.dropna()
            print(f"Calculated indicators. {len(df)} rows remaining after dropna.")
            
            df = df.reset_index()
            if 'Date' not in df.columns and 'index' in df.columns:
                df = df.rename(columns={'index': 'Date'})
            df['Date'] = df['Date'].dt.strftime('%Y-%m-%d')
            # Save the clean market name (KOSPI/KOSDAQ) instead of ticker
            df['Market'] = market_name
            
            # Change boolean DI column to UInt8 (0/1) for Tinybird
            df['DI'] = df['DI'].astype(int)
            
            # Select and rename columns to match Tinybird schema exactly
            final_cols = ['Date', 'Market', 'Open', 'High', 'Low', 'Close', 'Volume', 'Change', 'MA5', 'MA20', 'MA60', 'MA120', 'RSI', 'ADX', 'DI']
            df_db = df[final_cols].copy()
            df_db.rename(columns={col: col.lower() for col in df_db.columns}, inplace=True)
            
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
    pushed = push_to_tinybird_batch(combined_df)
    
    elapsed = time.time() - start_time
    print("=" * 60)
    print(f"🎉 KRX Daily Index Data Ingestion Completed! (Pushed {pushed} rows in ⏱️ {elapsed:.2f} seconds)")
    print("=" * 60)

def main():
    parser = argparse.ArgumentParser(description="Load KRX daily market index data (KOSPI/KOSDAQ) to Tinybird.")
    parser.add_argument("--start-year", type=int, default=2014, help="Start year to load.")
    parser.add_argument("--end-year", type=int, default=pd.Timestamp.now().year, help="End year to load.")
    args = parser.parse_args()
    
    # Ensure print statements aren't buffered in logs
    sys.stdout.reconfigure(line_buffering=True)
    migrate_market_data(args.start_year, args.end_year)

if __name__ == "__main__":
    main()
