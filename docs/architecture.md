# Data Infrastructure Architecture

Companion to `docs/data_platform_plan.md` (the source of truth). This file shows the infra as diagrams.
Diagrams are Mermaid and render on GitHub. Pre-rendered data flow: [`img/data_flow.png`](img/data_flow.png).

## 1. End-to-end data flow (Phase 1)

```mermaid
flowchart LR
    subgraph SRC[Sources]
        ST[StockTwits API<br/>no history, start early]
        RD[Reddit API<br/>WSB, stocks]
        PX[Hourly price vendor<br/>OPEN Q6]
    end

    subgraph ING[Ingestion - Python]
        FETCH[fetchers<br/>per source]
        SINK[Sink interface<br/>S3 now, Kafka in Phase 2]
        STATE[(brz._ingest_state<br/>cursor per source x endpoint)]
        FETCH --> SINK
        FETCH <--> STATE
    end

    subgraph BRZ[brz - Bronze, append-only, by ingest_date]
        RST[(raw_stocktwits)]
        RRD[(raw_reddit)]
        RPX[(raw_prices)]
    end

    subgraph SLV[slv - Silver, 3NF, MERGE on PK]
        POSTS[(posts)]
        MENT[(post_mentions<br/>post x entity)]
        LBL[(post_labels<br/>post x entity x label_version)]
        PR[(prices_1h)]
        REF[(dim_security SCD2<br/>dim_sector, etf_map)]
        OPS[(_quarantine<br/>_dq_results)]
    end

    subgraph LLMJ[LLM labeling job - separate batch]
        LJ[rate-limited worker<br/>Anthropic API / Bedrock]
    end

    subgraph GLD[gld - Gold, Kimball, dbt-spark]
        DIMS[(dim_date, dim_time_bucket,<br/>dim_entity, dim_source,<br/>dim_label_version, dim_topic, ...)]
        FPS[(fct_post_sentiment<br/>atomic)]
        AGG[(agg_ticker / sector / market<br/>_sentiment_4h)]
        FPX[(fct_price_4h)]
        SCORE[(fct_score)]
        ALERT[(fct_alert<br/>fct_alert_outcome)]
        RUN[(fct_agent_run)]
        OBT[(obt_ticker_4h, vw_*)]
    end

    subgraph USE[Consumers]
        AGENT[Agent<br/>read-only, Gold only]
        ML[Linan models<br/>obt_ticker_4h_train]
        GROK[Grok x_search<br/>agent tool only]
    end

    ST & RD & PX --> FETCH
    SINK --> RST & RRD & RPX

    RST & RRD -->|PySpark: parse, dedup,<br/>UTC, spam flags| POSTS
    POSTS -->|PySpark: cashtag + ETF map| MENT
    REF -.as-of join.-> MENT
    RPX -->|PySpark| PR
    MENT -->|rows missing current<br/>label_version| LJ
    LJ -->|append| LBL
    MENT -.unmapped / bad rows.-> OPS

    SLV ==>|dbt-spark: Silver tables as sources| DIMS
    DIMS --> FPS & FPX
    FPS --> AGG
    AGG & FPX --> SCORE
    SCORE --> ALERT
    ALERT --> OBT
    OBT --> AGENT & ML
    AGENT --> RUN
    GROK -.context.-> AGENT
```

## 2. Local runtime (docker compose)

```mermaid
flowchart TB
    subgraph HOST[Developer laptop]
        REPO[infra/local mounted at /workspace]
        subgraph DC[docker compose project: usse, infra/local/docker-compose.yml]
            SPARK[spark<br/>Python 3.11, PySpark 3.5.3,<br/>Delta 3.2.1, dbt-spark session<br/>Spark UI :4040]
            STORE[storage<br/>RustFS 1.0.0, S3-compatible<br/>S3 :9000, console :9001]
            INIT[storage-init<br/>boto3: creates buckets, exits]
            PG[metastore-db<br/>Postgres 16<br/>Hive 2.3 schema, pre-initialized]
        end
    end
    REPO --- SPARK
    SPARK -->|s3a://usse-lake, s3a://usse-ci| STORE
    SPARK -->|JDBC: table catalog| PG
    INIT --> STORE

    subgraph BUCKETS[Buckets]
        L[usse-lake<br/>brz/ slv/ gld/ = real tables]
        C[usse-ci<br/>ci_brz/ ci_slv/ ci_gld/ = CI + tests only]
    end
    STORE --- BUCKETS
```

| Local component | AWS equivalent (Plan 3.2) | What changes on migration |
|---|---|---|
| RustFS (S3-compatible) | S3 | `fs.s3a.endpoint` + credentials provider |
| Postgres-backed Hive metastore | Glue Data Catalog | catalog config lines in `spark-defaults.conf` |
| `spark` container, `local[*]` | EMR Serverless (Spark 3.5, EMR 7.x) | job submission wrapper |
| Anthropic API | Bedrock | LLM client config in labeling job |
| `docker compose` | Terraform | new `infra/` module |

## 3. Environment isolation

```mermaid
flowchart LR
    DEV[Local dev runs<br/>USSE_SCHEMA_PREFIX=''] --> REAL[(brz / slv / gld<br/>s3a://usse-lake)]
    PYTEST[pytest unit tests] --> TMP[(in-memory catalog<br/>temp dir Delta)]
    CI[CI + dbt --target ci<br/>USSE_SCHEMA_PREFIX=ci_] --> CIS[(ci_brz / ci_slv / ci_gld<br/>s3a://usse-ci)]
    AGENTR[Agent] -->|read-only| GOLDV[(gld.vw_* / obt_*)]
```

## 4. Daily batch sequence (target state, Phase 1)

```mermaid
sequenceDiagram
    autonumber
    participant CRON as Scheduler (cron, later Airflow)
    participant ING as Ingestion
    participant BZ as brz
    participant SP as PySpark jobs
    participant SV as slv
    participant LJ as Labeling job
    participant DBT as dbt build
    participant GD as gld
    participant DQ as _dq_results

    loop every N minutes
        CRON->>ING: poll StockTwits / Reddit
        ING->>BZ: append raw JSON (+ update _ingest_state)
    end
    CRON->>SP: every 4h, after bucket closes
    SP->>BZ: read new ingest_date partitions
    SP->>SV: MERGE posts, post_mentions, prices_1h
    SP->>DQ: PK uniqueness, ts sanity, mapping rate, volume drop
    CRON->>LJ: label rows missing current label_version
    LJ->>SV: append post_labels
    CRON->>DBT: dbt build (dims -> facts -> aggs -> score -> alerts -> obt)
    DBT->>GD: MERGE incremental models, run tests
```
