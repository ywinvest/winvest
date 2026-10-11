import os
from dotenv import load_dotenv
from tinybird_sdk import Tinybird

from tinybird.datasources import (
    krx_daily_stocks,
    krx_daily_adjusted_stocks,
    krx_daily_indices,
)

from tinybird.pipes import (
    top_rs_stocks,
    latest_rs_date,
    all_rs_stocks,
    latest_market_indices,
)

# Load environment variables
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

tinybird = Tinybird({
    "datasources": {
        "krx_daily_stocks": krx_daily_stocks,
        "krx_daily_adjusted_stocks": krx_daily_adjusted_stocks,
        "krx_daily_indices": krx_daily_indices,
    },
    "pipes": {
        "top_rs_stocks": top_rs_stocks,
        "latest_rs_date": latest_rs_date,
        "all_rs_stocks": all_rs_stocks,
        "latest_market_indices": latest_market_indices,
    },
    "base_url": (os.getenv("TINYBIRD_API_URL") or "https://api.ap-east-1.aws.tinybird.co").rstrip("/"),
    "token": os.getenv("TINYBIRD_TOKEN"),
})
