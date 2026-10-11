from tinybird_sdk import define_datasource, engine, t
from tinybird.tokens import app_token, ingest_token

krx_daily_indices = define_datasource(
    "krx_daily_indices",
    {
        "description": "Daily market index data (KOSPI/KOSDAQ) with technical indicators",
        "schema": {
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
        "engine": engine.merge_tree({
            "sorting_key": ["date", "market"],
            "partition_key": "toYYYYMM(date)"
        }),
        "tokens": [
            {"token": app_token, "scope": "READ"},
            {"token": ingest_token, "scope": "APPEND"}
        ],
    },
)
