# grokbot X collection spec

Version: v1.3 (2026-10-15). Owner: jerry. v1.3 applies the 2026-10-15 trial results: `response_trailer` for the non-JSON quota line, `params` and `endpoint` record what was actually sent, `fetched_at` tolerance of 10 s, the 1024-character query limit, the list file format with reason codes and a query budget for the blacklist (§3.2, §3.3), and run cadence plus coverage for capped chains (§3.4). v1.2 adapted the envelope to what grokbot can actually see (§4.1): `response` is the tool's wrapped response kept as is, `call_status` and `quota` replace `http_status` and `rate_limit`, and timestamps are taken right around the call. v1.1 added query-level spam filtering, the three streams (§3), white/blacklist versioning, per-run page caps, and matches grokbot's quota model (one call = one page of up to 25 posts).

This is what USStockEmotions needs from grokbot when it collects posts from X. grokbot is free to choose how it schedules, retries and stores state. This document fixes only **what goes into the output files**. Our loader reads those files into `brz.x_raw_search` (see `infra/local/contracts/brz/x_raw_search.yml`).

Requirements are labelled **MUST** (we cannot load or trust the data without it) and **SHOULD** (nice to have, add it when practical).

## 1. Why these rules exist

Everything downstream is a backtest, so data has to be **point-in-time correct**: for every post we must know when we could first have seen it, and which question we asked X to get it. The raw X API response does not carry the request or the fetch time, so grokbot has to record them. We also need to tell "nobody posted" apart from "the collector was down", and we need to know how much of the real stream each page covers.

## 2. What to call

- **MUST** call X API v2 search (`GET /2/tweets/search/recent`, or `/2/tweets/search/all` when backfilling).
- **Filtering rule.** Filter only **inside the query string**, so X drops posts on the server side. This costs no quota, and because the query is recorded, the filter can be reproduced. **MUST NOT** filter, rerank, summarise or drop posts after they come back, whether by a model or by rules. Pass the response through exactly as the tool returned it (§4.1). Post-fetch spam scoring happens on our side, in Silver.
- **Quota model.** One call returns one page of up to 25 posts and costs one unit, whether it returns 0 or 25 posts. So the cost levers are: fewer queries (merge accounts and tickers into one query with `OR`), tighter query filters, and never reading the same window twice.
- **MUST** use `sort_order=recency` and the largest page size the tool allows (25 today). Record the actual value in `params.max_results`.
- **MUST** read incrementally: for each query, set `since_id` to the `newest_id` from the previous run, then follow `next_token` until there are no more pages **or** the per-run page cap (§3.4) is reached. Stopping early without recording it turns the data into a silent sample (at 25 posts per page, `$SPY OR $QQQ` covers only about 33 minutes).

### Request fields

Adding fields costs no extra requests. Ask for all of them. The parameter names below are X's; if the tool names them differently (grokbot's tool uses `post.fields` instead of `tweet.fields`), send the tool's name and record **that** name in `params`.

| Parameter | Value |
|---|---|
| `tweet.fields` | `id,text,created_at,author_id,lang,conversation_id,entities,public_metrics,note_tweet,referenced_tweets,in_reply_to_user_id,edit_history_tweet_ids,possibly_sensitive,context_annotations` |
| `user.fields` | `id,username,name,created_at,public_metrics,verified,verified_type,description,protected` |
| `expansions` | `author_id,referenced_tweets.id,referenced_tweets.id.author_id` |

Why these matter:
- `entities.cashtags` is how we map posts to tickers. It is more reliable than regex. Pages can come back without it (§4.1), in which case Silver falls back to regex; ask for it anyway.
- `note_tweet` holds the full text of long posts. Without it, `text` is cut off.
- `lang` lets us route posts to the right sentiment model.
- `conversation_id` lets us group posts into threads.
- `public_metrics` (post and author) gives engagement weights. Note that these are snapshots taken at fetch time, which is one more reason `fetched_at` is required.
- Author `created_at`, `public_metrics` and `verified_type` feed spam filtering. New accounts posting 40 cashtags are a known pattern.
- `referenced_tweets.id` expansions put quoted and replied-to posts in `includes.tweets`. A quote often makes sense only next to the original.
- `context_annotations` (SHOULD) helps with tickers that are also ordinary words, such as `$GM`.

