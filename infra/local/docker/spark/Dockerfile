# PySpark 3.5 + Delta 3.2 + dbt-spark workspace image.
# Spark 3.5 / Delta 3.2 matches EMR 7.x, so local code runs unchanged on AWS later.
FROM python:3.11-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends openjdk-17-jre-headless curl procps git \
    && rm -rf /var/lib/apt/lists/* \
    # Arch-independent JAVA_HOME (amd64 and arm64/Apple Silicon)
    && ln -s "$(dirname "$(dirname "$(readlink -f "$(command -v java)")")")" /opt/java
ENV JAVA_HOME=/opt/java

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Bake extra jars into pyspark so nothing is downloaded at runtime.
# hadoop-aws must match the Hadoop version bundled with Spark 3.5 (3.3.4).
ARG MAVEN=https://repo1.maven.org/maven2
RUN cd "$(python -c 'import os, pyspark; print(os.path.join(os.path.dirname(pyspark.__file__), "jars"))')" \
    && curl -fsSLO ${MAVEN}/io/delta/delta-spark_2.12/3.2.1/delta-spark_2.12-3.2.1.jar \
    && curl -fsSLO ${MAVEN}/io/delta/delta-storage/3.2.1/delta-storage-3.2.1.jar \
    && curl -fsSLO ${MAVEN}/org/apache/hadoop/hadoop-aws/3.3.4/hadoop-aws-3.3.4.jar \
    && curl -fsSLO ${MAVEN}/com/amazonaws/aws-java-sdk-bundle/1.12.262/aws-java-sdk-bundle-1.12.262.jar \
    && curl -fsSLO ${MAVEN}/org/postgresql/postgresql/42.7.4/postgresql-42.7.4.jar

COPY docker/spark/spark-defaults.conf /opt/usse/conf/spark-defaults.conf
ENV SPARK_CONF_DIR=/opt/usse/conf \
    PYTHONPATH=/workspace/src \
    DBT_PROFILES_DIR=/workspace/dbt \
    TZ=UTC

WORKDIR /workspace
