import os
from pathlib import Path
from dotenv import load_dotenv

# Resolve directory paths relative to the `app/` package
APP_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = APP_DIR.parent

load_dotenv(PROJECT_ROOT / ".env")

TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"

DATABASE_URL: str | None = os.getenv("DATABASE_URL")
TINYBIRD_API_URL: str = (
    os.getenv("TINYBIRD_API_URL") or "https://api.ap-east-1.aws.tinybird.co"
).rstrip("/")
TINYBIRD_TOKEN: str | None = os.getenv("TINYBIRD_TOKEN")

