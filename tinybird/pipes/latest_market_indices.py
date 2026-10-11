from tinybird_sdk import define_endpoint, node, p, t
from tinybird.tokens import app_token

latest_market_indices = define_endpoint(
    "latest_market_indices",
    {
        "description": "Fetch the latest trading days of market index data and indicators.",
        "params": {
            "market_name": p.string().optional("KOSPI").describe("Market to filter (e.g. KOSPI or KOSDAQ)"),
            "limit": p.int32().optional(2).describe("Number of latest trading days to return"),
        },
        "nodes": [
            node(
                {
                    "name": "latest_indices",
                    "sql": """
                        SELECT 
                            date,
                            market,
                            open,
                            high,
                            low,
                            close,
                            volume,
                            change,
                            ma5,
                            ma20,
                            ma60,
                            ma120,
                            rsi,
                            adx,
                            di
                        FROM krx_daily_indices
                        WHERE market = {{String(market_name, 'KOSPI')}}
                        ORDER BY date DESC
                        LIMIT {{Int32(limit, 2)}}
                    """,
                }
            )
        ],
        "output": {
            "date": t.date(),
            "market": t.string(),
            "open": t.float32(),
            "high": t.float32(),
            "low": t.float32(),
            "close": t.float32(),
            "volume": t.int64(),
            "change": t.float32(),
            "ma5": t.float32(),
            "ma20": t.float32(),
            "ma60": t.float32(),
            "ma120": t.float32(),
            "rsi": t.float32(),
            "adx": t.float32(),
            "di": t.uint8(),
        },
        "tokens": [{"token": app_token, "scope": "READ"}],
    },
)
