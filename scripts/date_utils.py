import socket
from datetime import datetime, timedelta

# Set default socket timeout for network requests (e.g. Naver Finance API)
socket.setdefaulttimeout(10)


def is_trading_date(target_date: str) -> bool:
    """
    Check if target_date was an actual market trading day (not a weekend or holiday).
    Returns True for actual trading days, False for weekends and national holidays.
    """
    import FinanceDataReader as fdr

    try:
        target_date = parse_target_date(target_date)
        dt = datetime.strptime(target_date, "%Y-%m-%d")
        # Quick weekend check: 5 is Saturday, 6 is Sunday
        if dt.weekday() >= 5:
            return False

        # Check against KOSPI index to verify trading took place on target_date
        start_check = (dt - timedelta(days=5)).strftime("%Y-%m-%d")
        df = fdr.DataReader("NAVER:KOSPI", start_check, target_date)
        if df is not None and not df.empty:
            dates = df.index.strftime("%Y-%m-%d").tolist()
            return target_date in dates
    except Exception as e:
        print(f"⚠️ Failed to verify trading date via FDR: {e}", flush=True)
    return False


def parse_target_date(date_str: str | None) -> str:
    """
    Parse date string in YYYYMMDD or YYYY-MM-DD format to YYYY-MM-DD.
    If date_str is None or empty, returns today's date.
    """
    if not date_str:
        return datetime.today().strftime("%Y-%m-%d")
    cleaned = date_str.strip().replace("-", "")
    if len(cleaned) == 8 and cleaned.isdigit():
        return datetime.strptime(cleaned, "%Y%m%d").strftime("%Y-%m-%d")
    return datetime.strptime(date_str.strip(), "%Y-%m-%d").strftime("%Y-%m-%d")
