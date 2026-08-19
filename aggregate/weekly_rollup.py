"""
Weekly rollup logic for the Aggregation Engine.

Processes all classified records, explodes them into themes,
and calculates metrics (frequency, severity, trend, score, rank).
Writes results to `weekly_theme_stats` and `opportunity_areas`.
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta, date
from typing import Any

import pandas as pd

from config.settings import load_taxonomy
from db.supabase_client import (
    get_pipeline_client,
    upsert_opportunity_areas,
    upsert_weekly_theme_stats,
)
from aggregate.themes import extract_themes

logger = logging.getLogger(__name__)

def fetch_classified_data() -> pd.DataFrame:
    """Fetch all joined raw and classified records using standard tables."""
    client = get_pipeline_client()
    
    # We fetch raw_records and classified_records.
    # Note: PostgREST embedded querying syntax:
    # select("*, classified_records(*)")
    res = (
        client.table("classified_records")
        .select("*, raw_records(date_posted, source, raw_text, id)")
        .execute()
    )
    
    records = []
    for row in res.data:
        r_row = row.get("raw_records")
        if not r_row:
            continue
            
        if isinstance(r_row, list):
            r_row = r_row[0]
            
        # Flatten
        merged = {**row, **r_row}
        # Remove the nested object
        merged.pop("raw_records", None)
        records.append(merged)
            
    return pd.DataFrame(records)

def calculate_severity(df_theme: pd.DataFrame) -> float:
    """
    Calculate severity based on purchase_outcome and sentiment.
    N = count where purchase_outcome=not_purchased AND sentiment=negative
    rate = N / total_records
    """
    if len(df_theme) == 0:
        return 1.0
        
    n = len(df_theme[(df_theme["purchase_outcome"] == "not_purchased") & (df_theme["sentiment"] == "negative")])
    rate = n / len(df_theme)
    
    if rate >= 0.50:
        return 3.0
    elif rate >= 0.20:
        return 2.0
    else:
        return 1.0

def calculate_trend(current_freq: int, prior_freq: int) -> tuple[str, float, float]:
    """
    Calculate trend status, multiplier, and week-over-week percentage.
    Returns: (trend_str, multiplier, wow_pct)
    """
    if prior_freq == 0:
        if current_freq > 0:
            return "rising", 1.2, None
        return "flat", 1.0, None
        
    wow_pct = (current_freq - prior_freq) / prior_freq
    
    if current_freq > prior_freq * 1.10:
        return "rising", 1.2, wow_pct
    elif current_freq < prior_freq * 0.90:
        return "falling", 0.8, wow_pct
    else:
        return "flat", 1.0, wow_pct

def get_week_start(dt_str: str) -> str:
    """Returns Monday of the week for a given ISO date string."""
    if pd.isna(dt_str):
        dt = datetime.utcnow()
    else:
        dt = pd.to_datetime(dt_str)
    
    # Monday is 0
    start = dt - timedelta(days=dt.weekday())
    return start.strftime("%Y-%m-%d")

def run_weekly_rollup() -> dict:
    """
    Main entry point for Phase 3 aggregation.
    """
    counts = {"themes_processed": 0, "opportunity_areas_upserted": 0, "error": 0}
    logger.info("Starting Weekly Rollup (Aggregation Engine)...")
    
    try:
        df = fetch_classified_data()
    except Exception as e:
        logger.error("Failed to fetch data for aggregation: %s", e)
        counts["error"] = 1
        return counts

    if df.empty:
        logger.info("No classified records found. Skipping rollup.")
        return counts

    taxonomy = load_taxonomy()
    
    # 1. Explode records into (week_start, theme_key, raw_id, source, purchase_outcome, sentiment)
    exploded = []
    
    for _, row in df.iterrows():
        record = row.to_dict()
        themes = extract_themes(record, taxonomy)
        week_start = get_week_start(record.get("date_posted"))
        
        for t in themes:
            exploded.append({
                "raw_id": record["id"],
                "week_start": week_start,
                "theme_key": t,
                "source": record.get("source"),
                "purchase_outcome": record.get("purchase_outcome", "unclear"),
                "sentiment": record.get("sentiment", "neutral"),
                "raw_text_len": len(str(record.get("raw_text", "")))
            })

    if not exploded:
        logger.info("No themes extracted. Skipping rollup.")
        return counts

    df_exp = pd.DataFrame(exploded)
    
    # Ensure chronological sort of weeks for trend calculation
    weeks = sorted(df_exp["week_start"].unique())
    
    stats_rows = []
    opp_rows = []
    
    cumulative_counts = defaultdict(int)
    prior_week_counts = defaultdict(int)
    
    for week in weeks:
        df_week = df_exp[df_exp["week_start"] == week]
        themes_in_week = df_week["theme_key"].unique()
        
        week_opps = []
        
        for theme in themes_in_week:
            df_theme = df_week[df_week["theme_key"] == theme]
            weekly_count = len(df_theme)
            
            cumulative_counts[theme] += weekly_count
            cum_count = cumulative_counts[theme]
            
            prior_count = prior_week_counts[theme]
            trend_str, multiplier, wow_pct = calculate_trend(weekly_count, prior_count)
            
            severity = calculate_severity(df_theme)
            score = weekly_count * severity * multiplier
            
            # Sub-counts
            sources_counts = df_theme["source"].value_counts().to_dict()
            po_counts = df_theme["purchase_outcome"].value_counts().to_dict()
            
            purchased_n = po_counts.get("purchased", 0)
            not_purchased_n = po_counts.get("not_purchased", 0)
            unclear_n = po_counts.get("unclear", 0)
            
            # Select quotes (up to 5)
            # Prefer not_purchased + negative, length 80-400
            def score_quote(r):
                pts = 0
                if r["purchase_outcome"] == "not_purchased" and r["sentiment"] == "negative":
                    pts += 10
                if 80 <= r["raw_text_len"] <= 400:
                    pts += 5
                return pts
                
            df_theme_copy = df_theme.copy()
            df_theme_copy["quote_score"] = df_theme_copy.apply(score_quote, axis=1)
            # Sort by score desc, then id to be stable
            df_theme_sorted = df_theme_copy.sort_values(by=["quote_score", "raw_id"], ascending=[False, True])
            
            # Diversify source (round-robin)
            selected_quotes = []
            seen_sources = set()
            for _, r in df_theme_sorted.iterrows():
                src = r["source"]
                if src not in seen_sources or len(selected_quotes) >= len(df_theme_sorted["source"].unique()):
                    selected_quotes.append(r["raw_id"])
                    seen_sources.add(src)
                if len(selected_quotes) >= 5:
                    break
                    
            theme_parts = theme.split(":", 1)
            theme_field = theme_parts[0]
            theme_value = theme_parts[1] if len(theme_parts) > 1 else ""
            
            stats_rows.append({
                "week_start": week,
                "theme_key": theme,
                "theme_field": theme_field,
                "theme_value": theme_value,
                "weekly_count": weekly_count,
                "cumulative_count": cum_count,
                "wow_pct": wow_pct,
                "count_play_store": sources_counts.get("play_store", 0),
                "count_reddit": sources_counts.get("reddit", 0),
                "count_youtube": sources_counts.get("youtube", 0),
                "purchased_n": purchased_n,
                "not_purchased_n": not_purchased_n,
                "unclear_n": unclear_n,
            })
            
            week_opps.append({
                "week_start": week,
                "theme_key": theme,
                "theme_field": theme_field,
                "theme_value": theme_value,
                "frequency": weekly_count,
                "severity": severity,
                "trend": trend_str,
                "score": score,
                "quote_raw_ids": selected_quotes,
            })
            
            # Update prior for next week
            prior_week_counts[theme] = weekly_count
            
        # Rank and Priority for this week
        if week_opps:
            df_opps = pd.DataFrame(week_opps)
            # Rank desc by score, then freq, then theme_key
            df_opps.sort_values(by=["score", "frequency", "theme_key"], ascending=[False, False, True], inplace=True)
            df_opps["rank"] = range(1, len(df_opps) + 1)
            
            p75 = df_opps["score"].quantile(0.75)
            df_opps["priority"] = (df_opps["rank"] <= 3) | (df_opps["score"] >= p75)
            
            opp_rows.extend(df_opps.to_dict(orient="records"))

    try:
        upsert_weekly_theme_stats(stats_rows)
        upsert_opportunity_areas(opp_rows)
        counts["themes_processed"] = len(stats_rows)
        counts["opportunity_areas_upserted"] = len(opp_rows)
    except Exception as e:
        logger.error("Failed to upsert rollup data: %s", e)
        counts["error"] = 1

    logger.info("Weekly Rollup finished. %d themes stats, %d opp areas upserted.", len(stats_rows), len(opp_rows))
    return counts
