# Context — AI-Powered Discovery Engine

NextLeap Grad Project. **Myntra only** — fashion e-commerce wishlist-to-purchase behavior.

AJIO, Nykaa, and other marketplaces are out of scope. Do not scrape, tag, or rank them. AJIO/other platforms surface only incidentally, when a Myntra user mentions comparing to another site (captured by `comparison_behavior: cross_platform_comparison` and `external_info_sought: other_site_price_check` in the taxonomy). This is a stated scoping decision, not a gap.

This file is the working brief for later implementation. Scope is **Myntra only** (this file + Architecture.md + ProblemStatement.txt).

---

## Problem

Build a **system** (not a one-off manual review) that analyzes user feedback about **Myntra** at scale, on an ongoing basis, and surfaces **ranked, quantified opportunity areas** tied to a specific business metric: **wishlist-to-purchase conversion within 30 days**.

The engine must go beyond summarization and sentiment. It must answer the following with **evidence and frequency data**:

1. Why users add products to wishlists
2. What prevents wishlisted products from being purchased
3. What uncertainties remain after a product is shortlisted
4. What causes purchase postponement
5. How users compare multiple shortlisted products
6. What information users seek outside Myntra before buying
7. The role of fit, size, styling, price, reviews, occasion, and social validation
8. When wishlist behavior is genuine intent vs. bookmarking
9. How these behaviors differ across user segments
10. What unmet needs recur consistently across conversations

**No monetary-incentive solutions are in scope** for the eventual product recommendation — this discovery engine exists to find the underlying problem first, before any solution is proposed.

---

## North-star metric

**Wishlist-to-purchase conversion within 30 days.**

Every other tag is only useful if it can be compared against `purchase_outcome` (`purchased` / `not_purchased` / `unclear`). Without that field, themes cannot be tied to conversion. The 30-day window anchors what "conversion" means in this context — a wishlisted product that is purchased within 30 days counts; beyond that, the intent is likely stale.

---

## Design principles

- **Living pipeline, not a snapshot.** New reviews and discussions appear daily. Refresh weekly so opportunities can be tracked by **trend** (growing / shrinking) as well as raw frequency.
- **Free-tier only.** No paid APIs, no subscriptions.
- **Evidence over summaries.** Ranked opportunities with counts, quotes, and conversion-linked severity. Do not split the dashboard by channel or competitor.
- **Discovery before solution.** The engine identifies the problem; it does not propose fixes. No monetary-incentive solutions.

---

## Data sources

### Automated (weekly)

| Source | What | How |
|---|---|---|
| Google Play Store | Myntra app reviews only | `google-play-scraper` |
| Reddit | r/IndianFashionAddicts, r/india, plus keyword search (`Myntra`, `wishlist`, `size chart`, `return`, `Myntra vs`); retain Myntra-relevant text only | Reddit API, free tier |
| YouTube | Comments on ~10–15 seed **Myntra** haul/review videos | YouTube Data API v3, free quota |
| Product pages | On-site **Myntra** product reviews | Public HTML scrape (no API) |

The `Myntra vs` keyword is included deliberately to catch cross-platform comparison mentions (users contrasting Myntra with other sites), which feeds `comparison_behavior: cross_platform_comparison`.

### Manual (occasional)

- **Twitter/X** — a few relevant **Myntra** public posts every 1–2 weeks
- **Fashion/shopping communities and Facebook Groups** — a few relevant **Myntra** threads occasionally

### Scoping decisions (not gaps)

- **Myntra only.** AJIO and Nykaa are excluded from ingest, taxonomy comparisons, and the dashboard.
- Apple App Store is excluded: Android-first market; extra scrape complexity for marginal signal.

---

## Collection cadence

**Day 1 — one-time backfill**

- Play Store: full pagination
- YouTube: all comments from seed videos
- Reddit: up to the free API ceiling (~1000 results per query)
- Product pages: first full scrape (starting snapshot; pages have no historical archive)

This establishes a solid starting dataset from day one instead of waiting weeks to accumulate volume.

**Every week after — incremental**

