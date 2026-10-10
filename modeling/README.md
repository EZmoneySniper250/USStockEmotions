# modeling/ — scores, alert rules, model training, validation

**Owner:** Linan · **Reviewers:** Jaylen (hypotheses), Jerry (anything that becomes a Gold table)

| Path | Content |
|---|---|
| `rules/` | Score and alert rule specs: meaning (Plan Q1), components, weights, thresholds, windows, version. A spec becomes `dim_score_model` / `dim_alert_rule` rows |
| `training/` | Model training code |
| `validation/` | Rank IC, forward-return evaluation, backtests |
| `notebooks/` | Exploration only; nothing in production imports from here |

Interfaces with the data platform:
- **Read** Gold only: `gld.obt_ticker_4h`, `gld.obt_ticker_4h_train`, and Gold facts/dims. Never read `brz` / `slv`.
- Production score/alert logic is implemented as dbt models in `infra/local/dbt/models/gld/scoring/` and `.../alerting/`. Linan owns those two folders and Jerry reviews them. Specs live here, SQL lives there.
- Point-in-time (P3): features for time T use only rows with `available_ts <= T`. Forward returns appear only in `*_train` tables and `fct_alert_outcome`.