## 3. Queries and streams

- **MUST** record the exact query string sent to X.
- **MUST** build queries from versioned lists (watchlist, whitelist, blacklist) and record the versions used (`watchlist_version`, `whitelist_version`, `blacklist_version`).
- Keep each query within **1024 characters** (confirmed in the 2026-10-15 trial). Split a long list into several queries (`-q01a`, `-q01b`, …) rather than truncating it. In practice, 82 `from:` terms need two queries.
- `query_id` **MUST** start with the stream name: `kol-…`, `kol_replies-…` or `crowd-…`.

### 3.1 Streams

There are three streams. They answer different questions, so all three are collected and kept apart by `query_id`.

| Stream | What it is | Query template |
|---|---|---|
| `kol` | Original posts from whitelisted investors | `(from:A OR from:B OR …) -is:retweet -is:reply` |
| `kol_replies` | Replies to whitelisted investors (the comment sections) | `(to:A OR to:B OR …) is:reply -is:retweet -has:links (lang:en OR lang:zh) <blacklist>` |
| `crowd` | Retail chatter about watchlist tickers. **This is the main signal and must not be replaced by the whitelist.** | `($SPY OR $QQQ OR …) -is:retweet -is:nullcast (lang:en OR lang:zh) <blacklist> <spam keywords>` |

- `<blacklist>` is `-from:x -from:y …` built from the blacklist (known bots and spam accounts, e.g. `-from:grok`).
- `<spam keywords>` is a versioned list of negated phrases, e.g. `-"airdrop" -"giveaway" -"join my telegram" -"discord.gg"`.
- `-has:links` also drops posts with images (chart screenshots are common in finance posts), so it is used only on `kol_replies`, never on `kol` or `crowd`.
- `to:` and `-is:nullcast` both work (confirmed 2026-10-15). If `to:` stops working, fall back to `(@A OR @B OR …) is:reply`, which is looser because it also matches replies that merely mention the account. If `-is:nullcast` stops working, drop it. The recorded `query` always shows what was actually sent.
- Batch accounts into one query (dozens of `from:` / `to:` terms) rather than one query per account.

### 3.2 List files

All lists are kept in the USStockEmotions repo, under `infra/local/config/x_lists/`, which is their source of truth:

| File | What it holds |
|---|---|
| `whitelist.yml` | Accounts for `kol` and `kol_replies` |
| `blacklist.yml` | Accounts excluded with `-from:`, and spam keywords excluded with `-"…"` |
| `watchlist.yml` | Tickers for `crowd` (to be added; see plan Q2 / Q7) |

Every file has a top-level `version` (`v1`, `v2`, …), bumped on every change. The `*_version` fields in each envelope must match the version of the file that built the query.

Each account entry has these fields:

```yaml
- username: stockRichard11      # as of when it was added; accounts can be renamed
  user_id: "1234567890"         # MUST; the stable key, looked up when the entry is added
  added_on: 2026-10-15
  removed_on: null              # set a date instead of deleting the entry
  reason_code: scam             # blacklist only: scam | promo | bot
  reason: "WhatsApp stock-group invites"
  in_query: true                # blacklist only: false = applied in Silver, not in the query
```

- **MUST** match accounts by `user_id`. Usernames change, and spam accounts rename often.
- **MUST NOT** delete entries. Set `removed_on` instead.

### 3.3 Whitelist and blacklist rules

**Whitelist.** The whitelist is chosen today, from people who are famous today, and using today's list on past data is look-ahead bias. That is why `added_on` and `removed_on` exist: a backtest may only use the accounts that were active on each date.

