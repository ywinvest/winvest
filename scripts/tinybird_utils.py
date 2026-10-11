import os
import sys
import time
import tempfile
import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()

TINYBIRD_TOKEN = os.getenv("TINYBIRD_TOKEN")
TINYBIRD_API_URL = (os.getenv("TINYBIRD_API_URL") or "https://api.ap-east-1.aws.tinybird.co").rstrip("/")


def check_existing_records(datasource_name: str, target_date: str) -> int:
    """Check how many records already exist in Tinybird for target_date."""
    headers = {"Authorization": f"Bearer {TINYBIRD_TOKEN}"}
    params = {
        "q": f"SELECT count() as cnt FROM {datasource_name} WHERE date = '{target_date}' FORMAT JSON"
    }
    try:
        res = requests.get(
            f"{TINYBIRD_API_URL}/v0/sql",
            headers=headers,
            params=params,
            timeout=15,
        )
        if res.ok:
            data = res.json().get("data", [])
            if data:
                return int(data[0].get("cnt", 0))
    except Exception as e:
        print(f"⚠️ Failed to check existing records in {datasource_name}: {e}", flush=True)
    return 0


def delete_existing_records(
    datasource_obj, datasource_name: str, delete_condition: str, timeout: int = 30
):
    """Selectively delete existing records from Tinybird and poll job until complete."""
    print(f"🗑️ Deleting records from {datasource_name} ({delete_condition})...", flush=True)
    try:
        res = datasource_obj.delete({"delete_condition": delete_condition})
        job_url = res.get("job_url")
        if not job_url:
            print("✅ Delete request accepted without background job.", flush=True)
            return

        headers = {"Authorization": f"Bearer {TINYBIRD_TOKEN}"}
        start_poll = time.time()
        while time.time() - start_poll < timeout:
            job_res = requests.get(job_url, headers=headers, timeout=10)
            if job_res.ok:
                status = job_res.json().get("status")
                if status == "done":
                    print("✅ Existing records deleted successfully.", flush=True)
                    return
                elif status in ("error", "failed"):
                    print(f"❌ Delete job failed: {job_res.text}", flush=True)
                    sys.exit(1)
            time.sleep(1)
        print("⚠️ Delete job polling timed out; proceeding.", flush=True)
    except Exception as e:
        print(f"❌ Failed to delete existing records from {datasource_name}: {e}", flush=True)
        sys.exit(1)


def upload_parquet_to_tinybird(
    datasource_name: str, df: pd.DataFrame, session: requests.Session | None = None
) -> bool:
    """Convert dataframe to Parquet and upload to Tinybird via append mode."""
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tmp:
        df.to_parquet(tmp.name, index=False)
        tmp_path = tmp.name

    print(f"📤 Uploading {len(df):,} rows to Tinybird ({datasource_name})...", flush=True)
    upload_start = time.time()

    headers = {"Authorization": f"Bearer {TINYBIRD_TOKEN}"}
    params = {"name": datasource_name, "mode": "append", "format": "parquet"}
    sess = session or requests

    try:
        with open(tmp_path, "rb") as f:
            response = sess.post(
                f"{TINYBIRD_API_URL}/v0/datasources",
                headers=headers,
                params=params,
                files={"parquet": f},
                timeout=120,
            )
        response.raise_for_status()
        upload_elapsed = time.time() - upload_start
        print(f"✅ Upload successful in ⏱️ {upload_elapsed:.2f}s.", flush=True)
        return True
    except requests.exceptions.RetryError:
        print("❌ Upload failed: Max retries reached for 429 Rate Limit.", flush=True)
        sys.exit(1)
    except Exception as e:
        print(f"❌ Upload request failed: {e}", flush=True)
        sys.exit(1)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
