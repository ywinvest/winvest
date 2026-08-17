from tinybird_sdk import define_endpoint, node, p, t
from tinybird.tinybird_resources import app_token

top_rs_stocks = define_endpoint(
    "top_rs_stocks",
    {
        "description": "Fetch top RS stocks for a given date and market.",
        "params": {
            "target_date": p.date().describe("The date to query RS scores for"),
            "market_name": p.string().optional("KOSPI").describe("Market to filter (e.g. KOSPI or KOSDAQ)"),
            "limit": p.int32().optional(5).describe("Number of stocks to return")
        },
        "nodes": [
            node(
                {
                    "name": "joined_and_filtered",
                    "sql": """
                        SELECT 
                            s.name as name, 
                            s.code as code, 
                            s.close as close, 
                            s.changes_ratio as changes_ratio, 
                            s.marcap as marcap, 
                            s.amount as amount, 
                            i.rs as rs
                        FROM krx_daily_stocks s
                        JOIN krx_daily_adjusted_stocks i 
                          ON s.code = i.code AND s.date = i.date
                        WHERE s.date = {{Date(target_date)}}
                          AND s.market LIKE concat('%', {{String(market_name, 'KOSPI')}}, '%')
                          AND s.marcap >= 200000000000
                          AND NOT match(s.name, '.*스팩.*')
                          AND NOT match(s.code, '.*[579KLMNO]$')
                        ORDER BY 
                            i.rs DESC, 
                            i.rs_1m DESC, 
                            i.rs_3m DESC, 
                            i.rs_6m DESC, 
                            i.rs_12m DESC
                        LIMIT {{Int32(limit, 5)}}
                    """,
                }
            )
        ],
        "output": {
            "name": t.string(),
            "code": t.string(),
            "close": t.int32(),
            "changes_ratio": t.float32(),
            "marcap": t.int64(),
            "amount": t.int64(),
            "rs": t.float32(),
        },
        "tokens": [{"token": app_token, "scope": "READ"}],
    },
)
