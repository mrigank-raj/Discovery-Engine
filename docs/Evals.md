# Evals — AI-Powered Discovery Engine

Evaluation framework for every stage of the pipeline. Covers automated tests, manual audits, quality metrics, and acceptance criteria.

Reference: [Architecture.md](Architecture.md) §16, [Context.md](Context.md), [Edge_cases.md](Edge_cases.md).

---

## 1. Ingestion Evals

### 1.1 ID Canonicalization (Unit Tests)

Verify `ingest/ids.py` produces correct, stable canonical IDs for all 6 sources.

| Test case | Input | Expected output |
|---|---|---|
| Play Store | `package="com.myntra.android"`, `reviewId="abc123"` | `play:com.myntra.android:abc123` |
| Reddit comment | `fullname="t1_xyz789"` | `reddit:t1_xyz789` |
| Reddit post | `fullname="t3_def456"` | `reddit:t3_def456` |
| YouTube | `commentId="Ugw1234"` | `yt:Ugw1234` |
| Product page (with site ID) | `review_key="12345"` | `pdp:myntra:12345` |
| Product page (hash fallback) | `url + author + date + first200` | `pdp:myntra:{sha256[:24]}` — verify deterministic |
| Twitter | `tweet_id="9876543210"` | `tw:9876543210` |
| Community (hash) | `url\|author\|date\|first200` | `com:{sha256[:24]}` — verify deterministic |

**Criteria:** All IDs are deterministic (same input → same output across runs). No collisions on sample data.

### 1.2 Dedupe Correctness (Integration Test)

| Test | Steps | Expected |
|---|---|---|
| First insert | Insert 100 records | 100 new rows in `raw_records` |
| Repeat insert | Insert same 100 records | 0 new rows; `skipped_duplicate = 100` |
| Mixed insert | Insert 50 old + 50 new | 50 new rows; `skipped_duplicate = 50` |

### 1.3 Adapter-Specific Checks

| Adapter | What to verify |
|---|---|
| Play Store | Only Myntra package; `raw_text` is non-empty; `source_meta.rating` is 1–5; `date_posted` is valid timestamp |
| Reddit | Only target subreddits + keyword matches; `raw_text` strips markup; `source = 'reddit'` |
| YouTube | Only seed video IDs; comment text is non-empty; `source_meta.videoId` matches config |
| Product pages | Only allowlisted Myntra URLs; review text extracted (not page chrome); `source_meta.product_id` present |
| Manual CSV | Rejects missing required columns; rejects invalid `source` values; handles optional `id` and `date_posted` |

### 1.4 Scraper Resilience (Manual Test)

Run each scraper and verify behavior on:
- Normal conditions (happy path)
- Rate limiting (simulate or wait for natural 429)
- Network timeout (disconnect mid-scrape)
- Empty results (new subreddit with no Myntra posts)

Expected: no crashes, correct `pipeline_runs.status`, accurate `counts`.

---

## 2. Groq Filter Evals

### 2.1 Golden Set (Manual Audit)

Create a **golden set** of 100 manually-labeled records:
- 50 records labeled `relevant` (genuine Myntra shopping behavior)
- 50 records labeled `discarded` (spam, off-topic, AJIO-only, generic "nice app")

Run the Groq filter on the golden set and compute:

| Metric | Definition | Target |
|---|---|---|
| **Precision** | `true_relevant / (true_relevant + false_relevant)` | ≥ 0.85 |
| **Recall** | `true_relevant / (true_relevant + false_missed)` | ≥ 0.90 |
| **F1** | `2 × (precision × recall) / (precision + recall)` | ≥ 0.87 |

**Recall matters more than precision** — a false positive wastes one Gemini call but a false negative loses real data permanently.

### 2.2 Category Breakdown

Break the golden set into subcategories and check filter accuracy per category:

| Category | Examples | Risk |
|---|---|---|
| Clear Myntra shopping | "Size chart was wrong on Myntra" | Should always pass — low risk |
| Myntra-adjacent (app UX) | "Myntra app crashes on checkout" | Borderline — may or may not relate to purchase behavior |
| Other retailer only | "AJIO has better ethnic wear selection" | Must be filtered — high risk if passed |
| Spam / generic | "Nice video 👍", "First comment!", ads | Must be filtered |
| Multilingual (Hindi/Hinglish) | "Myntra pe size chart galat hai" | Must pass if about shopping — test explicitly |
| Mixed retailer | "Myntra is better than AJIO for western wear" | Should pass — mentions Myntra shopping behavior |

### 2.3 Prompt Sensitivity

Test at least 3 prompt variations and compare F1 scores on the golden set. Document the winning prompt in `filter/groq_filter.py`.

### 2.4 Batch Size Impact

Test filter quality at batch sizes 1, 3, and 5 texts per call. Verify that batching doesn't degrade accuracy (some models lose focus with multiple texts).

### 2.5 Production Monitoring (Ongoing)

After deployment, sample 20 random `discarded` rows per week. Manually check:
- How many were actually relevant? (false negative rate)
- If > 10% were relevant, tighten the prompt or lower the batch size.

---

## 3. Gemini Classification Evals

### 3.1 Golden Set (Manual Audit)

Create a **golden set** of 50 manually-classified records. For each record, a human annotator fills in all taxonomy fields. This is the ground truth.

Run Gemini on the same 50 records and compare field-by-field.

### 3.2 Per-Field Accuracy

| Field | Metric | Target | Notes |
|---|---|---|---|
| `purchase_outcome` | Accuracy | ≥ 0.80 | Critical — anchors the north-star metric |
| `wishlist_motive` | Accuracy | ≥ 0.75 | Multi-valued texts make this harder |
| `purchase_blocker` | Accuracy | ≥ 0.75 | Same |
| `post_selection_uncertainty` | Accuracy | ≥ 0.75 | |
| `purchase_postponement_reason` | Accuracy | ≥ 0.75 | |
| `comparison_behavior` | Accuracy | ≥ 0.75 | |
| `external_info_sought` | Accuracy | ≥ 0.75 | |
| `fit_size_signal` … `social_validation_signal` | Accuracy | ≥ 0.80 | Binary — should be easier |
| `wishlist_intent_type` | Accuracy | ≥ 0.70 | Subtle distinction; harder to judge |
| `segment_signal` | Accuracy | ≥ 0.85 | Should be `not_evident` most of the time — check for over-inference |
| `unmet_need` | Manual review | Subjective | Check: is the phrase meaningful? Is it a real need or just noise? |
| `sentiment` | Accuracy | ≥ 0.80 | Standard NLP task |

**Accuracy** = `(exact matches) / (total records)` for each field.

### 3.3 Confusion Analysis

For fields with accuracy below target, build a confusion matrix. Common failure modes to watch for:

| Failure mode | Example | Detection |
|---|---|---|
| **Over-inference of segment** | Gemini tags `budget_conscious` from "I like sales" | Count `segment_signal != not_evident` — if > 30% of records have a segment, Gemini is likely over-inferring |
| **Default-heavy classification** | Gemini tags everything as `not_stated` | Count default rates per field — if > 70% for a purchase-related field, the prompt may be too conservative |
| **Sentiment-content mismatch** | "Great app but sizes are terrible" tagged `positive` | Cross-check sentiment against purchase_blocker presence |
| **Missed boolean signals** | Text says "I checked YouTube reviews" but `reviews_signal = false` | Cross-check boolean signals against relevant enum fields |

### 3.4 JSON Schema Validation (Automated)

For every Gemini response:

| Check | Pass condition |
|---|---|
| Valid JSON | Parseable by `json.loads()` |
| All required fields present | Every taxonomy field exists in the response |
| Enum values in allowed set | Every enum field value is in `taxonomy.json` |
| Boolean fields are boolean | Signal fields are `true` or `false`, not strings |
| `unmet_need` is string | Not null, not a list, not a number |

