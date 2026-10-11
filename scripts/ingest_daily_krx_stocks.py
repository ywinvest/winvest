import os
import sys
import time
import argparse
import pandas as pd
from dotenv import load_dotenv

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from http_utils import create_retry_session
from tinybird.client import tinybird
from date_utils import parse_target_date, is_trading_date
from tinybird_utils import (
    check_existing_records,
    delete_existing_records,
    upload_parquet_to_tinybird,
)
import FinanceDataReader as fdr

DATASOURCE_NAME = "krx_daily_stocks"


def fetch_and_process_krx_stocks(target_date: str) -> pd.DataFrame:
    """Fetch KRX stock listing via FinanceDataReader and convert to Tinybird schema."""
    print(f"📥 1. Fetching KRX stock listing for {target_date} via FDR...")
    t0 = time.time()
    df = fdr.StockListing("KRX")
    print(f"  -> Fetched {len(df):,} raw rows in {time.time() - t0:.2f}s.")

    # 1. Rename columns to match Tinybird schema
    df.rename(
        columns={
            "Code": "code",
            "Name": "name",
            "Market": "market",
            "MarketId": "market_id",
            "Dept": "dept",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
            "Amount": "amount",
            "Changes": "changes",
            "ChangeCode": "change_code",
            "ChagesRatio": "changes_ratio",
            "Marcap": "marcap",
            "Stocks": "stocks",
        },
        inplace=True,
    )

    # 2. Filter out invalid rows
    df = df.dropna(subset=["close", "marcap"])
    df = df[df["close"] > 0].copy()

    # 3. Add date and calculate rank by market capitalization
    df["date"] = target_date
    df["rank"] = df["marcap"].rank(method="min", ascending=False).astype("int32")

    # 4. Strict type casting matching Tinybird schema
    string_cols = ["code", "name", "market", "market_id", "dept", "change_code"]
    for col in string_cols:
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str)
        else:
            df[col] = ""

    int32_cols = ["open", "high", "low", "close", "changes", "rank"]
    for col in int32_cols:
        df[col] = df[col].fillna(0).astype("int32")

    int64_cols = ["volume", "amount", "marcap", "stocks"]
    for col in int64_cols:
        df[col] = df[col].fillna(0).astype("int64")

    df["changes_ratio"] = df["changes_ratio"].fillna(0.0).astype("float32")

    required_cols = [
        "date",
        "code",
        "name",
        "market",
        "market_id",
        "dept",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "changes",
        "change_code",
        "changes_ratio",
        "marcap",
        "stocks",
        "rank",
    ]
    df = df[required_cols]
    print(f"  -> Processed {len(df):,} valid stock records.")
    return df


def ingest_daily_stocks(target_date_str: str | None = None, dry_run: bool = False):
    start_time = time.time()
    target_date = parse_target_date(target_date_str)

    print("=" * 60)
    print(f"🚀 Starting KRX Daily Stock Ingestion to Tinybird ({target_date})")
    print("=" * 60)

    if not is_trading_date(target_date):
        print(
            f"ℹ️ Target date {target_date} is not a market trading day (holiday or weekend). Skipping ingestion.",
            flush=True,
        )
        return

    # 1. Fetch & transform
    df = fetch_and_process_krx_stocks(target_date)

    if dry_run:
        print(f"\n🔍 [DRY RUN] Would ingest {len(df):,} rows for {target_date}.")
        print(df.head(3))
        return

    # 2. Check & clean existing rows for target_date to maintain idempotency
    existing_cnt = check_existing_records(DATASOURCE_NAME, target_date)
    if existing_cnt > 0:
        print(f"ℹ️ Found {existing_cnt:,} existing records for {target_date}.")
        delete_existing_records(
            tinybird.krx_daily_stocks, DATASOURCE_NAME, f"date = '{target_date}'"
        )
    else:
        print(f"ℹ️ No existing records found for {target_date}. Ready to append.")

    # 3. Upload to Tinybird
    session = create_retry_session(allowed_methods=["POST"], status_forcelist=[429])
    upload_parquet_to_tinybird(DATASOURCE_NAME, df, session)

    elapsed = time.time() - start_time
    print("=" * 60)
    print(
        f"🎉 Daily Stock Ingestion for {target_date} Completed in ⏱️ {elapsed:.2f}s!"
    )
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Ingest daily KRX stock data into Tinybird."
    )
    parser.add_argument(
        "--date",
        type=str,
        help="Target date in YYYYMMDD or YYYY-MM-DD format. Defaults to today.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without modifying Tinybird.",
    )
    args = parser.parse_args()

    sys.stdout.reconfigure(line_buffering=True)
    ingest_daily_stocks(args.date, args.dry_run)


if __name__ == "__main__":
    main()
