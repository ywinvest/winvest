from tinybird.client import tinybird


def get_rs_table_data(date_str: str | None = None) -> list[dict]:
    """
    RS 데이터를 Tinybird에서 조회하고 템플릿 렌더링에 맞게 반환합니다.
    """
    if date_str:
        target_date = date_str
    else:
        try:
            date_res = tinybird.latest_rs_date.query()
            if date_res.get("data") and len(date_res["data"]) > 0:
                target_date = date_res["data"][0]["date"]
            else:
                return []
        except Exception as e:
            print(f"Tinybird query failed for latest date: {e}")
            return []

    try:
        res = tinybird.all_rs_stocks.query({"target_date": target_date})

        if not res.get("data"):
            return []

        stocks = []
        for idx, row in enumerate(res["data"], start=1):
            close = row.get("close") or 0
            prev_high_52w = row.get("prev_high_52w") or 0
            prev_high_all_time = row.get("prev_high_all_time") or 0

            is_all_time_high = bool(prev_high_all_time > 0 and close > prev_high_all_time)
            is_52w_high = bool(prev_high_52w > 0 and close > prev_high_52w)
            pct_from_52w_high = ((close - prev_high_52w) / prev_high_52w * 100.0) if prev_high_52w > 0 else 0.0
            pct_from_all_time_high = (
                ((close - prev_high_all_time) / prev_high_all_time * 100.0) if prev_high_all_time > 0 else 0.0
            )

            stocks.append({
                "date": target_date,
                "name": row.get("name"),
                "code": row.get("code"),
                "market": row.get("market"),
                "changes_ratio": row.get("changes_ratio"),
                "changes": row.get("changes"),
                "marcap": row.get("marcap"),
                "amount": row.get("amount"),
                "rs_rank": idx,
                "close": close,
                "rs": row.get("rs"),
                "rs_1m": row.get("rs_1m"),
                "rs_3m": row.get("rs_3m"),
                "rs_6m": row.get("rs_6m"),
                "rs_12m": row.get("rs_12m"),
                "prev_high_52w": prev_high_52w,
                "prev_high_all_time": prev_high_all_time,
                "is_52w_high": is_52w_high,
                "is_all_time_high": is_all_time_high,
                "pct_from_52w_high": pct_from_52w_high,
                "pct_from_all_time_high": pct_from_all_time_high,
            })
        return stocks
    except Exception as e:
        print(f"Tinybird query failed for all_rs_stocks: {e}")
        return []