**Blacklist.** Its job is to save quota on known heavy hitters. The real spam defence happens in Silver (username patterns, account age, cashtag stuffing, near-duplicate text).

- **Evidence.** Add an account only on behavioural evidence, such as scam invites, traffic redirection or automated signals. High volume alone is not evidence. Every entry carries one `reason_code`:
  - `scam`: stock-group or DM scams (WhatsApp or Telegram "join my group", "contact me")
  - `promo`: follow or traffic redirection, paid promotion
  - `bot`: automated signal or repost accounts. These are not malicious, but they are not retail sentiment either.
- **Query budget.** Tickers, keywords and blacklist entries share the 1024-character limit, and each `-from:xxx` costs about 18 characters. So only entries with `in_query: true` go into the query: the highest-volume offenders, about 20–30 per query. All other entries have `in_query: false` and are applied in Silver only.
- **Keywords.** Use phrases, not single words that also show up in real news (`"WhatsApp"` alone would drop $META news). Before adding a keyword, run one control page without it, as was done for `-has:links`, and check what it removes.
- **Effect.** Changes take effect from the next run. Past data is never refetched; instead, Silver applies the current blacklist to past data as a flag and deletes nothing.
- **Rings.** Account rings such as `stock<Name><digits>` rotate faster than a blacklist can follow. List the worst offenders and leave the pattern itself to Silver.

### 3.4 Page cap, cadence and coverage

- **MUST** apply a per-query, per-run page cap (default 10 pages). When the cap stops a chain that still has a `next_token`, record `exhausted: false` in the manifest. This marks a deliberate sample, so downstream knows that window is incomplete.
- **SHOULD** run often with a small cap rather than rarely with a large one: for example, every 15 minutes with 1–2 pages per query, rather than every 2 hours with 5. In the 2026-10-15 trial, 3 pages of `kol_replies` covered only 4–21 minutes of a 2-hour window. Frequent small runs spread the sample evenly over time.
- How downstream uses this: when a chain is not exhausted, raw post counts do not measure volume, because a busier ticker gets a shorter covered window from the same number of pages. Silver therefore computes the covered window of each chain (oldest to newest `created_at`) and reports volume as posts per covered minute.

## 4. Output: one envelope per page

Every API call (every page) produces exactly one JSON object. The X response goes inside it unchanged.

```json
{
  "envelope_version": 1,
  "collector": "grokbot",
  "collector_version": "0.3.1",
  "run_id": "20261014T140000Z-a1b2c3",
  "request_id": "6f1c0f7e-3b2a-4c55-9d0e-2a7b1f9e8c41",
  "query_id": "crowd-q07",
  "page_index": 0,
  "requested_at": "2026-10-14T14:00:03.101Z",
  "fetched_at": "2026-10-14T14:00:03.512Z",
  "endpoint": "grokbot:search_posts_all",
  "query": "($SPY OR $QQQ) -is:retweet",
  "params": {
    "since_id": "1846012345678901234",
    "start_time": null,
    "end_time": null,
    "sort_order": "recency",
    "max_results": 25,
    "pagination_token": null,
    "post.fields": "...",
    "user.fields": "...",
    "expansions": "..."
  },
  "watchlist_version": "v3",
  "whitelist_version": "v1",
  "blacklist_version": "v1",
  "call_status": "ok",
  "error_message": null,
  "http_status": null,
  "quota": { "remaining_per_minute": 58, "remaining_per_day": 940 },
  "response_format": "grokbot_x_v2_wrapped_v1",
  "notes": null,
  "response_trailer": "<the non-JSON quota line exactly as returned, or null>",
  "response": {
    "data": [],
    "includes": { "users": [], "tweets": [] },
    "meta": { "result_count": 0, "newest_id": null, "oldest_id": null, "next_token": null },
    "errors": []
  }
}
```