Track `validation_warnings` rate per run. Target: < 15% of responses need any coercion.

### 3.5 Prompt Iteration Protocol

When accuracy is below target:

1. Analyze the confusion matrix for the weak field.
2. Add 2–3 in-context examples targeting the failure mode.
3. Re-run on the golden set.
4. If accuracy improves ≥ 5 points, adopt the new prompt. Otherwise, revert.
5. Document each iteration: prompt version, date, accuracy delta.

### 3.6 Inter-Annotator Agreement (Optional, Recommended)

If possible, have a second human annotate 20 of the 50 golden set records independently. Compute Cohen's kappa for key fields (`purchase_outcome`, `purchase_blocker`, `sentiment`). This establishes an upper bound on achievable accuracy — if humans disagree 25% of the time, expecting > 75% model accuracy is unrealistic.

---

## 4. Aggregation Evals

### 4.1 Theme Explosion (Unit Tests)

| Test case | Input classified row | Expected theme keys |
|---|---|---|
| Standard enum | `purchase_blocker: size_fit_doubt` | `purchase_blocker:size_fit_doubt` |
| Default enum (skipped) | `purchase_blocker: not_stated` | *(no theme key)* |
| `purchase_outcome` (never skipped) | `purchase_outcome: not_purchased` | *(not a ranked theme, but feeds purchased_n/not_purchased_n)* |
| Boolean signal true | `fit_size_signal: true` | `fit_size_signal:true` |
| Boolean signal false | `fit_size_signal: false` | *(no theme key)* |
| `unmet_need` non-empty | `unmet_need: "better size guide"` | `unmet_need:better size guide` |
| `unmet_need` empty | `unmet_need: ""` | *(no theme key)* |
| `segment_signal` not_evident | `segment_signal: not_evident` | *(no theme key)* |
| `segment_signal` explicit | `segment_signal: budget_conscious` | `segment_signal:budget_conscious` |
| Multiple fields | `purchase_blocker: price_too_high`, `fit_size_signal: true`, `price_signal: true` | `purchase_blocker:price_too_high`, `fit_size_signal:true`, `price_signal:true` |

### 4.2 Severity Calculation (Unit Tests)

| `|S|` | `|N|` (not_purchased + negative) | Expected rate | Expected severity |
|---|---|---|---|
| 10 | 6 | 0.60 | 3 |
| 10 | 5 | 0.50 | 3 (boundary — inclusive) |
| 10 | 4 | 0.40 | 2 |
| 10 | 2 | 0.20 | 2 (boundary — inclusive) |
| 10 | 1 | 0.10 | 1 |
| 10 | 0 | 0.00 | 1 |
| 0 | 0 | N/A | *(drop theme — no records)* |
| 1 | 1 | 1.00 | 3 |
| 1 | 0 | 0.00 | 1 |

### 4.3 Trend & Multiplier (Unit Tests)

| Prior freq | Current freq | Expected trend | Expected multiplier | Expected wow_pct |
|---|---|---|---|---|
| 0 | 5 | rising | 1.2 | null |
| 10 | 12 | rising | 1.2 | 0.20 |
| 10 | 11 | flat | 1.0 | 0.10 (at boundary — strict inequality) |
| 10 | 10 | flat | 1.0 | 0.00 |
| 10 | 9 | flat | 1.0 | -0.10 (at boundary — strict inequality) |
| 10 | 8 | falling | 0.8 | -0.20 |
| 10 | 0 | *(no theme row — current = 0)* | N/A | N/A |

### 4.4 Score & Rank (Unit Tests)

| Theme | Frequency | Severity | Trend multiplier | Expected score | Expected rank |
|---|---|---|---|---|---|
| A | 42 | 3 | 1.2 | 151.2 | 1 |
| B | 31 | 2 | 1.0 | 62.0 | 2 |
| C | 28 | 3 | 1.2 | 100.8 | *(wait — should be ranked by score)* |

