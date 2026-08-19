# Edge Cases — AI-Powered Discovery Engine

Comprehensive catalog of edge cases across every pipeline stage. Each entry describes the scenario, the expected behavior, and which component is responsible for handling it.

Reference: [Architecture.md](Architecture.md) for specs, [Context.md](Context.md) for taxonomy.

---

## 1. Ingestion

### 1.1 Empty or whitespace-only text

| Scenario | A review/comment/post body is empty, whitespace-only, or contains only HTML tags after stripping. |
|---|---|
| Expected | Skip the record entirely — do not insert into `raw_records`. Log as `skipped_empty`. |
| Owner | Each adapter (`play_store.py`, `reddit.py`, `youtube.py`, `product_pages.py`, `manual_csv.py`) |

### 1.2 Duplicate IDs across runs

| Scenario | A record with the same canonical `id` already exists in `raw_records` from a prior run. |
|---|---|
| Expected | `ON CONFLICT (id) DO NOTHING` — silently skip. Never overwrite `raw_text`. Count as `skipped_duplicate` in `pipeline_runs.counts`. |
| Owner | `db/supabase_client.py` upsert logic |

### 1.3 Duplicate content, different IDs

| Scenario | Same text appears from two sources (e.g., a Reddit post copied verbatim onto Twitter). Different canonical IDs, so dedupe doesn't catch it. |
|---|---|
| Expected | Both rows are retained. Content deduplication is **not** in scope — ID-based dedupe only. The same text may contribute to multiple theme counts. Acceptable: volume is small enough that this doesn't distort scores. |
| Owner | By design — documented as a known limitation |

### 1.4 Non-Myntra text slipping through ingestion

| Scenario | A Reddit post mentions Myntra in the title but the body is entirely about AJIO. Or a Play Store review is for the wrong app package. |
|---|---|
| Expected | Adapters do a first-pass scope check (correct package name, keyword relevance). Remaining AJIO-only/Nykaa-only text is caught by the Groq filter (`relevant=false`). |
| Owner | Adapters (hard gate) + `groq_filter.py` (soft gate) |

### 1.5 Scraper blocked or rate-limited (HTTP 403/429)

| Scenario | Play Store or product pages return 403 (blocked) or 429 (rate limit). |
|---|---|
| Expected | Log the error. Retry with backoff (up to N retries). If still failing, stop that adapter but continue others. Mark `pipeline_runs.status = 'partial'`. The run is not `failed` unless Supabase itself is down. |
| Owner | Each adapter + `pipeline.py` |

### 1.6 Reddit API ceiling reached

| Scenario | Reddit free API returns at most ~1000 results per query. Backfill can't go further back. |
|---|---|
| Expected | Stop at the ceiling. Log actual count pulled. Document in `pipeline_runs.counts` and `methodology.md`. This is a **stated limitation**, not a bug. |
| Owner | `ingest/reddit.py` |

### 1.7 YouTube daily quota exhausted

| Scenario | YouTube Data API v3 free quota runs out mid-scrape. |
|---|---|
| Expected | Stop YouTube ingest. Mark run `partial`. Resume next week (or next `workflow_dispatch`). Other sources continue. |
| Owner | `ingest/youtube.py` + `pipeline.py` |

### 1.8 Product page HTML structure changes

| Scenario | Myntra redesigns their review HTML. Parser breaks — returns zero reviews or garbage. |
|---|---|
| Expected | Log `parse_error` with the URL. Return zero records for that page. Mark run `partial` if all PDP URLs fail. Do not insert garbage into `raw_records`. |
| Owner | `ingest/product_pages.py` |

### 1.9 Manual CSV with missing required columns

| Scenario | A CSV is dropped into `data/manual/` but is missing `source`, `raw_text`, or `url`. |
|---|---|
| Expected | Reject the entire file with a clear error message listing missing columns. Do not partially ingest. |
| Owner | `ingest/manual_csv.py` |

### 1.10 Manual CSV with unknown `source` value

| Scenario | CSV has `source=instagram` instead of `twitter` or `community`. |
|---|---|
| Expected | Reject the row (or the file). Only `twitter` and `community` are valid manual sources. Log which rows were rejected and why. |
| Owner | `ingest/manual_csv.py` |

### 1.11 Extremely long text