- Same four scrapers via scheduled GitHub Actions
- Pull only **new** items since last run, **deduped by ID**
- New records flow through filter → classify → aggregate automatically
- Dataset and trend series grow across the ~20-day project window

**Stated limitations (document in methodology; do not hide)**

- Reddit free API caps ~1000 results per query — bounds how far back Reddit data goes
- Product-page scrape has no archive; "past" = everything live on day 1, not true history
- Twitter/X and community data are manual and present-only; not backfillable

---

## Pipeline

**Ingestion → Filtering → Classification → Aggregation → Presentation**

```text
scrapers (weekly cron)
    → store raw records in Supabase (immutable text)
    → Groq relevance filter
    → Gemini structured classification (fixed taxonomy)
    → weekly rollup + opportunity score
    → Streamlit dashboard
```

### 1. Ingestion

Python scrapers per automated source. Triggered weekly by GitHub Actions (free scheduled cron, no trial expiry risk).

### 2. Storage

**Supabase (Postgres)**, free tier. Day-1 backfill will exceed Airtable's free ~1,000-record cap; Supabase provides a unique `id` constraint, SQL rollups, and RLS.

Airtable is **not** in the design.

Raw schema:

- `id` — stable, source-native primary key
- `source` — `play_store` | `reddit` | `youtube` | `product_page` | `twitter` | `community`
- `brand` — always `myntra` for retained rows
- `raw_text` — body only; strip HTML; skip empty
- `date_collected` — `now()` at insert
- `date_posted` — source timestamp; null if unknown
- `url` — permalink
- `ingest_run_id` — current pipeline run
- `source_meta` — adapter leftovers (rating, subreddit, video_id, product_id); for debug/methodology, not classified

**Raw text is never overwritten.** Classification output is stored in a separate `classified_records` table linked by `raw_id`.

`source` is retained for methodology/debugging purposes only, not surfaced as a dashboard comparison feature.

### 3. Filtering

**Groq** (free-tier, fast open models): first-pass relevance filter. Discard spam and off-topic before they consume Gemini quota — a deliberate cost/quality tradeoff.

### 4. Classification

**Gemini API** (Google AI Studio free tier). Tag each surviving record against the fixed taxonomy below. Structured JSON output only.

### 5. Aggregation

Weekly rollup:

- Theme counts (weekly + cumulative)
- Week-over-week % change
- Representative quotes per theme

**Opportunity Score = Frequency × Severity × Trend Multiplier**

- **Frequency:** raw mentions per theme per week
- **Severity (1–3):** detected automatically from co-occurrence of `purchase_outcome: not_purchased` and negative `sentiment` — not manually guessed
- **Trend multiplier vs. prior week's average:** rising ×1.2 / flat ×1.0 / falling ×0.8

### 6. Presentation

Dashboard (Streamlit) showing ranked Myntra opportunity areas with an explicit link from each theme to wishlist→purchase conversion impact. Weekly refresh only — not real-time.

**Dashboard features (all filters/formatting on data already computed — no new pipeline components):**

1. **Question view filter** — filter the list by which brief question it maps to (e.g. "purchase blockers only," "comparison behavior only") instead of one mixed list.
2. **"So what" column** — one manually-written line per opportunity area translating the theme into a business implication. Written by hand during weekly review, not AI-generated.
3. **Priority threshold flag** — themes crossing a defined opportunity score are flagged "priority," making the ranked list skimmable.
4. **Trend arrows/sparkline per theme** — the computed week-over-week % change rendered as ↑/↓/→ or a small line chart.
5. **This week / All time toggle** — weekly vs cumulative mention counts; score recalculated for the selected period.

**Not in the UI:** platform or channel comparison (Play vs Reddit vs YouTube vs PDP), AJIO, channel source mix charts, PDF export, auto-refresh.

### Automation

GitHub Actions weekly workflow for the full pipeline. Timestamped, inspectable execution log as proof of repeated operation.

---

## Classification taxonomy

Mapped 1:1 to the brief's questions. **Do not add fields or enums beyond this set.**

### Foundational

