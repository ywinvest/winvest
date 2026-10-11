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
    delete_existing_records,
    upload_parquet_to_tinybird,
)
import FinanceDataReader as fdr
import rs

TINYBIRD_TOKEN = os.getenv("TINYBIRD_TOKEN")
TINYBIRD_API_URL = (os.getenv("TINYBIRD_API_URL") or "https://api.ap-east-1.aws.tinybird.co").rstrip("/")
DATASOURCE_NAME = "krx_daily_adjusted_stocks"


def query_tinybird(query: str, session: requests.Session | None = None) -> list[dict]:
    """Execute SQL query against Tinybird and return list of result dicts."""
    headers = {"Authorization": f"Bearer {TINYBIRD_TOKEN}"}
    sess = session or requests
    try:
        res = sess.get(
            f"{TINYBIRD_API_URL}/v0/sql",
            headers=headers,
            params={"q": f"{query} FORMAT JSON"},
            timeout=30,
        )
        if res.ok:
            return res.json().get("data", [])
        else:
            print(f"⚠️ Tinybird query error ({res.status_code}): {res.text}", flush=True)
    except Exception as e:
        print(f"⚠️ Query exception: {e}", flush=True)
    return []


def detect_price_discrepancies(target_date: str) -> list[dict]:
    """
    Detect tickers with price discrepancies on target_date:
    1) Corporate actions (splits, reductions) where today's close diverges from prev_close * (1 + change) by >5%
    2) Extreme price changes exceeding KRX price limit (±35%)
    """
    print(f"🔍 Scanning for price discrepancies on {target_date}...", flush=True)
    query = f"""
        SELECT 
            code, 
            toString(date) as date_str, 
            close, 
            prev_close, 
            change, 
            abs(close - prev_close * (1 + change)) / prev_close as diff_ratio 
        FROM (
            SELECT 
                code, 
                date, 
                close, 
                lagInFrame(close, 1) OVER (PARTITION BY code ORDER BY date ASC) as prev_close, 
                change 
            FROM {DATASOURCE_NAME} 
            WHERE date >= subtractDays(toDate('{target_date}'), 10) AND date <= toDate('{target_date}')
        )
        WHERE date = toDate('{target_date}')
          AND prev_close > 0
          AND (diff_ratio > 0.05 OR change > 0.35 OR change < -0.35)
        ORDER BY diff_ratio DESC
    """
    rows = query_tinybird(query)
    if not rows:
        print(f"✅ No price discrepancies detected on {target_date}.", flush=True)
        return []

    print(f"⚠️ Found {len(rows)} ticker(s) with price discrepancies on {target_date}:", flush=True)
    unique_tickers = {}
    for r in rows:
        code = r["code"]
        date_display = r.get("date_str") or r.get("date")
        r["date"] = date_display
        if code not in unique_tickers:
            unique_tickers[code] = r
        diff_info = f", Discrepancy {float(r.get('diff_ratio', 0))*100:.1f}%" if "diff_ratio" in r else ""
        print(
            f"  - [{code}] {date_display}: Close {r['close']:,}, Change {float(r['change'])*100:+.2f}%{diff_info}",
            flush=True,
        )

    return list(unique_tickers.values())


def get_ticker_start_date(code: str) -> str:
    """Fetch earliest recorded date for ticker in Tinybird (defaults to 2024-01-01)."""
    query = f"""
        SELECT 
            toString(min(date)) as min_date,
            count() as cnt
        FROM {DATASOURCE_NAME}
        WHERE code = '{code}'
    """
    rows = query_tinybird(query)
    if rows and rows[0].get("cnt", 0) > 0 and rows[0].get("min_date"):
        return rows[0]["min_date"]
    return "2024-01-01"


def fetch_existing_rs_scores(code: str, start_date: str) -> pd.DataFrame:
    """Fetch existing Relative Strength scores to preserve them during historical backfill."""
    query = f"""
        SELECT 
            toString(date) as date, 
            rs, 
            rs_1m, 
            rs_3m, 
            rs_6m, 
            rs_12m 
        FROM {DATASOURCE_NAME}
        WHERE code = '{code}' AND date >= '{start_date}'
    """
    rows = query_tinybird(query)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def delete_ticker_records(code: str, start_date: str):
    """Delete existing historical records for code on/after start_date."""
    delete_existing_records(
        tinybird.krx_daily_adjusted_stocks,
        DATASOURCE_NAME,
        f"code = '{code}' AND date >= '{start_date}'",
    )


