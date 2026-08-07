import os
import sys
import time
import requests
import pandas as pd
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

TINYBIRD_TOKEN = os.getenv("TINYBIRD_TOKEN")
TINYBIRD_API_URL = os.getenv("TINYBIRD_API_URL", "https://api.tinybird.co")
DATASOURCE_NAME = "krx_daily_stocks"

def load_parquet_to_tinybird(start_year: int, end_year: int):
    start_time = time.time()
    years = list(range(start_year, end_year + 1))
    
    print("=" * 60)
    print(f"🚀 Starting Marcap Data Load to Tinybird ({years})")
    print("=" * 60)

    for year in years:
        year_start_time = time.time()
        print(f"\n--- Processing Year: {year} ---")
        url = f"https://github.com/FinanceData/marcap/raw/master/data/marcap-{year}.parquet"
        try:
            print(f"Downloading {url}...")
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
            
            csv_data = df_db.to_csv(index=False)
            
            print(f"Uploading {len(df_db)} rows to Tinybird ({DATASOURCE_NAME})...")
            
            headers = {
                'Authorization': f'Bearer {TINYBIRD_TOKEN}'
            }
            params = {
                'name': DATASOURCE_NAME,
                'mode': 'append',
                'format': 'csv'
            }
            
            upload_start = time.time()
            response = requests.post(
                f"{TINYBIRD_API_URL}/v0/datasources",
                headers=headers,
                params=params,
                files={'csv': csv_data.encode('utf-8')}
            )
            
            if response.status_code >= 200 and response.status_code < 300:
                upload_elapsed = time.time() - upload_start
                print(f"✅ Upload successful. (⏱️ {upload_elapsed:.2f} seconds)")
            else:
                print(f"❌ Upload failed: {response.status_code} - {response.text}")
                
            year_elapsed = time.time() - year_start_time
            print(f"✅ Year {year} completed. (⏱️ {year_elapsed:.2f} seconds overall)")
            
        except Exception as e:
            print(f"❌ Failed to process {year} data: {e}")

    elapsed = time.time() - start_time
    print("=" * 60)
    print(f"🎉 Original Stock Data Ingestion to Tinybird Completed! (⏱️ Total time: {elapsed:.2f} seconds)")
    print("=" * 60)

if __name__ == "__main__":
    load_parquet_to_tinybird(2025, 2026)
