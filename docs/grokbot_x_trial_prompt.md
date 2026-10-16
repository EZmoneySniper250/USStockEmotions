# grokbot X trial run prompt

Version: v1.2 (2026-10-14). Owners: jerry, jaylen. v1.2 matches spec v1.2 (wrapped response, `call_status`/`quota`, operator and field probes). v1.1 shortened the window to 2 hours.

A one-off trial run that checks grokbot can produce output in the format of `docs/grokbot_x_spec.md` (v1.2) before we schedule it daily. S3 is not deployed yet, so the files are handed to jerry and jaylen, who check them by hand.

Before sending, fill in the `<…>` placeholders. Everything below the line is the prompt; paste it as is.

---

You are collecting raw X posts for a sentiment research pipeline. This is a **trial run**. Accurate, complete output matters more than volume. Follow these rules exactly.

## Hard rules

1. Use X API v2 search (`tweets/search/recent`). Filter **only inside the query string**. Do not filter, rerank, summarise or drop any post after it comes back. Keep every response exactly as your tool returned it, including the extra `url` fields and the quota information it adds. Do not strip or edit anything.
2. Do not add any analysis, sentiment or commentary to the data files. A short run report goes in a separate message (see "Report").
3. Total budget: **at most 30 calls**. Page cap: **5 pages per query**. If a cap stops a query that still has a `next_token`, stop and record it; do not go over the budget.
4. Time window: the last 2 hours. Set `start_time` to now minus 2h (UTC) and leave `end_time` unset. This is the first run, so do not set `since_id`.
5. Use `sort_order=recency` and the largest page size your tool allows.
6. Request these fields on every call:
   - `tweet.fields=id,text,created_at,author_id,lang,conversation_id,entities,public_metrics,note_tweet,referenced_tweets,in_reply_to_user_id,edit_history_tweet_ids,possibly_sensitive,context_annotations`
   - `user.fields=id,username,name,created_at,public_metrics,verified,verified_type,description,protected`
   - `expansions=author_id,referenced_tweets.id,referenced_tweets.id.author_id`

## Lists (version v1)

- Whitelist (investors): `<A, B, C, …>`
- Blacklist (known bots and spam): `grok, <…>`
- Spam keywords: `airdrop, giveaway, "join my telegram", discord.gg`

## Queries

Run these in order. Follow `next_token` up to the page cap.

| query_id | Query |
|---|---|
| `kol-q01` | `(from:A OR from:B OR …) -is:retweet -is:reply` |
| `kol_replies-q01` | `(to:A OR to:B OR …) is:reply -is:retweet -has:links (lang:en OR lang:zh) -from:grok <-from:…>`. If `to:` is rejected or returns nothing, keep that envelope, then run `kol_replies-q01-fallback` with `(@A OR @B OR …)` in place of the `to:` terms. |
| `kol_replies-q01-nolinkfilter` | Same as `kol_replies-q01` but **without** `-has:links`. **1 page only.** It measures how much `-has:links` removes. |
| `crowd-q01` | `($SPY OR $QQQ) -is:retweet -is:nullcast (lang:en OR lang:zh) -from:grok <-from:…> -"airdrop" -"giveaway" -"join my telegram" -"discord.gg"`. If `-is:nullcast` is rejected, keep that envelope, then rerun as `crowd-q01-fallback` without it (and use the same for `crowd-q02`). |
| `crowd-q02` | Same filters as `crowd-q01`, with `($NVDA OR $TSLA OR $AAPL)` |

If a query is too long, split the account list into `-q01a`, `-q01b`, and so on. Do not truncate it.

## Output format

For **every call**, write one JSON object (an "envelope") on its own line. This includes calls that returned 0 posts and calls that failed; a retry is a new call with a new `request_id`.

```json
{
  "envelope_version": 1,
  "collector": "grokbot",
  "collector_version": "<your script version, e.g. 2026.10.14-1 or a git sha>",
  "run_id": "<YYYYMMDDTHHMMSSZ>-trial",
  "request_id": "<new UUID per call>",
  "query_id": "crowd-q01",
  "page_index": 0,
  "requested_at": "<UTC time immediately before the call, ISO 8601 with ms and Z>",
  "fetched_at": "<UTC time immediately after the call returned, ISO 8601 with ms and Z>",
  "endpoint": "tweets/search/recent",
  "query": "<exact query string sent>",
  "params": {
    "since_id": null, "start_time": "...", "end_time": null,
    "sort_order": "recency", "max_results": 25,
    "pagination_token": "<token used for THIS page, null on page 0>",
    "tweet.fields": "...", "user.fields": "...", "expansions": "..."
  },
  "watchlist_version": "v1",
  "whitelist_version": "v1",
  "blacklist_version": "v1",
  "call_status": "ok | error | timeout",
  "error_message": null,
  "http_status": null,
  "quota": { "remaining_per_minute": null, "remaining_per_day": null },
  "response_format": "grokbot_x_v2_wrapped_v1",
  "notes": null,
  "response": { "...the response exactly as your tool returned it, including errors..." }
}
```

- Set list versions to `null` when the query does not use that list.
- Take `requested_at` right before the call and `fetched_at` right after it returns. Do not use the time you wrote the file.
- `http_status` stays `null` unless you can see the real status code. Put whatever quota numbers you can see in `quota`.
- If a value is not available to you (e.g. rate-limit headers), write `null` and explain it once in `notes`. Never invent a value.

## Deliverables

1. `x_search_<run_id>_0001.jsonl`: all envelopes, one per line, UTF-8.
2. `x_search_<run_id>_manifest.json`:

```json
{
  "run_id": "...",
  "collector_version": "...",
  "started_at": "...",
  "finished_at": "...",
  "status": "complete | partial | failed",
  "files": ["x_search_<run_id>_0001.jsonl"],
  "queries": [
    { "query_id": "crowd-q01", "pages": 5, "posts": 125,
      "since_id": null, "newest_id": "...", "exhausted": false }
  ],
  "calls_used": 0,
  "errors": 0
}
```

Attach both as files. If you cannot attach files, paste the manifest and the first 3 envelopes in full, and keep the complete files saved so they can be sent later.

## Report (separate message, not in the files)

Keep it short:

- Calls used, out of the 30 budget.
- Per query: pages, posts, and whether it was exhausted.
- `kol_replies-q01` vs `kol_replies-q01-nolinkfilter`: how many posts per page each returned, and roughly what kind of posts `-has:links` removed (spam links vs chart screenshots).
- **Operators:** whether `to:` and `-is:nullcast` worked, and whether fallbacks were used.
- **Fields:** for each requested field, whether it actually showed up in the posts or users (at least `entities`, `lang`, `conversation_id`, `public_metrics`, `note_tweet`, `context_annotations`, and the author's `created_at` and `public_metrics`). Write "missing" or "present" for each; a field can legitimately be absent from some posts (e.g. `note_tweet` exists only on long posts).
- **Wrapper:** list exactly which fields your tool adds on top of X's format, and where.
- Anything you could not do as specified, and why.
- Spam patterns you noticed (for example, accounts that look like they belong on the blacklist). List them only; do not filter them.
