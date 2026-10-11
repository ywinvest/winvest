import os
import sys
import time
import argparse
import tempfile
import pandas as pd
import requests
from dotenv import load_dotenv

from http_utils import create_retry_session

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from tinybird.client import tinybird

TINYBIRD_TOKEN = os.getenv("TINYBIRD_TOKEN")
TINYBIRD_API_URL = os.getenv("TINYBIRD_API_URL", "https://api.tinybird.co")
DATASOURCE_NAME = "krx_daily_stocks"

def truncate_datasource(datasource_name: str):
    print(f"🧹 Truncating datasource: {datasource_name}...")
    try:
        getattr(tinybird, datasource_name).truncate()
        print(f"✅ Successfully truncated datasource: {datasource_name}")
    except Exception as e:
        print(f"❌ Failed to truncate datasource: {datasource_name} - {e}")
        sys.exit(1)

def load_parquet_to_tinybird(start_year: int, end_year: int):
    # Retries up to 3 times on 429 Rate Limit errors
    session = create_retry_session(allowed_methods=["POST"], status_forcelist=[429])
    
    years = list(range(start_year, end_year + 1))

    for year in years:
        year_start_time = time.time()
        print(f"\n📅 Processing Year: {year} {'='*40}")
        url = f"https://github.com/FinanceData/marcap/raw/master/data/marcap-{year}.parquet"
        try:
            print(f"📥 Downloading data from {url}...")
            df = pd.read_parquet(url)
            print(f"💾 Loaded {len(df):,} rows into memory.")
            
            # The 'Date' column is often set as the DataFrame's index in the original dataset.
            # We reset the index to move 'Date' back into a regular column so we can process and upload it.
            df = df.reset_index()
            
            # If an 'index' column was added during reset_index, drop it
            if 'index' in df.columns:
                df = df.drop(columns=['index'])
            
            df['Date'] = df['Date'].dt.strftime('%Y-%m-%d')
            
            # 1. Dynamically fill NaN for string/object columns with empty string
            string_cols = df.select_dtypes(include=['object', 'string']).columns
            df[string_cols] = df[string_cols].fillna("").astype(str)
            
            # 2. Fill NaN for all remaining (numeric) columns with 0
            df = df.fillna(0)
            
            # Convert all column names to lowercase to match the Tinybird schema
            df.columns = df.columns.str.lower()
            df.rename(columns={
                'changecode': 'change_code',
                'changesratio': 'changes_ratio',
                'marketid': 'market_id'
            }, inplace=True)
            
            # Pandas converts integer columns containing NaNs to Float64 by default.
            # Even after filling NaNs with 0, the columns remain Float64 (e.g., 15000.0 instead of 15000).
            # Tinybird enforces strict typing (Int64), so uploading floats causes schema mismatch errors.
            # We explicitly cast them to int64 to perfectly match the Parquet schema with Tinybird's Int64 type.
            int_columns = ['open', 'high', 'low', 'close', 'volume', 'amount', 'changes', 'marcap', 'stocks', 'rank']
            df[int_columns] = df[int_columns].astype('int64')
            
            with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tmp:
                df.to_parquet(tmp.name, index=False)
                tmp_path = tmp.name
            
            print(f"📤 Uploading {len(df):,} rows to Tinybird ({DATASOURCE_NAME})...")
            
            upload_start = time.time()
            
            # Tinybird SDK (.append) has a bug where it hardcodes the multipart field name to "csv".
            # For Parquet, the Tinybird API strictly requires the field name to be "parquet".
            # We bypass the SDK and use requests directly for the upload.
            headers = {'Authorization': f'Bearer {TINYBIRD_TOKEN}'}
            params = {'name': DATASOURCE_NAME, 'mode': 'append', 'format': 'parquet'}
            
            try:
                with open(tmp_path, 'rb') as f:
                    response = session.post(
                        f"{TINYBIRD_API_URL}/v0/datasources",
                        headers=headers,
                        params=params,
                        files={'parquet': f},
                        timeout=120
                    )
                # Raise an exception for critical errors (e.g., 500) other than 429
                response.raise_for_status()
                
                upload_elapsed = time.time() - upload_start
                print(f"✅ Upload successful. (⏱️ {upload_elapsed:.2f}s)")
                
            except requests.exceptions.RetryError as e:
                print(f"❌ Upload failed: Max retries (3) reached for 429 Rate Limit.")
                sys.exit(1)
            except Exception as e:
                # This includes HTTPError raised by response.raise_for_status()
                print(f"❌ Upload request failed: {e}")
                sys.exit(1)
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
                
            year_elapsed = time.time() - year_start_time
            print(f"✅ Year {year} completed. (⏱️ {year_elapsed:.2f}s overall)")
            
        except Exception as e:
            print(f"❌ Failed to process {year} data: {e}")



def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-year", type=int, default=2014, help="Start year (e.g., 2014)")
    parser.add_argument("--end-year", type=int, default=pd.Timestamp.now().year, help="End year (e.g., 2024)")
    args = parser.parse_args()
    
    start_time = time.time()
    years_range = f"{args.start_year} - {args.end_year}"
    
    print("=" * 60)
    print(f"🚀 Starting Marcap Data Load to Tinybird ({years_range})")
    print("=" * 60)

    truncate_datasource(DATASOURCE_NAME)
    load_parquet_to_tinybird(args.start_year, args.end_year)
    
    elapsed = time.time() - start_time
    print("=" * 60)
    print(f"🎉 Marcap Data Load to Tinybird Completed! (⏱️ Total time: {elapsed:.2f}s)")
    print("=" * 60)

if __name__ == "__main__":
    main()
