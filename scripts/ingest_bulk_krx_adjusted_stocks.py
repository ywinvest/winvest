import os
import sys
import time
import socket
import argparse
import concurrent.futures
from functools import partial
from datetime import datetime
import pandas as pd
import requests
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
    truncate_datasource,
    delete_existing_records,
    upload_parquet_to_tinybird,
    TINYBIRD_TOKEN,
    TINYBIRD_API_URL,
)
import FinanceDataReader as fdr
import rs

DATASOURCE_NAME = "krx_daily_adjusted_stocks"


def get_tickers_with_first_trading_date(start_date: str) -> pd.DataFrame:
    """
    Fetch active tickers and their first trading date from krx_daily_stocks.
    Falls back to fdr.StockListing('KRX') if Tinybird query is unavailable.
    """
    print("📥 Fetching tickers and first trading dates from krx_daily_stocks...", flush=True)
    headers = {"Authorization": f"Bearer {TINYBIRD_TOKEN}"}
    session = create_retry_session(
        allowed_methods=["GET"],
        status_forcelist=[429, 500, 502, 503, 504],
    )

    start = pd.Timestamp(start_date)
    today = pd.Timestamp.today().normalize()
    first_seen = {}

    try:
        for year in range(start.year, today.year + 1):
            chunk_start = max(start, pd.Timestamp(year=year, month=1, day=1))
            chunk_end = pd.Timestamp(year=year + 1, month=1, day=1)
            query = (
                "SELECT code, toString(min(date)) AS first_date FROM krx_daily_stocks "
                f"WHERE date >= '{chunk_start:%Y-%m-%d}' AND date < '{chunk_end:%Y-%m-%d}' "
                "AND market != 'KONEX' GROUP BY code FORMAT JSON"
            )
            response = session.get(
                f"{TINYBIRD_API_URL}/v0/sql",
                headers=headers,
                params={"q": query},
                timeout=60,
            )
            if response.ok:
                rows = response.json().get("data", [])
                for row in rows:
                    code, first_date = row["code"], row["first_date"]
                    if code not in first_seen or first_date < first_seen[code]:
                        first_seen[code] = first_date
                print(f"  {year}: {len(rows):,} tickers (cumulative: {len(first_seen):,})", flush=True)
    except Exception as e:
        print(f"⚠️ Querying krx_daily_stocks encountered error: {e}", flush=True)

    if first_seen:
        df = (
            pd.DataFrame(
                {
                    "Code": list(first_seen.keys()),
                    "FirstTradingDate": pd.to_datetime(list(first_seen.values())),
                }
            )
            .sort_values("Code")
            .reset_index(drop=True)
        )
        print(f"ℹ️ Total distinct tickers found: {len(df):,}", flush=True)
        return df

    # Fallback to StockListing
    print("⚠️ Fallback: Fetching active tickers via FDR StockListing...", flush=True)
    listing = fdr.StockListing("KRX")
    listing = listing[listing["Market"] != "KONEX"]
    tickers = listing["Code"].dropna().unique().tolist()
    df = pd.DataFrame(
        {"Code": tickers, "FirstTradingDate": pd.Timestamp(start_date)}
    ).reset_index(drop=True)
    print(f"ℹ️ Found {len(df):,} tickers via fallback.", flush=True)
    return df


def process_single_stock(row, start_date: str, end_date: str | None = None) -> pd.DataFrame | None:
    """Fetch prices for ticker, calculate moving averages and returns."""
    code = row["Code"]
    first_trading_date = row.get("FirstTradingDate")
    fetch_start = max(pd.Timestamp(start_date), first_trading_date)

    try:
        df = fdr.DataReader(code, fetch_start, end_date) if end_date else fdr.DataReader(code, fetch_start)
        if df is None or df.empty:
            return None

        df = rs.calculate_indicators(df)
        df["MA5"] = df["Close"].rolling(window=5).mean()
        df["MA10"] = df["Close"].rolling(window=10).mean()
        df["MA20"] = df["Close"].rolling(window=20).mean()
        df["MA60"] = df["Close"].rolling(window=60).mean()
        df["MA120"] = df["Close"].rolling(window=120).mean()
        df["MA240"] = df["Close"].rolling(window=240).mean()

        df["Code"] = code
        return df
    except Exception:
        return None


