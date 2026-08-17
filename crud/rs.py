# No SQLAlchemy imports needed since we use Tinybird

def get_rs_table_data(
    date_str: str = None
) -> list[dict]:
    """
    RS 데이터를 DB에서 조회하고 템플릿 렌더링에 맞게 반환합니다.
    """
    # Tinybird에서 최신 날짜 가져오기
    if date_str:
        target_date = date_str
    else:
        try:
            from tinybird.client import tinybird
            date_res = tinybird.latest_rs_date.query()
            if date_res.get("data") and len(date_res["data"]) > 0:
                target_date = date_res["data"][0]["date"]
            else:
                return []
        except Exception as e:
            print(f"Tinybird query failed for latest date: {e}")
            return []

    try:
        from tinybird.client import tinybird
        # Tinybird에서 전체 RS 데이터 가져오기
        res = tinybird.all_rs_stocks.query({"target_date": target_date})
        
        if not res.get("data"):
            return []
            
        stocks = []
        for idx, row in enumerate(res["data"], start=1):
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
                "close": row.get("close"),
                "rs": row.get("rs"),
                "rs_1m": row.get("rs_1m"),
                "rs_3m": row.get("rs_3m"),
                "rs_6m": row.get("rs_6m"),
                "rs_12m": row.get("rs_12m"),
            })
        return stocks
    except Exception as e:
        print(f"Tinybird query failed for all_rs_stocks: {e}")
        return []