Correct ranking for the above: A (151.2) → C (100.8) → B (62.0). Rank = 1, 2, 3.

**Tie-break test:** Two themes with score = 48.0 and frequency = 24. Break by `theme_key` ascending.

### 4.5 Priority Flag (Unit Tests)

| Scenario | Expected |
|---|---|
| Rank ≤ 3 | `priority = true` |
| Rank = 4 but score ≥ 75th percentile | `priority = true` |
| Rank = 4 and score < 75th percentile | `priority = false` |
| Only 2 themes exist | Both `priority = true` (both rank ≤ 3) |

### 4.6 Idempotency (Integration Test)

Run aggregation twice on the same week. Compare `weekly_theme_stats` and `opportunity_areas` row-for-row. Must be identical — same scores, same ranks, same quotes.

### 4.7 Quote Selection (Unit Tests)

| Scenario | Expected quote_raw_ids |
|---|---|
| 10 records, mixed sources | Up to 5 IDs, diversified by source (round-robin) |
| 3 records, all Play Store | 3 IDs, all Play Store (best-effort diversity) |
| Records vary in length | Prefer 80–400 chars; include shorter/longer if needed |
| All records have `purchase_outcome=purchased` | Still select quotes (preference for not_purchased + negative, not a hard filter) |

### 4.8 `unmet_need` Normalization (Unit Tests)

| Input | Normalized output |
|---|---|
| `"Better Size Guide"` | `"better size guide"` |
| `"  better   size  guide  "` | `"better size guide"` |
| `"better size guide."` | `"better size guide"` |
| `"better size guide!!!"` | `"better size guide"` |
| `""` | *(skip — no theme key)* |
| `"   "` | *(skip — empty after strip)* |

### 4.9 Conversion Link (Unit Tests)

| purchased_n | not_purchased_n | unclear_n | Expected not_purchased_share |
|---|---|---|---|
| 5 | 15 | 0 | 0.75 |
| 0 | 0 | 10 | 0.00 |
| 0 | 0 | 0 | 0.00 (or null — guard against division by zero) |
| 3 | 7 | 2 | 7/12 ≈ 0.583 |

---

## 5. Dashboard Evals

### 5.1 Functional Acceptance Tests

| Test | Steps | Expected |
|---|---|---|
| Renders with fixture | Start app with no Supabase connection | Loads `sample_board.json`, shows opportunity list |
| Renders with live data | Connect Supabase with populated data | Shows real opportunity areas |
| Question filter | Select "What prevents a purchase?" | Only `purchase_blocker` themes visible |
| Question filter "All" | Select "All questions" | All taxonomy fields visible |
| This week toggle | Select "This week" | Scores use `weekly_count`; ranks update |
| All time toggle | Select "All time" | Scores use `cumulative_count`; ranks update |
| Priority badge | Check rank 1–3 rows | Badge visible |
| Priority badge absent | Check low-rank, low-score row | No badge |
| Trend arrow | Check a rising theme | ↑ displayed |
| So what edit | Type text in so_what field | Persists after page reload |
| Empty state | Filter returns zero themes | "No themes" message, no crash |

### 5.2 Visual / UX Checks (Manual)

| Check | Pass condition |
|---|---|
| Readability | Theme names are human-readable (not raw `snake_case`) |
| Quote display | Verbatim quote text is readable, not truncated unexpectedly |
| Priority contrast | Priority badge is visually distinct from non-priority rows |
| Trend legibility | ↑ / → / ↓ arrows are clear without explanation |
| Score format | Scores are formatted to 1 decimal (e.g., 151.2 not 151.19999) |
| Run status | Header shows last run time and status clearly |

### 5.3 Data Integrity Checks

| Check | How to verify |
|---|---|
| Rank consistency | Ranks are 1-indexed, contiguous, no gaps, no duplicates within a filter view |
| Score = F × S × T | Manually verify score = frequency × severity × trend_multiplier for 5 random rows |
| Quote matches theme | Click into a quote — does the text actually discuss the theme it's filed under? |
| Notes persist | Write a note, close the app, reopen — note is still there |

