from tinybird_sdk import define_datasource, engine, t
from tinybird.tokens import app_token, ingest_token

krx_daily_stocks = define_datasource(
    "krx_daily_stocks",
    {
        "description": "Original raw daily stock prices from marcap",
        "schema": {
            "date": t.date(),
            "code": t.string(),
            "name": t.string(),
            "market": t.string(),
            "market_id": t.string(),
            "dept": t.string(),
            "open": t.int32(),
            "high": t.int32(),
            "low": t.int32(),
            "close": t.int32(),
            "volume": t.int64(),
            "amount": t.int64(),
            "changes": t.int32(),
            "change_code": t.string(),
            "changes_ratio": t.float32(),
            "marcap": t.int64(),
            "stocks": t.int64(),
            "rank": t.int32(),
        },
        "engine": engine.merge_tree({
            "sorting_key": ["date", "code"],
            "partition_key": "toYYYYMM(date)"
        }),
        "tokens": [
            {"token": app_token, "scope": "READ"},
            {"token": ingest_token, "scope": "APPEND"}
        ],
    },
)
