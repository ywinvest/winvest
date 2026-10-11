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
from date_utils import parse_date_or_year
from tinybird_utils import (
    delete_existing_records,
    truncate_datasource,
    upload_parquet_to_tinybird,
)
import FinanceDataReader as fdr
import market

DATASOURCE_NAME = "krx_daily_indices"


def format_for_tinybird(df: pd.DataFrame, market_name: str) -> pd.DataFrame:
    """Format DataFrame to strictly match Tinybird krx_daily_indices schema."""
    df_formatted = df.reset_index()
    if "Date" not in df_formatted.columns and "index" in df_formatted.columns:
        df_formatted = df_formatted.rename(columns={"index": "Date"})

    df_formatted["date"] = df_formatted["Date"].dt.strftime("%Y-%m-%d")
    df_formatted["market"] = market_name

    rename_map = {
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
    df_formatted = df_formatted.rename(columns=rename_map)
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


def fetch_and_calculate_indices_range(start_date: str, end_date: str) -> pd.DataFrame:
    """Fetch and compute technical indicators for KOSPI & KOSDAQ across date range."""
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    # Fetch with 300-day warmup buffer so MA120 is fully calculated from start_date
    warmup_start = (start_dt - timedelta(days=300)).strftime("%Y-%m-%d")

    # NOTE: Naver Finance API returns a sliding window of the most recent ~3,000 trading days (~2014-07 as of 2026).
    # TODO: Once upstream FDR fdr_krx_data_cache bug is resolved or updated for KS11/KQ11, consider switching back
    # to 'KS11' and 'KQ11' (or combining historical KS11/KQ11 with recent NAVER) so older historical data does not shift out.
    market_codes = {"NAVER:KOSPI": "KOSPI", "NAVER:KOSDAQ": "KOSDAQ"}
    all_dfs = []

    for code, market_name in market_codes.items():
        print(f"\n📥 Fetching index data for {market_name} ({code}) from {warmup_start} to {end_date}...", flush=True)
        try:
            df = fdr.DataReader(code, warmup_start, end_date)
            if df is None or df.empty:
                print(f"⚠️ No data returned for {market_name}.", flush=True)
                continue

            if "Change" not in df.columns:
                df["Change"] = df["Close"].pct_change().fillna(0.0)

            # Calculate technical indicators
            df = market.add_indicators(df)
            df = df.dropna()

            # Filter to target start date
            df = df[df.index >= start_date]
            print(f"✅ Processed {len(df):,} rows for {market_name} ({start_date} ~ {end_date}).", flush=True)

            df_db = format_for_tinybird(df, market_name)
            all_dfs.append(df_db)
        except Exception as e:
            print(f"❌ Failed to process {market_name}: {e}", flush=True)

    if not all_dfs:
        return pd.DataFrame()

    return pd.concat(all_dfs, ignore_index=True)


def ingest_bulk_indices(
    start_date: str,
    end_date: str,
    truncate: bool = False,
    dry_run: bool = False,
):
    start_time = time.time()
    date_range_str = f"{start_date} ~ {end_date}"

    print("=" * 60, flush=True)
    print(f"🚀 Starting KRX Bulk Indices Ingestion ({date_range_str})", flush=True)
    if truncate:
        print("⚠️ Mode: Full Table Truncate & Reload", flush=True)
    else:
        print(f"ℹ️ Mode: Partition Replacement ({date_range_str})", flush=True)
    print("=" * 60, flush=True)

    # 1. Fetch & compute
    combined_df = fetch_and_calculate_indices_range(start_date, end_date)
    if combined_df.empty:
        print("❌ No index data retrieved. Exiting.", flush=True)
        return

    print(f"\n📊 Total computed index rows: {len(combined_df):,}", flush=True)

    if dry_run:
        print(f"\n🔍 [DRY RUN] Would ingest {len(combined_df):,} index rows across {date_range_str}:", flush=True)
        print(combined_df.head(3), flush=True)
        print(combined_df.tail(3), flush=True)
        return

    # 2. Clean existing records
    if truncate:
        truncate_datasource(DATASOURCE_NAME)
    else:
        delete_condition = f"date >= '{start_date}' AND date <= '{end_date}'"
        print(f"🗑️ Deleting existing records for {delete_condition}...", flush=True)
        delete_existing_records(tinybird.krx_daily_indices, DATASOURCE_NAME, delete_condition)

    # 3. Upload to Tinybird in yearly batches
    combined_df["year"] = combined_df["date"].str[:4]
    session = create_retry_session(allowed_methods=["POST"], status_forcelist=[429])
    total_uploaded = 0

    for year, group in combined_df.groupby("year", sort=True):
        batch = group.drop(columns=["year"])
        print(f"\n📤 Uploading Year {year} ({len(batch):,} rows)...", flush=True)
        upload_parquet_to_tinybird(DATASOURCE_NAME, batch, session)
        total_uploaded += len(batch)

    elapsed = time.time() - start_time
    print("\n" + "=" * 60, flush=True)
    print(
        f"🎉 Bulk Index Ingestion Completed! Successfully loaded {total_uploaded:,} rows in ⏱️ {elapsed:.2f}s.",
        flush=True,
    )
    print("=" * 60, flush=True)


def main():
    today_str = datetime.today().strftime("%Y-%m-%d")

    parser = argparse.ArgumentParser(
        description="Bulk ingest KRX daily market index data (KOSPI/KOSDAQ) into Tinybird."
    )
    parser.add_argument(
        "-s",
        "--start",
        "--start-date",
        "--start-year",
        dest="start",
        type=str,
        default=None,
        help="Start date or year (YYYY, YYYY-MM-DD, default: 2014-01-01 for full reload).",
    )
    parser.add_argument(
        "-e",
        "--end",
        "--end-date",
        "--end-year",
        dest="end",
        type=str,
        default=None,
        help=f"End date or year (YYYY, YYYY-MM-DD, default: {today_str}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without modifying Tinybird.",
    )

    args = parser.parse_args()

    # When start is not specified (default), reload entire historical range from 2014 with full table truncate.
    # When start is specified, update partition for that specific range without full table truncate.
    if args.start is None:
        start_date = "2014-01-01"
        end_date = parse_date_or_year(args.end, is_end=True)
        truncate = True
    else:
        start_date = parse_date_or_year(args.start, is_end=False)
        end_date = parse_date_or_year(args.end, is_end=True)
        truncate = False

    ingest_bulk_indices(
        start_date=start_date,
        end_date=end_date,
        truncate=truncate,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()