| Field | Req | Meaning |
|---|---|---|
| `envelope_version` | MUST | Schema version of this envelope. Starts at `1`; bump it when the shape changes. |
| `collector` | MUST | Always `"grokbot"`. |
| `collector_version` | MUST | grokbot version or git sha, so we can trace bugs to a release. |
| `run_id` | MUST | One id per scheduled run. All pages from one run share it. |
| `request_id` | MUST | Unique per API call (UUID). This is our dedupe key: a page reloaded twice must keep the same `request_id`. |
| `query_id` | SHOULD | Stable id for the query across runs, so we can track one query over time. |
| `page_index` | MUST | 0-based position within the pagination chain for this query in this run. |
| `requested_at` | SHOULD | UTC time taken immediately before the call. |
| `fetched_at` | MUST | UTC time taken immediately after the call returned, within 10 s of the true arrival time. **This is our point-in-time timestamp.** It is slightly later than the true arrival time, which is the safe direction. |
| `endpoint` | MUST | What was actually called: an X path (`tweets/search/recent`, `tweets/search/all`) or, when the call goes through a tool layer, `<collector>:<tool name>` (e.g. `grokbot:search_posts_all`). |
| `query` | MUST | Exact query string sent. |
| `params` | MUST | Every other parameter actually sent, **under the names actually sent** (e.g. `post.fields` rather than `tweet.fields` if that is what the tool takes), including the `pagination_token` used for **this** page (null for page 0) and `since_id` / `start_time` / `end_time`. Write keys you did not send as `null`; do not leave them out. |
| `watchlist_version` / `whitelist_version` / `blacklist_version` | MUST | Versions of the lists that built the query (null if the stream does not use that list). |
| `call_status` | MUST | `ok`, `error` or `timeout`. |
| `error_message` | MUST | Error text when `call_status` is not `ok`; otherwise null. |
| `http_status` | SHOULD | Real HTTP status code if the collector can see it; otherwise null. |
| `quota` | SHOULD | Whatever quota information the collector can see (e.g. remaining calls per minute and per day), as a flat object. Null if none. |
| `response_format` | MUST | Names the shape of `response`, so the loader knows how to parse it. grokbot today: `grokbot_x_v2_wrapped_v1` (§4.1). Bump the suffix whenever the wrapper changes. |
| `notes` | SHOULD | Free text for anything unusual (partial page, manual rerun, filtering). Otherwise null. |
| `response` | MUST | The JSON part of the response exactly as the tool returned it, including `errors` if present. Do not rename, reorder, trim or reformat fields, and do not strip fields the wrapper added. |
| `response_trailer` | MUST | Any non-JSON text the tool returned after the JSON (for grokbot, one quota line), kept verbatim. Null if there was none. Do not put it in `notes`. `quota` may hold values parsed from it. |

### 4.1 Known collector limits (grokbot, updated 2026-10-15)

grokbot reaches X through a tool layer, not the raw HTTP API. These limits are accepted:

| Limit | How the spec handles it |
|---|---|
| The response is wrapped: each post has an extra `url` field, extra fields such as `article` and `withheld` can appear, and a non-JSON quota line follows the JSON. Byte-identical X output is not possible. | Keep the JSON as is, tagged with `response_format`, and put the quota line in `response_trailer`. We strip the extra fields in Silver. |
| No HTTP status code and no `x-rate-limit-*` headers. | `call_status` + `error_message` are required. `http_status` may be null. `quota` holds what grokbot can see. |
| Timestamps come from just before and after the call (1–6 s error in the trial). | Accepted up to 10 s. We work at minute precision, and the error points later, which is safe for point-in-time use. |
| `max_results` is fixed at 25. | Record 25 in `params.max_results`. |
| **Whole pages sometimes lose fields.** In the trial, 7 of 25 pages had no `lang`, `conversation_id`, `entities`, `possibly_sensitive` or `context_annotations` on any post. User fields were always present. | Load such pages as they are; these fields are nullable in Silver, where cashtags fall back to regex and we detect language ourselves. **SHOULD** investigate: refetch one affected page once, note in `notes` whether the fields come back, and report the cause once known. Do not refetch routinely. |
| Parameter and endpoint names differ from X's (`post.fields`, a tool name instead of a path). | Record the names actually used (see the §4 field table). |
| `to:` and `-is:nullcast` | Both supported (confirmed 2026-10-15). |
| No release version number. | Use the collection script's version, e.g. a date plus counter (`2026.10.14-1`) or a git sha. |

