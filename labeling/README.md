# labeling/ — label specification

**Owners:** Linan + Jaylen · **Reviewer for changes:** Jerry (anything that changes `slv.post_labels` columns)

This folder holds the **specification** of what the LLM labels. The labeling **job** (batching, rate limits, retries, writes to `slv.post_labels`) is infra code owned by Jerry in `infra/local/src/usse/labeling/`, and it reads its inputs from here.

| Path | Owner | Content |
|---|---|---|
| `taxonomy/topics.yml` | Jaylen | Topic taxonomy for `post_labels.topic` (Plan Q5). Each topic: id, name, definition, examples |
| `schema/label_output.json` | Linan + Jaylen | JSON schema of one label: sentiment ∈ [-1, 1], stance ∈ {bull, bear, neutral}, topic, confidence |
| `prompts/<label_version>.md` | Linan + Jaylen | One file per prompt version. **Never edit a released version**: copy it to a new version (P5) |
| `spot_checks/` | Jaylen | Hand-labeled samples and agreement reports used to accept a new `label_version` |

Rules:
- Content classification only. Prompts must never ask about price or market impact (P7).
- A new prompt or taxonomy version means a new `label_version`; old labels stay (P5).
- Do not write code here that calls the LLM; the job in `infra/local` does that (P11).
