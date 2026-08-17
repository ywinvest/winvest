from tinybird_sdk import define_endpoint, node, p, t
from tinybird.tinybird_resources import app_token

latest_rs_date = define_endpoint(
    "latest_rs_date",
    {
        "description": "Fetch the latest date from the RS indicators table.",
        "nodes": [
            node(
                {
                    "name": "latest_date",
                    "sql": """
                        SELECT max(date) as date
                        FROM krx_daily_adjusted_stocks
                    """,
                }
            )
        ],
        "output": {
            "date": t.date(),
        },
        "tokens": [{"token": app_token, "scope": "READ"}],
    },
)
