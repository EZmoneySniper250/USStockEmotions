# Delta Principles — concepts, workflow, and the path to EMR

Audience: team members coming from SQL Server / Azure SQL / Postgres. Q&A format.
Related: `data_platform_plan.md` (rules), `dev_plan.md` (milestones), `architecture.md` (diagrams).

---

## 1. What is Delta?

### 1.1 Is Delta a pattern, a database, or what?

Neither a pattern nor a database. **Delta Lake is an open table format**: a specification for storing a table as files so that it behaves like a database table (ACID, versions, schema).

- **Medallion (brz → slv → gld) is an architecture pattern.** You can build it in T-SQL, in Delta, or anywhere.
- **Delta is how each individual table is stored.** In this project, every table in every layer is a Delta table.

One Delta table is one directory:

```
s3a://usse-lake/slv/posts/            <- one Delta table = one directory
├── part-0001-....parquet             <- data files (Parquet, columnar)
├── part-0002-....parquet
└── _delta_log/                       <- transaction log: the source of truth
    ├── 00000000000000000000.json     <- version 0: CREATE TABLE (schema lives here)
    ├── 00000000000000000001.json     <- version 1: "add these files, remove those files"
    └── 00000000000000000010.checkpoint.parquet   <- periodic snapshot of the log
```

The log is the table. A file in the directory that no log entry references is invisible to readers.

Delta does no compute. **Engines** read and write it: Spark (us), Databricks, Athena, Trino, and others. Databricks is just the best-known engine; Delta itself is open source.

### 1.2 How is it different from T-SQL / Postgres?

| | Azure SQL / Postgres | Delta + Spark |
|---|---|---|
| Architecture | Storage + compute in one server | **Storage and compute separated**: files on S3, Spark started on demand |
| Version history | Like SQL Server system-versioned (temporal) tables, if you enable them | Every write creates a version automatically: `SELECT * FROM t VERSION AS OF 3` / `TIMESTAMP AS OF '...'` |
| Transaction scope | `BEGIN TRAN` can span many tables | **ACID per table only.** No multi-table transactions, so every job must be safe to re-run (idempotent, P6) instead of relying on a rollback |
| Constraints | PK / FK / UNIQUE enforced | Only `NOT NULL` and `CHECK`. **No PK/FK/UNIQUE.** Uniqueness comes from MERGE on the key (P6) plus DQ checks and dbt tests |
| Wrong column on insert | Error | Also an error: Delta enforces the schema on write and rejects mismatched writes |
| Indexes | B-tree indexes | None. Partitioning + data skipping (min/max stats per file) + optional Z-order |
| Stored procs / triggers | Yes | No. Logic lives in Spark jobs and dbt models |
| `UPDATE` one row | In place | Rewrites the affected Parquet file(s); the log marks old files removed, new files added |
| Old versions | — | Kept until `VACUUM` deletes unreferenced files (default retention 7 days). After VACUUM, time travel to those versions is gone |
| Schema change | `ALTER TABLE` | `ALTER TABLE ... ADD COLUMNS`; recorded as a new version |

### 1.3 Concurrency control

SQL Server is **pessimistic** by default: row/page/table locks, blocking, deadlocks. Delta is **optimistic**:

1. **Readers** pick the latest version N when the query starts and read that snapshot. Concurrent writes don't affect them. This is snapshot isolation (like SQL Server with RCSI): **readers never block and are never blocked.**
2. **Writers:**
   - Read version N and write new Parquet files. Nobody can see these files yet.
   - Commit by atomically creating `_delta_log/N+1.json`.
   - If another writer already created `N+1`, Delta checks for a logical conflict. If there is none (e.g. two appends), it retries the commit as `N+2` automatically. If there is one (both touched the same files), it throws `ConcurrentModificationException` and the job must retry.
3. No locks means no deadlocks. The cost is that conflicts surface as failed commits.

**S3 caveat.** Step 2's commit needs storage that supports "create only if absent." With Delta 3.2 on S3, the default log store guarantees this only **within one Spark driver**. Two different clusters writing the same table at the same time can corrupt the log unless the DynamoDB LogStore is configured.

**Project rule: one writer job per table.** Ingestion writes Bronze, one Spark job per Silver table, dbt writes Gold. Under that rule the caveat doesn't bite.

### 1.4 Do I create tables with `CREATE TABLE`, like Postgres?

You *can*:

```sql
CREATE TABLE IF NOT EXISTS slv.posts (
  post_id    STRING    NOT NULL,
  created_ts TIMESTAMP NOT NULL
) USING DELTA
```

or implicitly from a DataFrame: `df.write.format("delta").saveAsTable("slv.posts")` (schema taken from the DataFrame).

What happens underneath is different from Postgres. There is no server holding the table. The **catalog** (Postgres-backed Hive metastore locally, Glue on AWS) only maps the name `slv.posts` to a directory. The schema itself is in `_delta_log`.

**How we create tables in this project:**

| Layer | Who creates the table | What you write |
|---|---|---|
| Bronze / Silver | `ensure_table(contract)` (dev plan M1) reads the contract YAML and runs `CREATE TABLE IF NOT EXISTS ... USING DELTA` | Only `infra/local/contracts/<layer>/<table>.yml`. **No hand-written DDL** (Plan Rule 17) |
| Gold | dbt, from the model `.sql` + contract `.yml` (`+file_format: delta`) | The dbt model and its YAML |

Always write `USING DELTA` explicitly (Plan Rule 16). Without it, Spark 3.5 with Hive support would create a Hive table that silently looks fine. `spark.sql.sources.default=delta` is set as a safety net; the explicit clause is still required.

---

## 2. Where does Spark code go, and what is the daily workflow?