| Scenario | A Reddit post or review is 10,000+ characters. |
|---|---|
| Expected | Store full text in `raw_records` (no truncation at ingest). Truncation happens at the LLM call boundary if needed (Groq/Gemini context limits). Log if truncation was applied. |
| Owner | `raw_records` stores full text; `groq_filter.py` and `gemini_classify.py` handle truncation |

### 1.12 Non-English text

| Scenario | A review is in Hindi, Hinglish, or another language. |
|---|---|
| Expected | Ingest normally. The Groq filter decides relevance regardless of language. Gemini classifies if relevant. No language-based exclusion — Myntra users write in multiple languages. |
| Owner | Adapters (no language filter) + LLM stages (handle multilingual) |

### 1.13 `date_posted` is null or in the future

| Scenario | Source doesn't provide a post date, or provides a timestamp in the future (clock skew). |
|---|---|
| Expected | `date_posted = null` is allowed. Future dates: store as-is (source data integrity). Week assignment uses `COALESCE(date_posted, date_collected)` — if `date_posted` is null, `date_collected` determines the week. |
| Owner | Adapters + `aggregate/weekly_rollup.py` |

---

## 2. Filtering (Groq)

### 2.1 Groq returns invalid JSON

| Scenario | Groq's response is not valid JSON, or is missing `relevant`/`reason` fields. |
|---|---|
| Expected | Retry once. If still invalid, skip the record — leave it unfiltered (no `classified_records` row). Next run will retry. Log `filter_invalid_json`. |
| Owner | `filter/groq_filter.py` |

### 2.2 Groq returns `relevant` for AJIO-only text

| Scenario | A review says "AJIO has better prices" with no Myntra context. Groq marks it `relevant`. |
|---|---|
| Expected | False positive passes to Gemini. Gemini will tag it with `not_stated` / `not_mentioned` defaults (no Myntra shopping behavior to extract). The cost is one wasted Gemini call, not data corruption. Acceptable at low volume. |
| Owner | `groq_filter.py` prompt should catch most; Gemini is the safety net |

### 2.3 Groq marks relevant text as `discarded`

| Scenario | A valid Myntra review about size chart issues is incorrectly filtered out. |
|---|---|
| Expected | The record is lost from classification — a false negative. Mitigated by: (1) tuning the Groq prompt, (2) periodic manual spot-check of discarded rows, (3) accepting some loss as the cost of the free-tier filter gate. |
| Owner | `groq_filter.py` prompt quality; evaluated in Evals.md |

### 2.4 Groq quota exhausted mid-batch

| Scenario | Groq returns 429 partway through filtering. |
|---|---|
| Expected | Stop filtering. Already-filtered rows proceed to classify. Unfiltered rows remain in the queue for next run. Mark `pipeline_runs.status = 'partial'`. |
| Owner | `filter/groq_filter.py` + `pipeline.py` |

### 2.5 Batch contains mix of languages

| Scenario | A Groq batch of 5 texts includes Hindi, English, and Hinglish reviews. |
|---|---|
| Expected | Groq should handle multilingual input. If it consistently fails on a language, document in methodology. No language-based pre-filtering. |
| Owner | `groq_filter.py` prompt |

### 2.6 Text is ambiguously relevant

| Scenario | "The app crashes every time I open it" — shopping-adjacent but not about wishlist/purchase behavior. |
|---|---|
| Expected | Groq should mark this `discarded` (not about wishlist/purchase/fit/price/reviews). But if it marks `relevant`, Gemini will tag all taxonomy fields as `not_stated`, resulting in zero theme keys. The record exists in `classified_records` but contributes nothing to the board. Low harm. |
| Owner | `groq_filter.py` prompt definition of "relevant" |

---

## 3. Classification (Gemini)

### 3.1 Gemini returns invalid JSON

| Scenario | Response is not parseable JSON, or includes markdown fencing (` ```json ... ``` `). |
|---|---|
| Expected | Strip markdown fencing and retry parse. If still invalid, retry the API call once. If still failing, leave `classified_at = null` — next run retries. Log `classify_invalid_json`. |
| Owner | `classify/gemini_classify.py` |

### 3.2 Gemini returns an enum value not in `taxonomy.json`

| Scenario | Gemini invents `purchase_blocker: "out_of_stock"` which is not in the allowed enum. |
|---|---|
| Expected | Coerce to the field's unknown/default value (`not_stated`). Log the invented value in `validation_warnings` jsonb on the `classified_records` row. Do **not** add the value to the taxonomy. |
| Owner | `classify/gemini_classify.py` validation layer |