### Empty and failed calls

- **MUST** write an envelope for pages with `result_count = 0`. An empty page tells us the window was covered and quiet.
- **MUST** write an envelope for failed calls (4xx, 5xx, timeouts). Set `call_status` and `error_message`, and put whatever body came back in `response`, or `null` if none did. Retries are new calls with a new `request_id`.

## 5. Timestamps

- **MUST** use UTC, in ISO 8601 with milliseconds and a `Z` suffix: `2026-10-14T14:00:03.512Z`.
- **MUST** take `fetched_at` immediately after the call returns (and `requested_at` immediately before it). Do not use the time the file was written or uploaded.

## 6. Files

- **MUST** write JSON Lines (UTF-8, one envelope per line). Name files `x_search_<run_id>_<part>.jsonl`. One file per run is fine; split it if it grows beyond about 100 MB.
- **MUST** write files atomically: write to `*.tmp`, then rename. We only read files that do not end in `.tmp`.
- **MUST NOT** rewrite or append to a file after it has been renamed. Corrections go into a new run.
- **SHOULD** deliver files within 15 minutes of the run ending. Data that arrives late is still correct, because we use `fetched_at`, but alerts will be late.
- Drop location: `<lake>/landing/x_raw_search/`. This is not under `<lake>/brz/`, because files there would be deleted by Delta VACUUM. Until S3 is deployed, hand the files to jerry directly; the format stays the same.

### Run manifest (SHOULD)

At the end of each run, write `x_search_<run_id>_manifest.json`:

```json
{
  "run_id": "20261014T140000Z-a1b2c3",
  "collector_version": "0.3.1",
  "started_at": "2026-10-14T14:00:00.000Z",
  "finished_at": "2026-10-14T14:02:41.220Z",
  "status": "complete",
  "files": ["x_search_20261014T140000Z-a1b2c3_0001.jsonl"],
  "queries": [
    { "query_id": "crowd-q07", "pages": 4, "posts": 371,
      "since_id": "1846012345678901234", "newest_id": "1846099999999999999",
      "exhausted": true }
  ],
  "errors": 0
}
```

`status` is `complete`, `partial` or `failed`. `exhausted: true` means the pagination chain ran until there was no `next_token`. We use the manifest to check completeness on load.

## 7. Out of scope

- Media, geo and poll fields. We do not use them, and they make responses bigger.
- Any summary, sentiment or classification done by Grok. If grokbot produces these, put them in a separate file. They do not go in the envelope.

## 8. Acceptance checklist

A sample run is accepted when:

- [ ] Every line parses as JSON and has all MUST fields. `response` parses as JSON on its own, with any trailing text in `response_trailer`.
- [ ] `response` is unchanged from what the tool returned: posts, users and `meta` match a manual search for the same query and window.
- [ ] Pages with no results and failed calls are present.
- [ ] Following `params.pagination_token` → `response.meta.next_token` reconstructs each chain with no gaps.
- [ ] `since_id` for each query equals the previous run's `newest_id`.
- [ ] Posts include `entities`, `lang`, `public_metrics` and `note_tweet` where they apply. Pages that lost fields (§4.1) are reported, not hidden. Users include `created_at` and `public_metrics`.
- [ ] `params` and `endpoint` use the names actually sent.
- [ ] Every `*_version` matches a version of the corresponding list file under `infra/local/config/x_lists/`.
- [ ] Timestamps are UTC with `Z`.
- [ ] No `.tmp` files are left behind.
