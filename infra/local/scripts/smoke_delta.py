"""Step 1 smoke test: Spark + Delta + S3 storage + metastore working end to end.

Checks: schemas exist at lake locations, Delta write via catalog, MERGE is idempotent
(P6), time travel works, table is visible from a fresh session (shared metastore).

Run: docker compose exec spark python scripts/smoke_delta.py
"""

from usse import bootstrap
from usse.settings import load_settings
from usse.spark import get_spark


def main() -> None:
    bootstrap.main()
    settings = load_settings()
    spark = get_spark("usse-smoke")
    table = f"{settings.schema('slv')}._smoke_test"

    spark.sql(f"DROP TABLE IF EXISTS {table}")
    spark.sql(f"CREATE TABLE {table} (post_id STRING, likes INT, ingest_ts TIMESTAMP) USING DELTA")

    rows = [("st:1", 3), ("st:2", 5), ("rd:9", 1)]
    spark.createDataFrame(rows, "post_id STRING, likes INT").createOrReplaceTempView("src")

    merge_sql = f"""
        MERGE INTO {table} t
        USING (SELECT post_id, likes, current_timestamp() AS ingest_ts FROM src) s
        ON t.post_id = s.post_id
        WHEN MATCHED THEN UPDATE SET t.likes = s.likes
        WHEN NOT MATCHED THEN INSERT *
    """
    spark.sql(merge_sql)
    spark.sql(merge_sql)  # re-run must not duplicate

    count = spark.table(table).count()
    assert count == 3, f"MERGE not idempotent: expected 3 rows, got {count}"

    location = spark.sql(f"DESCRIBE DETAIL {table}").first()["location"]
    assert location.startswith("s3a://"), f"table not on object storage: {location}"

    versions = spark.sql(f"DESCRIBE HISTORY {table}").count()
    v0 = spark.read.format("delta").option("versionAsOf", 0).load(location).count()
    assert v0 == 0, "time travel to version 0 should be empty"

    spark.stop()

    # Fresh session: table must be visible through the shared metastore.
    spark = get_spark("usse-smoke-reopen")
    assert spark.table(table).count() == 3
    spark.sql(f"DROP TABLE {table}")
    spark.stop()

    print(f"OK  rows={count} versions={versions} location={location}")


if __name__ == "__main__":
    main()