### 3.3 Gemini omits a field entirely

| Scenario | JSON response is missing `comparison_behavior`. |
|---|---|
| Expected | Set to the field's default (`not_mentioned` for `comparison_behavior`). Log in `validation_warnings`. |
| Owner | `classify/gemini_classify.py` validation layer |

### 3.4 Gemini returns extra fields not in taxonomy

| Scenario | Response includes `"category": "electronics"` — not a taxonomy field. |
|---|---|
| Expected | Ignore extra fields. Only write columns defined in `classified_records`. No error, no warning (LLMs commonly add unsolicited fields). |
| Owner | `classify/gemini_classify.py` |

### 3.5 Text has multiple conflicting signals

| Scenario | "I bought it but the size was wrong so I returned it and wishlisted something else." — `purchased` and `not_purchased` simultaneously? |
|---|---|
| Expected | Gemini picks the **dominant** outcome for `purchase_outcome`. The taxonomy is single-select per field by design. The nuance is captured across multiple fields (e.g., `purchase_outcome: purchased`, `purchase_blocker: size_fit_doubt`, `fit_size_signal: true`). The verbatim quote preserves full context. |
| Owner | Gemini prompt + taxonomy design |

### 3.6 Text mentions multiple products

| Scenario | "I wishlisted three kurtas — loved the print on one, but the other two were overpriced." |
|---|---|
| Expected | One `raw_records` row = one classification. Gemini tags the **dominant signal** from the text. It does not split into sub-records. Multiple theme keys can fire from one classification (e.g., `wishlist_motive:liked_product` AND `purchase_blocker:price_too_high`). |
| Owner | Gemini prompt + theme explosion logic |

### 3.7 `segment_signal` inference temptation

