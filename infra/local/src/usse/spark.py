"""SparkSession factory. All cluster/catalog config comes from spark-defaults.conf."""

from pyspark.sql import SparkSession


def get_spark(app_name: str) -> SparkSession:
    return SparkSession.builder.appName(app_name).enableHiveSupport().getOrCreate()
