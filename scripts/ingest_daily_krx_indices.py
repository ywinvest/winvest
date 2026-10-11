import os
import sys
import time
import socket
import argparse
from datetime import datetime, timedelta
import pandas as pd
from dotenv import load_dotenv

# Set default socket timeout for network requests (e.g. Naver Finance API)
socket.setdefaulttimeout(10)

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
import market

DATASOURCE_NAME = "krx_daily_indices"


def fetch_and_calculate_indices(target_date: str) -> pd.DataFrame:
    """
    Fetch historical prices (warmup 300 days) for KOSPI & KOSDAQ,
    calculate moving averages and technical indicators (RSI, ADX, DI),
    and extract rows for target_date.
    """
    target_dt = datetime.strptime(target_date, "%Y-%m-%d")
    warmup_start = (target_dt - timedelta(days=300)).strftime("%Y-%m-%d")

    # Use NAVER source to prevent upstream KRX cache issues
    market_codes = {"NAVER:KOSPI": "KOSPI", "NAVER:KOSDAQ": "KOSDAQ"}
    results = []

    for code, market_name in market_codes.items():
        print(f"📥 Fetching index data for {market_name} ({code}) from {warmup_start}...", flush=True)
        try:
            df = fdr.DataReader(code, warmup_start, target_date)
            if df is None or df.empty:
                print(f"⚠️ No data returned for {market_name}.", flush=True)
                continue

            if "Change" not in df.columns:
                df["Change"] = df["Close"].pct_change().fillna(0.0)

            # Calculate technical indicators (MA5, MA20, MA60, MA120, RSI, ADX, DI)
            df = market.add_indicators(df)
            df = df.dropna()

            df = df.reset_index()
            if "Date" not in df.columns and "index" in df.columns:
                df = df.rename(columns={"index": "Date"})

            df["date_str"] = df["Date"].dt.strftime("%Y-%m-%d")

            # Extract target_date row
            target_row = df[df["date_str"] == target_date]
            if target_row.empty:
                print(f"⚠️ Target date {target_date} not found in {market_name} data.", flush=True)
                continue

            row_df = target_row.iloc[[-1]].copy()
            row_df["market"] = market_name
            results.append(row_df)
            print(f"✅ Computed indicators for {market_name} on {target_date}.", flush=True)

        except Exception as e:
            print(f"❌ Failed to process index {market_name}: {e}", flush=True)

    if not results:
        return pd.DataFrame()

    return pd.concat(results, ignore_index=True)


def format_for_tinybird(df: pd.DataFrame, target_date: str) -> pd.DataFrame:
    """Format DataFrame to strictly match Tinybird krx_daily_indices schema."""
    df_formatted = df.rename(
        columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
            "Change": "change",
            "MA5": "ma5",
            "MA20": "ma20",
            "MA60": "ma60",
            "MA120": "ma120",
            "RSI": "rsi",
            "ADX": "adx",
            "DI": "di",
        }
    )

    df_formatted["date"] = target_date
    df_formatted = df_formatted.fillna(0.0)

    # Cast types
    float32_cols = ["open", "high", "low", "close", "change", "ma5", "ma20", "ma60", "ma120", "rsi", "adx"]
    for col in float32_cols:
        df_formatted[col] = df_formatted[col].astype("float32")

    df_formatted["volume"] = df_formatted["volume"].astype("int64")
    df_formatted["di"] = df_formatted["di"].astype(int).astype("uint8")
    df_formatted["market"] = df_formatted["market"].astype(str)

    final_cols = [
        "date",
        "market",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "change",
        "ma5",
        "ma20",
        "ma60",
        "ma120",
        "rsi",
        "adx",
        "di",
    ]
    return df_formatted[final_cols]


def ingest_daily_indices(target_date_str: str | None = None, dry_run: bool = False):
    start_time = time.time()
    target_date = parse_target_date(target_date_str)

    print("=" * 60, flush=True)
    print(f"🚀 Starting KRX Daily Indices Ingestion ({target_date})", flush=True)
    print("=" * 60, flush=True)

    if not is_trading_date(target_date):
        print(
            f"ℹ️ Target date {target_date} is not a market trading day (holiday or weekend). Skipping ingestion.",
            flush=True,
        )
        return

    # 1. Fetch & Calculate technical indicators
    raw_df = fetch_and_calculate_indices(target_date)
    if raw_df.empty:
        print(
            f"⚠️ No index records returned for {target_date}. Target date might be a weekend or holiday.",
            flush=True,
        )
        return

    # 2. Format schema
    df_db = format_for_tinybird(raw_df, target_date)

    if dry_run:
        print(
            f"\n🔍 [DRY RUN] Would ingest {len(df_db):,} index rows for {target_date}:",
            flush=True,
        )
        print(df_db, flush=True)
        return

    # 3. Check & Delete existing records for target_date to maintain idempotency
    existing_cnt = check_existing_records(DATASOURCE_NAME, target_date)
    if existing_cnt > 0:
        print(
            f"⚠️ Found {existing_cnt} existing records for {target_date}. Re-running ingestion...",
            flush=True,
        )
        delete_existing_records(
            tinybird.krx_daily_indices, DATASOURCE_NAME, f"date = '{target_date}'"
        )
    else:
        print(f"ℹ️ No existing records found for {target_date}.", flush=True)

    # 4. Upload to Tinybird
    session = create_retry_session(allowed_methods=["POST"], status_forcelist=[429])
    upload_parquet_to_tinybird(DATASOURCE_NAME, df_db, session)

    elapsed = time.time() - start_time
    print("=" * 60, flush=True)
    print(
        f"🎉 Successfully ingested {len(df_db)} index records for {target_date}! (⏱️ Total time: {elapsed:.2f}s)",
        flush=True,
    )
    print("=" * 60, flush=True)


def main():
    parser = argparse.ArgumentParser(
        description="Ingest daily KRX market indices (KOSPI & KOSDAQ) with technical indicators into Tinybird."
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Target date (YYYYMMDD or YYYY-MM-DD). Defaults to today.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview processed index data without modifying Tinybird.",
    )

    args = parser.parse_args()
    ingest_daily_indices(args.date, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
