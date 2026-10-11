from tinybird_sdk import define_datasource, engine, t
from tinybird.tokens import app_token, ingest_token

krx_daily_adjusted_stocks = define_datasource(
    "krx_daily_adjusted_stocks",
    {
        "description": "Adjusted daily stock prices from FinanceDataReader",
        "schema": {
            "date": t.date(),
            "code": t.string(),
            "open": t.int32(),
            "high": t.int32(),
            "low": t.int32(),
            "close": t.int32(),
            "volume": t.int64(),
            "change": t.float32(),
            "rs": t.float32(),
            "rs_1m": t.float32(),
            "rs_3m": t.float32(),
            "rs_6m": t.float32(),
            "rs_12m": t.float32(),
            "ma5": t.float32(),
            "ma10": t.float32(),
            "ma20": t.float32(),
            "ma60": t.float32(),
            "ma120": t.float32(),
            "ma240": t.float32(),
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