---

## 6. End-to-End Pipeline Eval

### 6.1 Full Pipeline Smoke Test

| Step | Expected |
|---|---|
| `python pipeline.py --mode backfill` | Creates `pipeline_runs` row; ingests from all sources; filters; classifies; aggregates. Status = `success` or `partial`. |
| Check `raw_records` count | > 0 across multiple sources |
| Check `classified_records` | Mix of `relevant` and `discarded`; relevant rows have taxonomy columns filled |
| Check `weekly_theme_stats` | Themes have non-zero counts |
| Check `opportunity_areas` | Ranked themes with scores |
| Open dashboard | Renders real data |

### 6.2 Incremental Run Correctness

| Step | Expected |
|---|---|
| Run backfill | N records ingested |
| Run incremental immediately | 0 new records (all dupes); filter/classify processes 0 new; aggregate re-upserts same scores |
| Wait one week; run incremental | > 0 new records; new week's theme stats appear alongside prior week |

### 6.3 Failure Recovery Test

| Scenario | Steps | Expected |
|---|---|---|
| Kill mid-filter | Interrupt pipeline during Groq stage | Unfiltered rows remain; next run resumes |
| Kill mid-classify | Interrupt during Gemini stage | Unclassified rows remain; next run resumes; already-classified are not re-processed |
| Kill mid-aggregate | Interrupt during rollup | Partial upserts; next run re-upserts cleanly (idempotent) |

### 6.4 GitHub Actions Validation

| Check | Pass condition |
|---|---|
| Secrets not logged | Grep Actions log for API key patterns — zero matches |
| Concurrency | Trigger two `workflow_dispatch` simultaneously — second is queued, not parallel |
| Run summary | Actions log contains counts JSON (ingested, filtered, classified, themes) |
| Cron schedule | Verify cron expression `0 3 * * 1` = Monday 03:00 UTC |

---

## 7. Quality Gates (Go/No-Go Per Phase)

| Phase | Gate | Minimum criteria |
|---|---|---|
| 0 — Scaffold | Schema deploys | `schema.sql` runs without errors; client connects |
| 1 — Play Store | Data flows | > 100 real records in `raw_records` |
| 2 — Filter + Classify | LLM quality | Groq F1 ≥ 0.87; Gemini per-field accuracy ≥ 0.75 on golden set |
| 3 — Aggregation | Math correct | All unit tests pass; manual score verification on 10 rows |
| 4 — Dashboard | Functional | All acceptance tests pass; notes persist |
| 5 — Scrapers | Multi-source | All 4 sources produce data; incremental dedupe works |
| 6 — Actions | Automation | Scheduled run completes; secrets not leaked; idempotent |
| 7 — Methodology | Documentation | `methodology.md` covers all stated limitations; dashboard reads live Supabase |

---

## 8. Ongoing Monitoring (Post-Launch)

### 8.1 Weekly Quality Checks

After each pipeline run, perform these quick checks:

| Check | How | Time |
|---|---|---|
| Filter false negatives | Sample 20 `discarded` rows; count relevant ones | 10 min |
| Classification spot check | Sample 10 `classified` rows; verify 3 key fields | 15 min |
| Score sanity | Check top-3 themes — do they make intuitive sense? | 5 min |
| New `unmet_need` phrases | Review any new `unmet_need` theme keys | 5 min |

### 8.2 Alert Thresholds

| Metric | Alert if |
|---|---|
| `pipeline_runs.status` | `failed` two consecutive weeks |
| Ingested count | Drops > 50% week-over-week (scraper may be blocked) |
| Filter discard rate | > 80% (prompt may be too aggressive) or < 20% (prompt may be too lenient) |
| Classification `validation_warnings` rate | > 25% (Gemini output quality degrading) |
| Dashboard stale data | `week_start` is > 10 days old |
