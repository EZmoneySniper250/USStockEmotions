# USStockEmotions — Local Data Platform

Retail-investor sentiment → point-in-time signals → rule-based alerts with an explaining agent.

| Doc | What |
|---|---|
| [`docs/data_platform_plan.md`](../../docs/data_platform_plan.md) | Source of truth: rules, layers, table contracts. **Coding agents: read §2 and §11 first.** |
| [`docs/architecture.md`](../../docs/architecture.md) | Infra diagrams (data flow, local runtime, env isolation, batch sequence) |
| [`docs/dev_plan.md`](../../docs/dev_plan.md) | Milestones, per-table workflow, git/CI process, open-question blockers |

## Quick start (local)

Requires Docker Desktop (~6 GB RAM free). Run everything from this folder (`infra/local/`).

```bash
cp .env.example .env
docker compose up -d --build                              # storage + metastore + spark
docker compose exec spark python scripts/smoke_delta.py   # expect: OK rows=3 ...
docker compose exec spark pytest -q
```

JupyterLab: http://localhost:8888 (token = `JUPYTER_TOKEN` in `.env`). Start with `notebooks/00_getting_started.ipynb`.
Notebooks are for exploration only; see `docs/deltaprinciples.md` §2.

Stack: PySpark 3.5.3 + Delta 3.2.1 (matches EMR 7.x) · RustFS (S3-compatible, `s3a://usse-lake`, `s3a://usse-ci`)
· Postgres-backed Hive metastore (Glue stand-in) · dbt-spark (session method, targets `dev` / `ci`).

On Git Bash for Windows, prefix `docker compose exec` with `MSYS_NO_PATHCONV=1` so paths aren't rewritten.

## Where to write things

| What | Where |
|---|---|
| Bronze/Silver table schema | `contracts/<layer>/<table>.yml` (copy `contracts/_template.yml`) |
| Bronze/Silver job | `src/usse/jobs/<layer>/<table>.py` + `tests/jobs/test_<table>.py` |
| Gold model | `dbt/models/gld/<group>/<model>.sql` + `_<group>.yml` (contract enforced) |
| Reference data | `seeds/*.csv` |
| Exploration | `notebooks/*.ipynb` (clear outputs before commit) |

Full table: `docs/data_platform_plan.md` §3.4.
