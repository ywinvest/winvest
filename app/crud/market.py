import market
from tinybird.client import tinybird

SIGNAL_MAP = {
    "green": "양호🟢",
    "yellow": "주의🟡",
    "red": "경고🔴",
}


def get_market_status(market_name: str) -> dict:
    """특정 시장(KOSPI/KOSDAQ)의 최신 지수 및 전일 대비 신호 변화를 계산합니다."""
    try:
        res = tinybird.latest_market_indices.query({"market_name": market_name, "limit": 2})
        data = res.get("data", [])
        if len(data) < 2:
            return {"status_msg": "데이터 부족", "change": 0.0, "close": 0.0, "signal": "red", "signal_text": "오류"}

        today_market = data[0]
        yesterday_market = data[1]

        today_ma5_up = today_market["close"] > today_market["ma5"]
        today_ma20_up = today_market["close"] > today_market["ma20"]
        today_signal_raw = market.get_signal(
            today_ma20_up, today_market["adx"], bool(today_market["di"]), today_ma5_up
        )

        yesterday_ma5_up = yesterday_market["close"] > yesterday_market["ma5"]
        yesterday_ma20_up = yesterday_market["close"] > yesterday_market["ma20"]
        yesterday_signal_raw = market.get_signal(
            yesterday_ma20_up, yesterday_market["adx"], bool(yesterday_market["di"]), yesterday_ma5_up
        )

        today_signal_text = SIGNAL_MAP[today_signal_raw]
        yesterday_signal_text = SIGNAL_MAP[yesterday_signal_raw]

        if today_signal_text == yesterday_signal_text:
            status_msg = f"{today_signal_text} 유지"
        else:
            status_msg = f"{yesterday_signal_text} ➡ {today_signal_text} 전환"

        return {
            "status_msg": status_msg,
            "change": today_market["change"],
            "close": today_market["close"],
            "signal": today_signal_raw,
            "signal_text": today_signal_text,
        }
    except Exception as e:
        return {"status_msg": f"오류: {e}", "change": 0.0, "close": 0.0, "signal": "red", "signal_text": "실패"}


def format_market_cap(marcap: int | float | None) -> str:
    """시가총액/거래대금을 조·억 단위 문자열로 변환합니다."""
    if marcap is None or marcap == 0:
        return "정보없음"
    if marcap >= 1e12:
        return f"{marcap / 1e12:.1f}조"
    return f"{marcap / 1e8:.0f}억"


def _fetch_market_top5_rs(latest_date: str, market_name: str) -> list[dict]:
    """특정 시장의 RS 상위 5개 종목을 조회하고 포맷팅합니다."""
    items: list[dict] = []
    try:
        res = tinybird.top_rs_stocks.query({"target_date": latest_date, "market_name": market_name})
        if res.get("data"):
            best_row = max(res["data"], key=lambda x: x["changes_ratio"])
            for row in res["data"]:
                close = row.get("close") or 0
                prev_high_52w = row.get("prev_high_52w") or 0
                prev_high_all_time = row.get("prev_high_all_time") or 0
                items.append({
                    "name": row["name"],
                    "code": row["code"],
                    "close": close,
                    "changes_ratio": row["changes_ratio"],
                    "marcap_formatted": format_market_cap(row["marcap"]),
                    "amount_formatted": format_market_cap(row["amount"]),
                    "rs": row["rs"],
                    "prev_high_52w": prev_high_52w,
                    "prev_high_all_time": prev_high_all_time,
                    "is_52w_high": bool(prev_high_52w > 0 and close > prev_high_52w),
                    "is_all_time_high": bool(prev_high_all_time > 0 and close > prev_high_all_time),
                    "is_top_gainer": row == best_row,
                })
    except Exception as e:
        print(f"Tinybird query failed for {market_name} top 5: {e}")
    return items