def format_for_tinybird(df: pd.DataFrame, code: str) -> pd.DataFrame:
    """Format DataFrame to match Tinybird krx_daily_adjusted_stocks schema."""
    df_formatted = df.rename(
        columns={
            "Date": "date",
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

    df_formatted["code"] = code
    df_formatted = df_formatted.fillna(0.0)

    # Convert date to string YYYY-MM-DD
    if pd.api.types.is_datetime64_any_dtype(df_formatted["date"]):
        df_formatted["date"] = df_formatted["date"].dt.strftime("%Y-%m-%d")

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


def backfill_ticker_history(
    code: str,
    dry_run: bool = False,
    session: requests.Session | None = None,
) -> int:
    """
    Backfills a single ticker's historical adjusted prices, MAs, and returns.
    Preserves existing cross-sectional RS scores from Tinybird where available.
    """
    # 1. Determine effective start date in Tinybird
    effective_start = get_ticker_start_date(code)

    print(f"\n⚡ [{code}] Backfilling historical adjusted prices from {effective_start}...", flush=True)

    # 2. Fetch existing RS scores before deleting to preserve them
    existing_rs_df = fetch_existing_rs_scores(code, effective_start)
    if not existing_rs_df.empty:
        print(f"  -> Retained {len(existing_rs_df):,} existing RS scores for [{code}].", flush=True)

    # 3. Fetch from FDR starting 400 calendar days earlier to ensure MAs and 12M return are fully calculated
    dt_start = datetime.strptime(effective_start, "%Y-%m-%d")
    fetch_start = (dt_start - timedelta(days=400)).strftime("%Y-%m-%d")

    try:
        df = fdr.DataReader(code, fetch_start)
    except Exception as e:
        print(f"❌ Failed to fetch FDR data for [{code}]: {e}", flush=True)
        return 0

    if df is None or df.empty:
        print(f"⚠️ No data returned from FDR for [{code}].", flush=True)
        return 0

    # 4. Calculate return indicators & Moving Averages
    df = rs.calculate_indicators(df)
    df["MA5"] = df["Close"].rolling(5).mean()
    df["MA10"] = df["Close"].rolling(10).mean()
    df["MA20"] = df["Close"].rolling(20).mean()
    df["MA60"] = df["Close"].rolling(60).mean()
    df["MA120"] = df["Close"].rolling(120).mean()
    df["MA240"] = df["Close"].rolling(240).mean()

    df = df.reset_index()
    if "Date" not in df.columns and "index" in df.columns:
        df = df.rename(columns={"index": "Date"})

    # Filter to effective_start
    df["date_str"] = df["Date"].dt.strftime("%Y-%m-%d")
    df = df[df["date_str"] >= effective_start].copy()
    if df.empty:
        print(f"⚠️ No rows remaining after date filter for [{code}].", flush=True)
        return 0

    # 5. Merge retained RS scores if available
    if not existing_rs_df.empty:
        rs_merge_cols = existing_rs_df.rename(columns={"date": "date_str"})
        df = df.merge(rs_merge_cols, on="date_str", how="left")
    else:
        for col in ["rs", "rs_1m", "rs_3m", "rs_6m", "rs_12m"]:
            df[col] = 0.0

    df["Date"] = df["date_str"]
    df = df.drop(columns=["date_str"], errors="ignore")

    # 6. Format schema
    df_db = format_for_tinybird(df, code)

    if dry_run:
        print(f"🔍 [DRY RUN] [{code}] Would backfill {len(df_db):,} rows from {effective_start}.", flush=True)
        print(df_db[["date", "code", "close", "change", "ma5", "rs"]].head(2), flush=True)
        print("  ...", flush=True)
        print(df_db[["date", "code", "close", "change", "ma5", "rs"]].tail(2), flush=True)
        return len(df_db)

    # 7. Delete outdated historical records in Tinybird
    delete_ticker_records(code, effective_start)

    # 8. Upload fresh Parquet file
    sess = session or create_retry_session(allowed_methods=["POST"], status_forcelist=[429])
    success = upload_parquet_to_tinybird(DATASOURCE_NAME, df_db, sess)
    if success:
        print(f"✅ [{code}] Successfully backfilled {len(df_db):,} historical rows.", flush=True)
        return len(df_db)
    else:
        return 0


def backfill_daily_discrepancies(
    target_date: str, dry_run: bool = False, workers: int = 5
) -> int:
    """
    Scans for price discrepancies on target_date and backfills history for affected tickers.
    """
    if not is_trading_date(target_date):
        print(
            f"ℹ️ Target date {target_date} is not a market trading day (holiday or weekend). Skipping backfill.",
            flush=True,
        )
        return 0

    discrepancies = detect_price_discrepancies(target_date)
    target_codes = list(dict.fromkeys([d["code"] for d in discrepancies]))

    if not target_codes:
        print(f"ℹ️ No discrepancies found for {target_date}. Nothing to backfill.", flush=True)
        return 0

    print(f"\n📋 Discrepant Tickers to Backfill ({len(target_codes)}): {target_codes}", flush=True)
    t0 = time.time()
    total_rows = 0

    upload_session = create_retry_session(allowed_methods=["POST"], status_forcelist=[429])

    if len(target_codes) == 1:
        total_rows += backfill_ticker_history(
            target_codes[0],
            dry_run=dry_run,
            session=upload_session,
        )
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_code = {
                executor.submit(
                    backfill_ticker_history,
                    code,
                    dry_run,
                    upload_session,
                ): code
                for code in target_codes
            }
            for future in concurrent.futures.as_completed(future_to_code):
                code = future_to_code[future]
                try:
                    count = future.result()
                    total_rows += count
                except Exception as e:
                    print(f"❌ Error processing [{code}]: {e}", flush=True)

    elapsed = time.time() - t0
    mode_str = "[DRY RUN] " if dry_run else ""
    print("\n" + "=" * 60, flush=True)
    print(
        f"🎉 {mode_str}Backfill Complete! Processed {len(target_codes)} ticker(s), {total_rows:,} rows in {elapsed:.2f}s.",
        flush=True,
    )
    print("=" * 60, flush=True)
    return total_rows


def main():
    parser = argparse.ArgumentParser(
        description="Detect and backfill KRX adjusted stock price discrepancies for a target date."
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
        help="Preview changes without deleting or modifying Tinybird data.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=5,
        help="Number of parallel workers for multi-ticker backfill (default: 5)",
    )

    args = parser.parse_args()

    target_date = parse_target_date(args.date)

    print("=" * 60, flush=True)
    print(f"🛠️ Starting KRX Adjusted Stocks Discrepancy Backfill ({target_date})", flush=True)
    print("=" * 60, flush=True)

    backfill_daily_discrepancies(
        target_date=target_date, dry_run=args.dry_run, workers=args.workers
    )


if __name__ == "__main__":
    main()
