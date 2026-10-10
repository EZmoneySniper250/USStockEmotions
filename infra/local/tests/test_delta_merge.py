"""Guards the P6 pattern every Silver/Gold job relies on: MERGE on PK is idempotent."""


def test_merge_is_idempotent(spark, tmp_path):
    path = str(tmp_path / "posts")
    spark.createDataFrame([], "post_id STRING, likes INT").write.format("delta").save(path)
    src = spark.createDataFrame([("st:1", 3), ("st:2", 5)], "post_id STRING, likes INT")
    src.createOrReplaceTempView("src")

    merge_sql = f"""
        MERGE INTO delta.`{path}` t USING src s ON t.post_id = s.post_id
        WHEN MATCHED THEN UPDATE SET *
        WHEN NOT MATCHED THEN INSERT *
    """
    spark.sql(merge_sql)
    spark.sql(merge_sql)

    assert spark.read.format("delta").load(path).count() == 2
