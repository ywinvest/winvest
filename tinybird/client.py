import os
from dotenv import load_dotenv
from tinybird_sdk import Tinybird

from .tinybird_resources import (
    krx_daily_stocks,
    krx_daily_adjusted_stocks,
    krx_daily_indices
)

from .pipes.top_rs_stocks import top_rs_stocks
from .pipes.latest_rs_date import latest_rs_date
from .pipes.all_rs_stocks import all_rs_stocks

# Load environment variables
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

tinybird = Tinybird({
    "datasources": {
        "krx_daily_stocks": krx_daily_stocks,
        "krx_daily_adjusted_stocks": krx_daily_adjusted_stocks,
        "krx_daily_indices": krx_daily_indices
    },
    "pipes": {
        "top_rs_stocks": top_rs_stocks,
        "latest_rs_date": latest_rs_date,
        "all_rs_stocks": all_rs_stocks
    },
    "base_url": os.getenv("TINYBIRD_API_URL", "https://api.tinybird.co"),
    "token": os.getenv("TINYBIRD_TOKEN"),
})