def parallel_fetch_stocks(
    all_stocks: pd.DataFrame,
    start_date: str,
    end_date: str | None = None,
    max_workers: int = 10,
) -> pd.DataFrame:
    """Fetch all ticker price histories and compute indicators in parallel."""
    process_func = partial(process_single_stock, start_date=start_date, end_date=end_date)
    results = []
    total = len(all_stocks)
    completed = 0
    t0 = time.time()

    print(f"📥 Concurrently fetching prices for {total:,} tickers (workers: {max_workers})...", flush=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(process_func, row) for _, row in all_stocks.iterrows()]
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            if res is not None and not res.empty:
                results.append(res)
            completed += 1
            if completed % 200 == 0 or completed == total:
                print(f"  -> Processed {completed:,}/{total:,} tickers...", flush=True)

    print(
        f"  -> Successfully processed {len(results):,} tickers in {time.time() - t0:.2f}s.",
        flush=True,
    )
    return pd.concat(results) if results else pd.DataFrame()


def format_for_tinybird(df: pd.DataFrame) -> pd.DataFrame:
    """Format DataFrame to strictly match Tinybird krx_daily_adjusted_stocks schema."""
    df_formatted = df.rename(
        columns={
            "Date": "date",
            "Code": "code",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
            "Change": "change",
            "RS": "rs",
            "RS_1M": "rs_1m",
            "RS_3M": "rs_3m",
            "RS_6M": "rs_6m",
            "RS_12M": "rs_12m",
            "MA5": "ma5",
            "MA10": "ma10",
            "MA20": "ma20",
            "MA60": "ma60",
            "MA120": "ma120",
            "MA240": "ma240",
        }
    )

    df_formatted = df_formatted.fillna(0.0)

    # Cast integer columns (Int32, Int64)
    int32_columns = ["open", "high", "low", "close"]
    for col in int32_columns:
        df_formatted[col] = df_formatted[col].astype("int32")

    df_formatted["volume"] = df_formatted["volume"].astype("int64")

    # Cast float32 columns
    float32_columns = [
        "change",
        "rs",
        "rs_1m",
        "rs_3m",
        "rs_6m",
        "rs_12m",
        "ma5",
        "ma10",
        "ma20",
        "ma60",
        "ma120",
        "ma240",
    ]
    for col in float32_columns:
        df_formatted[col] = df_formatted[col].astype("float32")

    df_formatted["code"] = df_formatted["code"].astype(str)

    if pd.api.types.is_datetime64_any_dtype(df_formatted["date"]):
        df_formatted["date"] = df_formatted["date"].dt.strftime("%Y-%m-%d")

    final_cols = [
        "date",
        "code",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "change",
        "rs",
        "rs_1m",
        "rs_3m",
        "rs_6m",
        "rs_12m",
        "ma5",
        "ma10",
        "ma20",
        "ma60",
        "ma120",
        "ma240",
    ]
    return df_formatted[final_cols]


