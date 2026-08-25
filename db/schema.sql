-- ==========================================================================
-- Schema for the AI-Powered Discovery Engine
-- Supabase (Postgres) — Architecture.md §9
-- ==========================================================================

-- 1. pipeline_runs — one row per pipeline execution
-- ==========================================================================
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    started_at      timestamptz NOT NULL DEFAULT now(),
    finished_at     timestamptz,
    mode            text        NOT NULL CHECK (mode IN ('backfill', 'incremental')),
    status          text        NOT NULL DEFAULT 'running'
                                CHECK (status IN ('running', 'success', 'partial', 'failed')),
    github_run_id   text,
    log_url         text,
    counts          jsonb       DEFAULT '{}'::jsonb,
    error_summary   text,
    watermark       jsonb       DEFAULT '{}'::jsonb
);

-- 2. raw_records — immutable ingested text
-- ==========================================================================
CREATE TABLE IF NOT EXISTS raw_records (
    id              text        PRIMARY KEY,
    source          text        NOT NULL
                                CHECK (source IN (
                                    'play_store', 'reddit', 'youtube', 'app_store',
                                    'product_page', 'twitter', 'community'
                                )),
    brand           text        NOT NULL DEFAULT 'myntra'
                                CHECK (brand IN ('myntra', 'ajio', 'nykaa_fashion')),
    raw_text        text        NOT NULL CHECK (length(trim(raw_text)) > 0),
    date_collected  timestamptz NOT NULL DEFAULT now(),
    date_posted     timestamptz,
    url             text,
    ingest_run_id   uuid        REFERENCES pipeline_runs(id),
    source_meta     jsonb       DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_raw_source_date
    ON raw_records (source, date_posted);
CREATE INDEX IF NOT EXISTS idx_raw_ingest_run
    ON raw_records (ingest_run_id);

-- 3. classified_records — filter + taxonomy tags
-- ==========================================================================
CREATE TABLE IF NOT EXISTS classified_records (
    raw_id                      text PRIMARY KEY REFERENCES raw_records(id),
    filter_status               text NOT NULL
                                CHECK (filter_status IN ('relevant', 'discarded')),
    filtered_at                 timestamptz NOT NULL DEFAULT now(),
    filter_reason               text,

    -- Taxonomy columns (all nullable until Gemini classifies)
    purchase_outcome            text CHECK (purchase_outcome IN (
                                    'purchased', 'not_purchased', 'unclear'
                                )),
    wishlist_motive             text CHECK (wishlist_motive IN (
                                    'liked_product', 'waiting_for_sale', 'saving_for_later',
                                    'comparing_options', 'no_immediate_budget', 'not_stated'
                                )),
    purchase_blocker            text CHECK (purchase_blocker IN (
                                    'price_too_high', 'size_fit_doubt', 'quality_doubt',
                                    'found_alternative', 'no_longer_needed', 'bad_reviews',
                                    'delivery_return_concern', 'forgot', 'not_stated'
                                )),
    post_selection_uncertainty  text CHECK (post_selection_uncertainty IN (
                                    'fit_size', 'quality_material', 'color_accuracy',
                                    'authenticity', 'styling_fit_for_occasion', 'none_stated'
                                )),
    purchase_postponement_reason text CHECK (purchase_postponement_reason IN (
                                    'waiting_for_discount', 'waiting_for_payday_budget',
                                    'waiting_for_occasion', 'seeking_more_reviews',
                                    'comparing_more_options', 'not_stated'
                                )),
    comparison_behavior         text CHECK (comparison_behavior IN (
                                    'price_comparison', 'review_rating_comparison',
                                    'brand_comparison', 'feature_comparison',
                                    'cross_platform_comparison', 'not_mentioned'
                                )),
    external_info_sought        text CHECK (external_info_sought IN (
                                    'youtube_review', 'influencer_opinion',
                                    'friends_family_opinion', 'other_site_price_check',
                                    'other_site_reviews', 'not_mentioned'
                                )),
    fit_size_signal             boolean,
    styling_signal              boolean,
    price_signal                boolean,
    reviews_signal              boolean,
    occasion_signal             boolean,
    social_validation_signal    boolean,
    wishlist_intent_type        text CHECK (wishlist_intent_type IN (
                                    'genuine_intent', 'bookmarking_only', 'unclear'
                                )),
    segment_signal              text CHECK (segment_signal IN (
                                    'gender_context', 'budget_conscious', 'premium_oriented',
                                    'first_time_shopper', 'frequent_shopper', 'not_evident'
                                )),
    unmet_need                  text,
    sentiment                   text CHECK (sentiment IN (
                                    'positive', 'negative', 'neutral'
                                )),

    classified_at               timestamptz,
    model_filter                text,
    model_classify              text,
    validation_warnings         jsonb
);

CREATE INDEX IF NOT EXISTS idx_classified_filter_status
    ON classified_records (filter_status);
CREATE INDEX IF NOT EXISTS idx_classified_unclassified
    ON classified_records (filter_status, classified_at)
    WHERE filter_status = 'relevant' AND classified_at IS NULL;

-- 4. weekly_theme_stats — rollup per (week, theme)
-- ==========================================================================
CREATE TABLE IF NOT EXISTS weekly_theme_stats (
    week_start          date    NOT NULL,
    theme_key           text    NOT NULL,
    theme_field         text    NOT NULL,
    theme_value         text    NOT NULL,
    weekly_count        int     NOT NULL DEFAULT 0,
    cumulative_count    int     NOT NULL DEFAULT 0,
    wow_pct             numeric,

    -- Per-source breakdown
    count_play_store    int     NOT NULL DEFAULT 0,
    count_reddit        int     NOT NULL DEFAULT 0,
    count_youtube       int     NOT NULL DEFAULT 0,
    count_product_page  int     NOT NULL DEFAULT 0,
    count_twitter       int     NOT NULL DEFAULT 0,
    count_community     int     NOT NULL DEFAULT 0,

    -- Conversion mix
    purchased_n         int     NOT NULL DEFAULT 0,
    not_purchased_n     int     NOT NULL DEFAULT 0,
    unclear_n           int     NOT NULL DEFAULT 0,

    PRIMARY KEY (week_start, theme_key)
);

-- 5. opportunity_areas — scored and ranked themes per week
-- ==========================================================================
CREATE TABLE IF NOT EXISTS opportunity_areas (
    week_start          date    NOT NULL,
    theme_key           text    NOT NULL,
    theme_field         text    NOT NULL,
    theme_value         text    NOT NULL,
    frequency           int     NOT NULL,
    severity            int     NOT NULL CHECK (severity BETWEEN 1 AND 3),
    neg_not_purchased_rate numeric,
    trend               text    NOT NULL CHECK (trend IN ('rising', 'flat', 'falling')),
    trend_multiplier    numeric NOT NULL CHECK (trend_multiplier IN (1.2, 1.0, 0.8)),
    wow_pct             numeric,
    score               numeric NOT NULL,
    rank                int     NOT NULL,
    priority            boolean NOT NULL DEFAULT false,
    quote_raw_ids       text[]  DEFAULT '{}',

    PRIMARY KEY (week_start, theme_key)
);

-- 6. opportunity_notes — human "so what" per theme (persists across weeks)
-- ==========================================================================
CREATE TABLE IF NOT EXISTS opportunity_notes (
    theme_key       text        PRIMARY KEY,
    so_what         text        NOT NULL DEFAULT '',
    updated_at      timestamptz NOT NULL DEFAULT now(),
    updated_by      text
);

-- ==========================================================================
-- Views for Streamlit (Architecture §9.8)
-- ==========================================================================

-- Latest week with a successful or partial pipeline run that has rollup data
CREATE OR REPLACE VIEW v_latest_week AS
SELECT MAX(oa.week_start) AS week_start
FROM opportunity_areas oa
JOIN pipeline_runs pr ON pr.status IN ('success', 'partial')
WHERE oa.week_start IS NOT NULL;

-- Opportunity board: areas + stats + notes for the latest week
CREATE OR REPLACE VIEW v_opportunity_board AS
SELECT
    oa.week_start,
    oa.theme_key,
    oa.theme_field,
    oa.theme_value,
    oa.frequency,
    oa.severity,
    oa.neg_not_purchased_rate,
    oa.trend,
    oa.trend_multiplier,
    oa.wow_pct,
    oa.score,
    oa.rank,
    oa.priority,
    oa.quote_raw_ids,
    wts.weekly_count,
    wts.cumulative_count,
    wts.purchased_n,
    wts.not_purchased_n,
    wts.unclear_n,
    COALESCE(n.so_what, '') AS so_what
FROM opportunity_areas oa
JOIN weekly_theme_stats wts
    ON oa.week_start = wts.week_start AND oa.theme_key = wts.theme_key
LEFT JOIN opportunity_notes n
    ON oa.theme_key = n.theme_key
WHERE oa.week_start = (SELECT week_start FROM v_latest_week);

-- Quotes: unnest quote_raw_ids and join to raw_records for text
CREATE OR REPLACE VIEW v_quotes AS
SELECT
    oa.week_start,
    oa.theme_key,
    unnest(oa.quote_raw_ids) AS raw_id,
    rr.raw_text,
    rr.url,
    rr.source
FROM opportunity_areas oa
JOIN raw_records rr ON rr.id = ANY(oa.quote_raw_ids)
WHERE oa.week_start = (SELECT week_start FROM v_latest_week);

-- ==========================================================================
-- Row-Level Security (Architecture §13)
-- ==========================================================================

-- Enable RLS on all tables
ALTER TABLE pipeline_runs       ENABLE ROW LEVEL SECURITY;
ALTER TABLE raw_records         ENABLE ROW LEVEL SECURITY;
ALTER TABLE classified_records  ENABLE ROW LEVEL SECURITY;
ALTER TABLE weekly_theme_stats  ENABLE ROW LEVEL SECURITY;
ALTER TABLE opportunity_areas   ENABLE ROW LEVEL SECURITY;
ALTER TABLE opportunity_notes   ENABLE ROW LEVEL SECURITY;

-- Anon can SELECT all tables (dashboard reads)
CREATE POLICY "anon_read_pipeline_runs"     ON pipeline_runs      FOR SELECT TO anon USING (true);
CREATE POLICY "anon_read_raw_records"       ON raw_records        FOR SELECT TO anon USING (true);
CREATE POLICY "anon_read_classified"        ON classified_records FOR SELECT TO anon USING (true);
CREATE POLICY "anon_read_theme_stats"       ON weekly_theme_stats FOR SELECT TO anon USING (true);
CREATE POLICY "anon_read_opportunity_areas" ON opportunity_areas  FOR SELECT TO anon USING (true);
CREATE POLICY "anon_read_opportunity_notes" ON opportunity_notes  FOR SELECT TO anon USING (true);

-- Anon can INSERT/UPDATE opportunity_notes (for dashboard "so what" edits)
CREATE POLICY "anon_insert_notes" ON opportunity_notes FOR INSERT TO anon WITH CHECK (true);
CREATE POLICY "anon_update_notes" ON opportunity_notes FOR UPDATE TO anon USING (true) WITH CHECK (true);

-- Service role bypasses RLS (pipeline writes use service_role key)
-- No explicit policies needed — service_role has full access by default.

-- Helper RPC for finding records that need filtering
CREATE OR REPLACE FUNCTION public.get_unfiltered_ids()
RETURNS TABLE(id text)
LANGUAGE sql
SECURITY DEFINER
AS $$
    SELECT r.id 
    FROM public.raw_records r 
    LEFT JOIN public.classified_records c ON r.id = c.raw_id 
    WHERE c.raw_id IS NULL;
$$;
