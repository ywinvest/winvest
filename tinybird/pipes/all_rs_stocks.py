from tinybird_sdk import define_endpoint, node, p, t
from tinybird.tinybird_resources import app_token

all_rs_stocks = define_endpoint(
    "all_rs_stocks",
    {
        "description": "Fetch all RS stocks for a given date without limiting, used for the main RS table.",
        "params": {
            "target_date": p.date().describe("The date to query RS scores for")
        },
        "nodes": [
            node(
                {
                    "name": "joined_and_filtered",
                    "sql": """
                        SELECT 
                            s.name as name, 
                            s.code as code, 
                            s.market as market,
                            s.close as close, 
                            s.changes as changes,
                            s.changes_ratio as changes_ratio, 
                            s.marcap as marcap, 
                            s.amount as amount, 
                            i.rs as rs,
                            i.rs_1m as rs_1m,
                            i.rs_3m as rs_3m,
                            i.rs_6m as rs_6m,
                            i.rs_12m as rs_12m
                        FROM krx_daily_stocks s
                        JOIN krx_daily_adjusted_stocks i 
                          ON s.code = i.code AND s.date = i.date
                        WHERE s.date = {{Date(target_date)}}
                          AND NOT match(s.name, '.*스팩.*')
                          AND NOT match(s.code, '.*[579KLMNO]$')
                        ORDER BY 
                            i.rs DESC, 
                            i.rs_1m DESC, 
                            i.rs_3m DESC, 
                            i.rs_6m DESC, 
                            i.rs_12m DESC,
                            s.marcap DESC
                        LIMIT 5000
                    """,
                }
            )
        ],
        "output": {
            "name": t.string(),
            "code": t.string(),
            "market": t.string(),
            "close": t.int32(),
            "changes": t.int32(),
            "changes_ratio": t.float32(),
            "marcap": t.int64(),
            "amount": t.int64(),
            "rs": t.float32(),
            "rs_1m": t.float32(),
            "rs_3m": t.float32(),
            "rs_6m": t.float32(),
            "rs_12m": t.float32(),
        },
        "tokens": [{"token": app_token, "scope": "READ"}],
    },
)