def ingest_bulk_adjusted_stocks(
    start_date: str = "2024-01-01",
    end_date: str | None = None,
    truncate: bool = True,
    dry_run: bool = False,
    workers: int = 10,
):
    start_time = time.time()
    date_range_str = f"{start_date} ~ {end_date}" if end_date else f"From {start_date}"

    print("=" * 60, flush=True)
    print(f"🚀 Starting KRX Bulk Adjusted Stock Ingestion ({date_range_str})", flush=True)
    if truncate:
        print("⚠️ Mode: Full Table Truncate & Re-calculation", flush=True)
    else:
        print(f"ℹ️ Mode: Partition Replacement ({date_range_str})", flush=True)
    print("=" * 60, flush=True)

    # 1. Fetch active tickers and first trading dates
    all_stocks = get_tickers_with_first_trading_date(start_date)
    if all_stocks.empty:
        print("❌ No tickers found. Exiting.", flush=True)
        return

    # 2. Parallel price fetch and indicator calculation
    combined_df = parallel_fetch_stocks(all_stocks, start_date, end_date=end_date, max_workers=workers)
    if combined_df.empty:
        print("❌ No price data fetched. Exiting.", flush=True)
        return

    print(f"📊 Total fetched rows: {len(combined_df):,}", flush=True)

    # 3. Calculate cross-sectional Relative Strength percentiles across full history
    print("📈 Calculating cross-sectional Relative Strength (RS) percentiles...", flush=True)
    t_rs = time.time()
    rs_calc_df = rs.calculate_relative_strength(combined_df)
    print(f"✅ Relative Strength computed in {time.time() - t_rs:.2f}s.", flush=True)

    # Reset index
    rs_calc_df = rs_calc_df.reset_index()
    if "Date" not in rs_calc_df.columns and "index" in rs_calc_df.columns:
        rs_calc_df = rs_calc_df.rename(columns={"index": "Date"})

    # 4. Format schema
    df_db = format_for_tinybird(rs_calc_df)

    if dry_run:
        print(f"\n🔍 [DRY RUN] Would ingest {len(df_db):,} adjusted stock rows:", flush=True)
        print(df_db.head(2), flush=True)
        print(df_db.tail(2), flush=True)
        return

    # 5. Clean existing records
    if truncate:
        truncate_datasource(DATASOURCE_NAME)
    else:
        if end_date:
            delete_condition = f"date >= '{start_date}' AND date <= '{end_date}'"
        else:
            delete_condition = f"date >= '{start_date}'"
        print(f"🗑️ Deleting records for {delete_condition}...", flush=True)
        delete_existing_records(tinybird.krx_daily_adjusted_stocks, DATASOURCE_NAME, delete_condition)

    # 6. Upload in Parquet batches
    batch_size = 250000
    upload_session = create_retry_session(allowed_methods=["POST"], status_forcelist=[429])
    total_uploaded = 0

    print(f"\n📤 Uploading {len(df_db):,} rows to Tinybird in batches of {batch_size:,}...", flush=True)
    for i in range(0, len(df_db), batch_size):
        batch = df_db.iloc[i : i + batch_size]
        upload_parquet_to_tinybird(DATASOURCE_NAME, batch, upload_session)
        total_uploaded += len(batch)

    elapsed = time.time() - start_time
    print("\n" + "=" * 60, flush=True)
    print(
        f"🎉 Bulk Adjusted Stock Ingestion Completed! Successfully loaded {total_uploaded:,} rows in ⏱️ {elapsed:.2f}s.",
        flush=True,
    )
    print("=" * 60, flush=True)


def main():
    today_str = datetime.today().strftime("%Y-%m-%d")
    parser = argparse.ArgumentParser(
        description="Bulk ingest KRX daily adjusted stock prices and cross-sectional RS indicators into Tinybird."
    )
    parser.add_argument(
        "-s",
        "--start",
        "--start-date",
        "--start-year",
        dest="start",
        type=str,
        default=None,
        help="Start date or year (YYYY, YYYY-MM-DD, default: 2024-01-01 for full reload).",
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
    parser.add_argument(
        "--workers",
        type=int,
        default=10,
        help="Number of concurrent worker threads (default: 10).",
    )

    args = parser.parse_args()

    # When start is not specified (default), reload entire history from 2024-01-01 with full table truncate.
    # When start is specified, update partition for that specific range without full table truncate.
    if args.start is None:
        start_date = "2024-01-01"
        end_date = parse_date_or_year(args.end, is_end=True)
        truncate = True
    else:
        start_date = parse_date_or_year(args.start, is_end=False, default_year=2024)
        end_date = parse_date_or_year(args.end, is_end=True)
        truncate = False

    ingest_bulk_adjusted_stocks(
        start_date=start_date,
        end_date=end_date,
        truncate=truncate,
        dry_run=args.dry_run,
        workers=args.workers,
    )


if __name__ == "__main__":
    main()