def get_market_dashboard_data() -> dict:
    """시장 대시보드(partials/market_status.html)에 필요한 전체 컨텍스트 데이터를 반환합니다."""
    kospi = get_market_status("KOSPI")
    kosdaq = get_market_status("KOSDAQ")

    latest_date_result = None
    try:
        date_res = tinybird.latest_rs_date.query()
        if date_res.get("data") and len(date_res["data"]) > 0:
            latest_date_result = date_res["data"][0]["date"]
    except Exception as e:
        print(f"Tinybird query failed for latest date: {e}")

    if latest_date_result:
        kospi_rs_top5_list = _fetch_market_top5_rs(latest_date_result, "KOSPI")
        kosdaq_rs_top5_list = _fetch_market_top5_rs(latest_date_result, "KOSDAQ")
    else:
        latest_date_result = "2026-06-28 (Mock Data)"
        kospi_rs_top5_list = [
            {"name": "삼성전자", "code": "005930", "close": 84500, "changes_ratio": 2.5, "marcap_formatted": "500조", "amount_formatted": "1.5조", "rs": 98.5, "is_52w_high": True, "is_all_time_high": False, "is_top_gainer": False},
            {"name": "SK하이닉스", "code": "000660", "close": 235000, "changes_ratio": 5.2, "marcap_formatted": "120조", "amount_formatted": "2.1조", "rs": 97.2, "is_52w_high": True, "is_all_time_high": True, "is_top_gainer": True},
            {"name": "현대차", "code": "005380", "close": 285000, "changes_ratio": -1.2, "marcap_formatted": "50조", "amount_formatted": "3000억", "rs": 95.1, "is_52w_high": False, "is_all_time_high": False, "is_top_gainer": False},
            {"name": "NAVER", "code": "035420", "close": 172000, "changes_ratio": 0.5, "marcap_formatted": "30조", "amount_formatted": "1500억", "rs": 93.4, "is_52w_high": False, "is_all_time_high": False, "is_top_gainer": False},
            {"name": "카카오", "code": "035720", "close": 42000, "changes_ratio": -0.8, "marcap_formatted": "25조", "amount_formatted": "1200억", "rs": 92.0, "is_52w_high": False, "is_all_time_high": False, "is_top_gainer": False},
        ]
        kosdaq_rs_top5_list = [
            {"name": "에코프로비엠", "code": "247540", "close": 195000, "changes_ratio": 8.5, "marcap_formatted": "30조", "amount_formatted": "8000억", "rs": 99.1, "is_52w_high": True, "is_all_time_high": True, "is_top_gainer": True},
            {"name": "에코프로", "code": "086520", "close": 95000, "changes_ratio": 4.2, "marcap_formatted": "25조", "amount_formatted": "5000억", "rs": 98.4, "is_52w_high": True, "is_all_time_high": False, "is_top_gainer": False},
            {"name": "셀트리온헬스케어", "code": "091990", "close": 68000, "changes_ratio": -2.1, "marcap_formatted": "15조", "amount_formatted": "2000억", "rs": 96.5, "is_52w_high": False, "is_all_time_high": False, "is_top_gainer": False},
            {"name": "포스코DX", "code": "022100", "close": 38000, "changes_ratio": 1.5, "marcap_formatted": "10조", "amount_formatted": "3500억", "rs": 95.2, "is_52w_high": False, "is_all_time_high": False, "is_top_gainer": False},
            {"name": "엘앤에프", "code": "066970", "close": 150000, "changes_ratio": -0.5, "marcap_formatted": "8조", "amount_formatted": "1000억", "rs": 94.8, "is_52w_high": False, "is_all_time_high": False, "is_top_gainer": False},
        ]

    return {
        "kospi": kospi,
        "kosdaq": kosdaq,
        "kospi_rs_top5": kospi_rs_top5_list,
        "kosdaq_rs_top5": kosdaq_rs_top5_list,
        "latest_date": latest_date_result,
    }

