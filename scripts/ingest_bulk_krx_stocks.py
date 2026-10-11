import os
import sys
import time
import argparse
from datetime import datetime
import pandas as pd
from dotenv import load_dotenv

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

DATASOURCE_NAME = "krx_daily_stocks"


def format_for_tinybird(df: pd.DataFrame) -> pd.DataFrame:
    """Format marcap DataFrame to strictly match Tinybird krx_daily_stocks schema."""
    df = df.reset_index()
    if "index" in df.columns:
        df = df.drop(columns=["index"])

    # Ensure Date column formatted YYYY-MM-DD
    if pd.api.types.is_datetime64_any_dtype(df["Date"]):
        df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")

    # Lowercase column names and standardize
    df.columns = df.columns.str.lower()
    df.rename(
        columns={
            "changecode": "change_code",
            "changesratio": "changes_ratio",
            "marketid": "market_id",
        },
        inplace=True,
    )

    # Filter out invalid rows
    df = df.dropna(subset=["close", "marcap"])
    df = df[df["close"] > 0].copy()

    # Calculate rank if missing or null
    if "rank" not in df.columns or df["rank"].isna().any():
        df["rank"] = df.groupby("date")["marcap"].rank(method="min", ascending=False)

    # Type casting
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
    return df[required_cols]


def process_year(year: int, session, dry_run: bool = False, truncate_done: bool = False) -> int:
    """Download, transform, and upload one year of marcap stock data."""
    url = f"https://github.com/FinanceData/marcap/raw/master/data/marcap-{year}.parquet"
    print(f"\n📅 --- Processing Year: {year} ---", flush=True)
    print(f"📥 Downloading marcap data from {url}...", flush=True)

    t0 = time.time()
    try:
        raw_df = pd.read_parquet(url)
    except Exception as e:
        print(f"❌ Failed to download marcap data for {year}: {e}", flush=True)
        return 0

    print(f"  -> Downloaded {len(raw_df):,} rows in {time.time() - t0:.2f}s.", flush=True)

    # Transform
    df_clean = format_for_tinybird(raw_df)
    print(f"  -> Formatted {len(df_clean):,} valid stock records.", flush=True)

    if dry_run:
        print(f"🔍 [DRY RUN] Would ingest {len(df_clean):,} rows for {year}:", flush=True)
        print(df_clean.head(2), flush=True)
        print(df_clean.tail(2), flush=True)
        return len(df_clean)

    # Delete existing records for year if full truncate wasn't performed
    if not truncate_done:
        year_condition = f"date >= '{year}-01-01' AND date <= '{year}-12-31'"
        print(f"🗑️ Deleting existing records for {year_condition}...", flush=True)
        delete_existing_records(tinybird.krx_daily_stocks, DATASOURCE_NAME, year_condition)

    # Upload in chunks if very large (e.g. 250,000 rows) or full
    chunk_size = 250000
    uploaded_for_year = 0
    for i in range(0, len(df_clean), chunk_size):
        chunk = df_clean.iloc[i : i + chunk_size]
        upload_parquet_to_tinybird(DATASOURCE_NAME, chunk, session)
        uploaded_for_year += len(chunk)

    return uploaded_for_year


def ingest_bulk_stocks(
    start_year: int,
    end_year: int,
    truncate: bool = False,
    dry_run: bool = False,
):
    start_time = time.time()
    years = list(range(start_year, end_year + 1))
    years_range = f"{start_year} - {end_year}"

    print("=" * 60, flush=True)
    print(f"🚀 Starting KRX Bulk Stock Ingestion ({years_range})", flush=True)
    if truncate:
        print("⚠️ Mode: Full Table Truncate & Reload", flush=True)
    else:
        print(f"ℹ️ Mode: Yearly Partition Replacement ({years_range})", flush=True)
    print("=" * 60, flush=True)

    if truncate and not dry_run:
        truncate_datasource(DATASOURCE_NAME)

    session = create_retry_session(allowed_methods=["POST"], status_forcelist=[429])
    total_uploaded = 0

    for year in years:
        uploaded = process_year(
            year=year,
            session=session,
            dry_run=dry_run,
            truncate_done=truncate,
        )
        total_uploaded += uploaded

    elapsed = time.time() - start_time
    mode_str = "[DRY RUN] " if dry_run else ""
    print("\n" + "=" * 60, flush=True)
    print(
        f"🎉 {mode_str}Bulk Stock Ingestion Completed! Processed {total_uploaded:,} rows across {years_range} in ⏱️ {elapsed:.2f}s.",
        flush=True,
    )
    print("=" * 60, flush=True)


def main():
    current_year = datetime.now().year
    today_str = datetime.today().strftime("%Y-%m-%d")

    parser = argparse.ArgumentParser(
        description="Bulk ingest KRX stock listing & price history (from marcap) into Tinybird."
    )
    parser.add_argument(
        "-s",
        "--start",
        "--start-date",
        "--start-year",
        dest="start",
        type=str,
        default=None,
        help="Start date or year to load (default: 2014 for full reload).",
    )
    parser.add_argument(
        "-e",
        "--end",
        "--end-date",
        "--end-year",
        dest="end",
        type=str,
        default=None,
        help=f"End date or year to load (default: current year {current_year}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without modifying Tinybird.",
    )

    args = parser.parse_args()

    # When start is not specified (default), reload entire historical range (2014 ~ present) with full table truncate.
    # When start is specified, update partition for that specific range without full table truncate.
    if args.start is None:
        start_year = 2014
        end_date = parse_date_or_year(args.end, is_end=True)
        end_year = int(end_date[:4])
        truncate = True
    else:
        start_date = parse_date_or_year(args.start, is_end=False)
        end_date = parse_date_or_year(args.end, is_end=True)
        start_year = int(start_date[:4])
        end_year = int(end_date[:4])
        truncate = False

    ingest_bulk_stocks(
        start_year=start_year,
        end_year=end_year,
        truncate=truncate,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()