| Scenario | Text says "I bought a men's shirt" — Gemini might infer `segment_signal: gender_context`. But the text doesn't explicitly state the user's gender or shopping pattern. |
|---|---|
| Expected | If the text **explicitly states** a segment marker ("as a college student on a budget"), tag it. If it only implies it, tag `not_evident`. The prompt must say: "Tag only when explicitly evident. Never infer." |
| Owner | Gemini prompt (constraint #4 in Architecture §2) |

### 3.8 `unmet_need` is a full sentence instead of a short phrase

| Scenario | Gemini returns `unmet_need: "I really wish they would add a feature where you can see how clothes look on different body types"`. |
|---|---|
| Expected | Store as submitted. Normalization (lowercase, strip, collapse whitespace) happens at aggregation. Very long phrases will have low exact-match counts and will be hidden by `min_count` filtering. Acceptable. |
| Owner | `classify/gemini_classify.py` stores; `aggregate/themes.py` normalizes |

### 3.9 Gemini quota exhausted

| Scenario | Gemini returns 429 or quota error mid-classification. |
|---|---|
| Expected | Stop classifying. Already-classified rows proceed to aggregation. Unclassified rows (`classified_at = null`) stay in queue for next run. Mark `partial`. |
| Owner | `classify/gemini_classify.py` + `pipeline.py` |

### 3.10 All taxonomy fields are `not_stated`/`not_mentioned`

| Scenario | A relevant review says "Love Myntra's new UI!" — no wishlist/purchase/fit/price signal. |
|---|---|
| Expected | Record is classified (all defaults). Theme explosion produces **zero** theme keys (all skipped). The record exists in `classified_records` but does not appear in `weekly_theme_stats` or `opportunity_areas`. This is correct — it passed the filter but has no actionable signal. |
| Owner | `aggregate/themes.py` |

---

## 4. Aggregation

### 4.1 First week ever (no prior data)

| Scenario | First pipeline run. No prior `weekly_theme_stats` rows exist for trend comparison. |
|---|---|
| Expected | Treat prior frequency as 0 for all themes. All themes with current > 0 get `trend = 'rising'`, `trend_multiplier = 1.2`. `wow_pct = null` (can't divide by zero). |
| Owner | `aggregate/weekly_rollup.py` (§10.4) |

### 4.2 Theme appears this week but not last week

| Scenario | `purchase_blocker:forgot` appeared 5 times this week, 0 last week. |
|---|---|
| Expected | Prior = 0, current > 0 → `trend = 'rising'`, multiplier = 1.2. `wow_pct = null`. |
| Owner | `aggregate/weekly_rollup.py` |

### 4.3 Theme appeared last week but not this week

| Scenario | `comparison_behavior:brand_comparison` had 8 mentions last week, 0 this week. |
|---|---|
| Expected | Current = 0 → theme is **not** in this week's `opportunity_areas` (no `|S|`, no theme row). It still exists in prior weeks' stats. The board shows it if "All time" is selected (via `cumulative_count`). |
| Owner | `aggregate/weekly_rollup.py` |

### 4.4 Severity boundary: rate exactly at threshold

| Scenario | `rate = |N|/|S|` is exactly 0.20 or exactly 0.50. |
|---|---|
| Expected | ≥ 0.50 → severity 3. ≥ 0.20 → severity 2. Boundary values are **inclusive** on the upper tier. |
| Owner | `aggregate/weekly_rollup.py` (§10.3) |

### 4.5 Severity when `|S| = 0`

| Scenario | A theme has zero records this week (shouldn't happen if theme key was generated, but a safeguard). |
|---|---|
| Expected | Drop the theme — do not divide by zero. No row in `opportunity_areas` for that week. |
| Owner | `aggregate/weekly_rollup.py` |

### 4.6 Severity when all records have `purchase_outcome = unclear`

| Scenario | A theme has 10 records but all have `purchase_outcome = unclear` and `sentiment = neutral`. `|N| = 0`. |
|---|---|
| Expected | `rate = 0/10 = 0.0` → severity 1. The theme appears on the board with low severity. This is correct — we can't tie it to non-purchase. |
| Owner | `aggregate/weekly_rollup.py` |

### 4.7 Trend deadband: change exactly at ±10%

| Scenario | Prior = 10, current = 11 (exactly +10%). Or current = 9 (exactly -10%). |
|---|---|
| Expected | current > prior × 1.10 is `11 > 11.0` → false → `flat`. current < prior × 0.90 is `9 < 9.0` → false → `flat`. The ±10% deadband uses **strict** inequality. Exactly ±10% is `flat`. |
| Owner | `aggregate/weekly_rollup.py` (§10.4) |

### 4.8 Score tie-breaking

| Scenario | Two themes have identical `score` and identical `frequency`. |
|---|---|
| Expected | Tie-break by `theme_key` ascending (alphabetical). Deterministic across reruns. |
| Owner | `aggregate/weekly_rollup.py` (§10.5) |

### 4.9 Priority threshold: fewer than 4 themes

| Scenario | Only 2 themes exist this week. Both are rank ≤ 3. |
|---|---|
| Expected | Both get `priority = true` (rank ≤ 3). The 75th percentile check is redundant but harmless. |
| Owner | `aggregate/weekly_rollup.py` |

### 4.10 `unmet_need` normalization collisions

| Scenario | "Better size guide" and "better size guide." normalize to the same string. |
|---|---|
| Expected | They are counted as the same theme key `unmet_need:better size guide`. This is intended behavior (lowercase, strip punctuation, collapse whitespace). |
| Owner | `aggregate/themes.py` (§10.2) |

### 4.11 `unmet_need` is extremely rare (count = 1)

| Scenario | A unique unmet_need phrase appears only once in the entire dataset. |
|---|---|
| Expected | It appears in `weekly_theme_stats` with `weekly_count = 1`. The board can hide it via `min_count` filter (default 2). Not a bug — rare phrases are expected. |
| Owner | `aggregate/weekly_rollup.py` + Streamlit `min_count` filter |

### 4.12 Re-running aggregation on the same week

| Scenario | `pipeline.py --stage aggregate` is run twice for the same `week_start`. |
|---|---|
| Expected | Upsert on `(week_start, theme_key)` — idempotent. Same data in, same scores out. No duplicate rows. |
| Owner | `aggregate/weekly_rollup.py` |

### 4.13 Quote selection: fewer than 5 qualifying records

| Scenario | A theme has only 2 records this week, but quote selection wants up to 5. |
|---|---|
| Expected | Return all 2 `raw_id`s. Do not pad or invent. `quote_raw_ids` has 2 entries. |
| Owner | `aggregate/weekly_rollup.py` (§10.6) |

### 4.14 Quote selection: all records are from one source

| Scenario | A theme has 10 records, all from Play Store. Round-robin source diversification can't diversify. |
|---|---|
| Expected | Select 5 from Play Store. Source diversification is best-effort, not a hard requirement. |
| Owner | `aggregate/weekly_rollup.py` |

---

## 5. Presentation (Streamlit)

### 5.1 No data in Supabase yet

| Scenario | Supabase is connected but `opportunity_areas` is empty (pre-backfill). |
|---|---|
| Expected | Fall back to `app/sample_board.json` fixture. Show a notice: "Showing sample data — run the pipeline to populate." |
| Owner | `app/streamlit_app.py` |

### 5.2 Last pipeline run status is `failed`

| Scenario | The most recent `pipeline_runs` row has `status = 'failed'`. |
|---|---|
| Expected | Display a warning banner: "Last run failed at {finished_at}. Showing data from previous successful run." Load rollup from the latest `success` or `partial` run. |
| Owner | `app/streamlit_app.py` |

### 5.3 Last pipeline run status is `partial`

| Scenario | Run completed but some sources or LLM stages had errors. |
|---|---|
| Expected | Display an info notice: "Last run was partial — some sources may be incomplete." Show data normally. |
| Owner | `app/streamlit_app.py` |

### 5.4 "So what" note is empty

| Scenario | A theme has no `opportunity_notes` row (never reviewed). |
|---|---|
| Expected | Show an empty editable text field. Do not display "null" or "None". |
| Owner | `app/streamlit_app.py` |

### 5.5 Very long "so what" note

| Scenario | Reviewer writes a 500-word paragraph in the so_what field. |
|---|---|
| Expected | Store and display it. No truncation. The UI may wrap or scroll. The convention is one short line, but it's not enforced by the system. |
| Owner | `app/streamlit_app.py` |

### 5.6 Question filter returns zero results

| Scenario | User selects "How do users compare products?" but no `comparison_behavior` themes exist this week. |
|---|---|
| Expected | Show an empty list with a message: "No themes in this category for the selected period." |
| Owner | `app/streamlit_app.py` |

### 5.7 "All time" toggle with cumulative_count = 0

| Scenario | A theme just appeared this week. `cumulative_count` equals `weekly_count`. Switching to "All time" shouldn't change the score. |
|---|---|
| Expected | Score = `cumulative_count × severity × trend_multiplier`. If cumulative = weekly (one week of data), scores are the same. Correct behavior. |
| Owner | `app/streamlit_app.py` |

### 5.8 Quote text was deleted from `raw_records` (should never happen)

| Scenario | A `quote_raw_ids` entry references a `raw_id` that doesn't exist in `raw_records`. |
|---|---|
| Expected | Should never happen (raw text is immutable, never deleted). If it does, the join returns null — display "[quote unavailable]" instead of crashing. |
| Owner | `v_quotes` view + `app/streamlit_app.py` |

---

## 6. Pipeline Orchestration

### 6.1 Two pipeline runs triggered simultaneously

| Scenario | Cron fires while a `workflow_dispatch` is still running. |
|---|---|
| Expected | GitHub Actions `concurrency: pipeline` ensures only one runs at a time. The second is queued or cancelled (depending on concurrency config). |
| Owner | `.github/workflows/weekly-pipeline.yml` |

### 6.2 Backfill exceeds free-tier quotas in one run

| Scenario | Day-1 backfill has thousands of records. Groq and Gemini quotas run out before all are processed. |
|---|---|
| Expected | Process as many as caps allow (`max_filter_per_run`, `max_classify_per_run`). Mark `partial`. Already-processed IDs are skipped on next `workflow_dispatch`. Multiple dispatches resume where prior runs stopped. |
| Owner | `pipeline.py` + per-stage caps |

### 6.3 Supabase outage during pipeline run

| Scenario | Supabase goes down mid-run. |
|---|---|
| Expected | All DB writes fail. Mark `status = 'failed'`. Do not retry endlessly — fail fast after connection retries. The run can be re-dispatched manually once Supabase is back. |
| Owner | `db/supabase_client.py` + `pipeline.py` |

### 6.4 Environment variable missing

| Scenario | `GEMINI_API_KEY` is not set in GitHub Secrets. |
|---|---|
| Expected | `config/settings.py` raises a clear error at startup listing the missing variable. Pipeline does not partially run with a broken config. |
| Owner | `config/settings.py` |

### 6.5 `--stage aggregate` with no classified data

| Scenario | Someone runs `python pipeline.py --stage aggregate` before any filter/classify has run. |
|---|---|
| Expected | Aggregation finds zero classified rows. Produces zero theme stats and zero opportunity areas. Mark `success` with counts all at 0. Not an error — just empty. |
| Owner | `pipeline.py` + `aggregate/weekly_rollup.py` |