### 2.1 Where to write Spark

| Purpose | Location | Format |
|---|---|---|
| **Production jobs** | `infra/local/src/usse/jobs/<layer>/<table>.py` | `.py`: a pure `transform(df) -> df` + a thin `run()` that reads, transforms, MERGEs |
| Tests | `infra/local/tests/jobs/test_<table>.py` | pytest with small hand-written DataFrames |
| **Exploration / debugging** | `infra/local/notebooks/` | `.ipynb`, run in JupyterLab inside Docker |

**Notebooks are for exploration only.** Once logic works, move it into a `.py` module with tests, and have the notebook import it (`from usse.jobs.slv.posts import transform`). Reasons: notebooks are hard to unit test, PR diffs are unreadable, CI can't run them, and out-of-order cell execution breaks reproducibility. Clear outputs before committing.

### 2.2 Do I need Docker to test in Jupyter?

**Yes, on this team's setup.** JupyterLab runs inside the `spark` container.
- Anything touching real tables (`brz`/`slv`/`gld`) needs the storage + metastore containers anyway.
- Running PySpark directly on Windows to write local Delta/Parquet needs extra Hadoop native binaries (`winutils.exe`, `hadoop.dll`) and a matching JDK, which is fragile.

Running Jupyter in the container gives every teammate the exact environment the jobs use: same Spark, Delta, jars, and config.

- Start: `docker compose up -d` (from `infra/local/`)
- Open: http://localhost:8888, token = `JUPYTER_TOKEN` in `.env`
- Example: `notebooks/00_getting_started.ipynb` (schemas, versions, time travel)
- Spark UI: http://localhost:4040 (notebook session), 4041 (a second session, e.g. a job run via `exec`)

### 2.3 Will Spark/Delta pick up and run my code automatically?

**No.** This is not Databricks: there are no Jobs, Workflows or DLT watching anything, and Delta itself never runs code. Jobs run when someone or something starts them:

| Phase | How jobs run |
|---|---|
| Now | By hand: `docker compose exec spark python -m usse.jobs.slv.posts` |
| M4+ | One `run_pipeline` entrypoint (Silver jobs → labeling → `dbt build`) on cron every 4h |
| AWS | Step Functions (or Airflow) calling EMR jobs |

(Spark Structured Streaming *can* read a Delta table incrementally with `spark.readStream.format("delta")`, a bit like DLT. Phase 1 uses batch + watermarks instead; streaming is not needed.)

### 2.4 Workflow for one table

```
1. Contract      contracts/slv/posts.yml        grain, PK, columns (review first)
2. Explore       notebooks/                     optional: try parsing on Bronze samples
3. Tests         tests/jobs/test_posts.py       hand-written input -> expected output (fails first)
4. Transform     src/usse/jobs/slv/posts.py     pure function until pytest is green
5. run()         read brz -> transform -> MERGE into slv on PK
6. Trial run     USSE_SCHEMA_PREFIX=ci_ USSE_LAKE_ROOT=s3a://usse-ci python -m usse.jobs.slv.posts
                 -> writes ci_slv.posts, never the real table
7. Inspect       notebook / spark-sql; run step 6 again: same row count (idempotent)
8. PR            CI (ruff, pytest, dbt parse) + owner review
9. Real run      default env -> slv.posts; add the job to run_pipeline
```

It is the same loop as "create table, write the stored proc, run it, check results" in T-SQL. The logic lives in Python instead of procs, trial runs go to an isolated `ci_` environment, and every step has tests.

---

## 3. Moving to AWS EMR — same approach?

**Same code, different config and submission.** That is why versions are pinned to EMR 7.x and every path and schema comes from settings.

| | Local | EMR | Change |
|---|---|---|---|
| Job code `src/usse/` | same | same | **none** |
| dbt models | same | same | **none** |
| Storage | RustFS, `s3a://usse-lake` | S3 (`s3://bucket`, EMR's recommended scheme) | `USSE_LAKE_ROOT` only |
| Catalog | Postgres-backed Hive metastore | Glue Data Catalog | EMR configuration (Glue as metastore) |
| Delta | jars baked into the image | bundled with EMR, enabled via `delta-defaults` | config |
| Credentials | keys in `.env` | IAM role | drop the keys |
| How a job runs | `docker compose exec ... python -m ...` | `usse` built as a wheel → S3 → EMR Serverless `StartJobRun` | new submit wrapper |
| Scheduling | by hand / cron | Step Functions or Airflow | new |
| Notebooks | JupyterLab in Docker | EMR Studio | — |
| Infra | docker compose | Terraform (`infra/aws/`) | new |

**Decide in M8: how dbt runs on EMR.** Locally dbt uses `method: session` (in-process Spark). On EMR, the options are:
- **EMR on EC2 + Spark Thrift Server**, with dbt using `method: thrift`. Most mature.
- **EMR Serverless**, with dbt wrapped as a Spark job.

Either way only `profiles.yml` gains a target; the models don't change.

**Roles of the two environments:** local Docker is for development and testing; EMR is for production. Write and test locally, merge, deploy, run on EMR.

---

## 4. Rules recap (from `data_platform_plan.md` §11)

| Rule | Summary |
|---|---|
| 16 | Every table is Delta; write `USING DELTA` explicitly |
| 17 | Bronze/Silver DDL only from contracts; Gold DDL only from dbt |
| P6 / 3 | All Silver/Gold writes are MERGE on the declared PK |
| — | One writer job per table (§1.3 S3 caveat) |
| 11 | Tests and trial runs go to `ci_` schemas on `s3a://usse-ci` |
| 20 | Notebooks are exploration only; production code is `.py` with tests |
