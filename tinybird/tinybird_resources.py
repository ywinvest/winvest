from tinybird_sdk import (
    define_datasource, define_token,
    engine, t
)

# App token to access the resources
app_token = define_token("winvest_app_token")

# 1. krx_daily_stocks
krx_daily_stocks = define_datasource(
    "krx_daily_stocks",
    {
        "description": "Original raw daily stock prices from marcap",
        "schema": {
            "date": t.date(),
            "code": t.string(),
            "name": t.string(),
            "market": t.string(),
            "open": t.int32(),
            "high": t.int32(),
            "low": t.int32(),
            "close": t.int32(),
            "volume": t.int64(),
            "amount": t.int64(),
            "changes": t.int32(),
            "changes_ratio": t.float32(),
            "marcap": t.int64(),
            "stocks": t.int64(),
            "rank": t.int32(),
        },
        "engine": engine.merge_tree({
            "sorting_key": ["date", "code"],
            "partition_key": "toYYYYMM(date)"
        }),
        "tokens": [{"token": app_token, "scope": "APPEND"}],
    },
)

# 2. krx_daily_adjusted_stocks
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
        "tokens": [{"token": app_token, "scope": "APPEND"}],
    },
)

# 3. krx_daily_indices
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
        "tokens": [{"token": app_token, "scope": "APPEND"}],
    },
)