| Field | Values | Why |
|---|---|---|
| `purchase_outcome` | `purchased` / `not_purchased` / `unclear` | Connects every other tag to conversion. Without this, no theme can be tied to the north-star metric. |

### 1. Why add to wishlist?

**`wishlist_motive`:** `liked_product` / `waiting_for_sale` / `saving_for_later` / `comparing_options` / `no_immediate_budget` / `not_stated`

### 2. What blocks purchase?

**`purchase_blocker`:** `price_too_high` / `size_fit_doubt` / `quality_doubt` / `found_alternative` / `no_longer_needed` / `bad_reviews` / `delivery_return_concern` / `forgot` / `not_stated`

### 3. Post-selection uncertainty

**`post_selection_uncertainty`:** `fit_size` / `quality_material` / `color_accuracy` / `authenticity` / `styling_fit_for_occasion` / `none_stated`

### 4. Purchase postponement

**`purchase_postponement_reason`:** `waiting_for_discount` / `waiting_for_payday_budget` / `waiting_for_occasion` / `seeking_more_reviews` / `comparing_more_options` / `not_stated`

### 5. How users compare shortlists

**`comparison_behavior`:** `price_comparison` / `review_rating_comparison` / `brand_comparison` / `feature_comparison` / `cross_platform_comparison` / `not_mentioned`

### 6. Information sought off-platform

**`external_info_sought`:** `youtube_review` / `influencer_opinion` / `friends_family_opinion` / `other_site_price_check` / `other_site_reviews` / `not_mentioned`

### 7. Role of key factors (independent yes/no; one record can fire several)

- `fit_size_signal`
- `styling_signal`
- `price_signal`
- `reviews_signal`
- `occasion_signal`
- `social_validation_signal`

### 8. Intent vs. bookmarking

**`wishlist_intent_type`:** `genuine_intent` (states plan/timeline to buy) / `bookmarking_only` (no stated intent) / `unclear`

### 9. Segments

**`segment_signal`:** `gender_context` / `budget_conscious` / `premium_oriented` / `first_time_shopper` / `frequent_shopper` / `not_evident`

Tag **only when explicitly evident in the text**. Never infer or guess.

### 10. Recurring unmet needs

**`unmet_need`:** open short-text (e.g. "better size guide", "video try-on", "faster returns"). Aggregate later to surface recurring phrases.

### Supporting

**`sentiment`:** `positive` / `negative` / `neutral`

Needed so counts are meaningful (e.g. "price is great" vs. "price is too high" are opposite signals). Also feeds the severity auto-detection: severity is computed from co-occurrence with `purchase_outcome: not_purchased` and negative `sentiment`.

---

## Out of scope

Do not build:

- AJIO, Nykaa, or other-retailer coverage
- Platform or channel comparison views/toggles
- Predictive modeling
- Unsupervised topic clustering (conflicts with the fixed taxonomy)
- Algorithmic segment inference
- Automated PDF report generation
- Real-time updating (refresh is weekly by design)
- Apple App Store scrape
- Monetary-incentive solutions (the engine discovers problems, not solutions)

---

## Deliverables

1. GitHub repo — scrapers, filter, classifier, aggregator, Actions workflow
2. `taxonomy.json` — machine-readable copy of the schema above
3. Live data store (Supabase) accumulating real weekly data across the project window
4. Dashboard of ranked, trending opportunity areas with quote evidence and explicit tie to wishlist→purchase conversion
5. Methodology note — sources, sample size, taxonomy rationale, tool tradeoffs, stated coverage limitations

---

## Working rules for later implementation

- **Myntra only** — no AJIO, Nykaa, or other retailer ingest. No platform/channel comparison in the dashboard.
- Do not expand the taxonomy past this brief.
- Keep scrapers inside free quotas; incremental + dedupe by ID.
- State coverage limits in the methodology note rather than treating them as bugs.
- "So what" lines on the dashboard are written by a human during weekly review.
- `segment_signal` is evidence-only, never inferred.
- Raw `raw_text` is immutable.
- No monetary-incentive solutions in scope.
- Severity is auto-detected from data, not manually guessed.
- 30-day window defines what "conversion" means.
