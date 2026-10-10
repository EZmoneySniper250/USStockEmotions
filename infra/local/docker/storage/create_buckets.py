"""Create lake buckets (idempotent). usse-lake = real tables, usse-ci = CI / test runs only."""

import boto3

s3 = boto3.client("s3", endpoint_url="http://storage:9000")
existing = {b["Name"] for b in s3.list_buckets().get("Buckets", [])}
for bucket in ("usse-lake", "usse-ci"):
    if bucket not in existing:
        s3.create_bucket(Bucket=bucket)
    print(f"bucket ready: {bucket}")
