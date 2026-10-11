import os
import sys
import time
import socket
import argparse
import tempfile
import concurrent.futures
from datetime import datetime, timedelta
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
from date_utils import parse_target_date, is_trading_date
from tinybird_utils import (
    check_existing_records,
    delete_existing_records,
    upload_parquet_to_tinybird,
)
import FinanceDataReader as fdr
import rs

DATASOURCE_NAME = "krx_daily_adjusted_stocks"


def get_active_tickers() -> list[str]:
    """Fetch active KRX tickers (excluding KONEX) directly via FinanceDataReader."""
    print("📥 Fetching active KRX tickers via FDR StockListing (excluding KONEX)...", flush=True)
    df = fdr.StockListing("KRX")
    df = df[df["Market"] != "KONEX"]
    tickers = df["Code"].dropna().unique().tolist()
    print(f"ℹ️ Found {len(tickers):,} active tickers.", flush=True)
    return tickers


def process_single_ticker(
    code: str, fetch_start: str, target_date: str
) -> pd.DataFrame | None:
    """Fetch price history for a ticker, calculate indicators, and return the target date row."""
    try:
        df = fdr.DataReader(code, fetch_start)
        if df is None or df.empty:
            return None

        # 1. Calculate return indicators (Return_1M, Return_3M, Return_6M, Return_12M)
        df = rs.calculate_indicators(df)

        # 2. Calculate Moving Averages (MA5 ~ MA240)
        df["MA5"] = df["Close"].rolling(5).mean()
        df["MA10"] = df["Close"].rolling(10).mean()
        df["MA20"] = df["Close"].rolling(20).mean()
        df["MA60"] = df["Close"].rolling(60).mean()
        df["MA120"] = df["Close"].rolling(120).mean()
        df["MA240"] = df["Close"].rolling(240).mean()

        df["Code"] = code
        df = df.reset_index()
        if "Date" not in df.columns and "index" in df.columns:
            df = df.rename(columns={"index": "Date"})

        df["date_str"] = df["Date"].dt.strftime("%Y-%m-%d")

        # Keep row for target_date
        target_rows = df[df["date_str"] == target_date]
        if target_rows.empty:
            return None

        return target_rows.iloc[[-1]]
    except Exception:
        return None


def fetch_and_calculate_all_adjusted_stocks(
    tickers: list[str], target_date: str, max_workers: int = 10
) -> pd.DataFrame:
    """Fetch price histories in parallel, compute MAs and cross-sectional RS scores."""
    # 400 calendar days covers ~270 trading days, sufficient for MA240 and Return_12M
    target_dt = datetime.strptime(target_date, "%Y-%m-%d")
    fetch_start = (target_dt - timedelta(days=400)).strftime("%Y-%m-%d")

    print(
        f"📥 Fetching prices & computing indicators for {len(tickers):,} tickers (from {fetch_start})...",
        flush=True,
    )
    t0 = time.time()
    results = []
    completed = 0
    total = len(tickers)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_ticker = {
            executor.submit(
                process_single_ticker, ticker, fetch_start, target_date
            ): ticker
            for ticker in tickers
        }
        for future in concurrent.futures.as_completed(future_to_ticker):
            res = future.result()
            if res is not None and not res.empty:
                results.append(res)
            completed += 1
            if completed % 300 == 0 or completed == total:
                print(f"  -> Processed {completed:,}/{total:,} tickers...", flush=True)

    print(
        f"  -> Successfully processed {len(results):,} tickers in {time.time() - t0:.2f}s.",
        flush=True,
    )

    if not results:
        return pd.DataFrame()

    combined_df = pd.concat(results, ignore_index=True)

    # Cross-sectional Relative Strength ranking for target_date
    print("📊 Calculating cross-sectional Relative Strength (RS) percentiles...", flush=True)
    combined_df["Date"] = pd.to_datetime(target_date)
    combined_df.set_index("Date", inplace=True)
    rs_calc_df = rs.calculate_relative_strength(combined_df)
    rs_calc_df = rs_calc_df.reset_index(drop=True)

    return rs_calc_df


def format_for_tinybird(df: pd.DataFrame, target_date: str) -> pd.DataFrame:
    """Format DataFrame to strictly match Tinybird krx_daily_adjusted_stocks schema."""
    df_formatted = df.rename(
        columns={
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

    df_formatted["date"] = target_date
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


def ingest_daily_adjusted_stocks(
    target_date_str: str | None = None, dry_run: bool = False
):
    start_time = time.time()
    target_date = parse_target_date(target_date_str)

    print("=" * 60, flush=True)
    print(f"🚀 Starting KRX Daily Adjusted Stock Ingestion ({target_date})", flush=True)
    print("=" * 60, flush=True)

    if not is_trading_date(target_date):
        print(
            f"ℹ️ Target date {target_date} is not a market trading day (holiday or weekend). Skipping ingestion.",
            flush=True,
        )
        return

    # 1. Fetch active tickers
    tickers = get_active_tickers()
    if not tickers:
        print(f"❌ No active tickers found for {target_date}.", flush=True)
        return

    # 2. Fetch prices & compute indicators
    raw_df = fetch_and_calculate_all_adjusted_stocks(tickers, target_date)
    if raw_df.empty:
        print(
            f"⚠️ No price records returned for {target_date}. Target date might be a weekend or holiday.",
            flush=True,
        )
        return

    # 3. Format for Tinybird schema
    df_db = format_for_tinybird(raw_df, target_date)

    if dry_run:
        print(
            f"\n🔍 [DRY RUN] Would ingest {len(df_db):,} adjusted stock rows for {target_date}.",
            flush=True,
        )
        print(df_db.head(3), flush=True)
        return

    # 4. Check & clean existing rows for target_date to maintain idempotency
    existing_cnt = check_existing_records(DATASOURCE_NAME, target_date)
    if existing_cnt > 0:
        print(f"ℹ️ Found {existing_cnt:,} existing records for {target_date}.", flush=True)
        delete_existing_records(
            tinybird.krx_daily_adjusted_stocks, DATASOURCE_NAME, f"date = '{target_date}'"
        )
    else:
        print(f"ℹ️ No existing records found for {target_date}. Ready to append.", flush=True)

    # 5. Upload to Tinybird
    session = create_retry_session(allowed_methods=["POST"], status_forcelist=[429])
    upload_parquet_to_tinybird(DATASOURCE_NAME, df_db, session)

    elapsed = time.time() - start_time
    print("=" * 60, flush=True)
    print(
        f"🎉 Daily Adjusted Stock Ingestion for {target_date} Completed in ⏱️ {elapsed:.2f}s!",
        flush=True,
    )
    print("=" * 60, flush=True)


def main():
    parser = argparse.ArgumentParser(
        description="Ingest daily KRX adjusted stock prices and RS indicators into Tinybird."
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
    ingest_daily_adjusted_stocks(args.date, args.dry_run)


if __name__ == "__main__":
    main()
