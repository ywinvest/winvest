from tinybird_sdk import define_token

# Token for data ingestion scripts (APPEND access)
ingest_token = define_token("ingest_token")

# Token for application read access (READ access)
app_token = define_token("app_token")
