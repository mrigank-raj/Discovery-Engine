"""
Supabase client module for the Discovery Engine.

Provides a shared client and helper methods for all pipeline stages.
Pipeline uses service_role key (full write access).
Dashboard uses anon key (read-only + notes write via RLS).
"""

import logging
from typing import Any

from supabase import Client, create_client

from config.settings import SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY, SUPABASE_URL

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------

_pipeline_client: Client | None = None
_dashboard_client: Client | None = None


def get_pipeline_client() -> Client:
    """
    Return a Supabase client using the service_role key.
    Used by pipeline.py and all ingest/filter/classify/aggregate modules.
    Raises EnvironmentError if SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY
    is not set.
    """
    global _pipeline_client
    if _pipeline_client is None:
        if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
            raise EnvironmentError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set. "
                "Check your .env file or GitHub Actions secrets."
            )
        _pipeline_client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    return _pipeline_client


def get_dashboard_client() -> Client:
    """
    Return a Supabase client using the anon key.
    Used by Streamlit for reads and opportunity_notes writes.
    Raises EnvironmentError if SUPABASE_URL or SUPABASE_ANON_KEY is not set.
    """
    global _dashboard_client
    if _dashboard_client is None:
        if not SUPABASE_URL or not SUPABASE_ANON_KEY:
            raise EnvironmentError(
                "SUPABASE_URL and SUPABASE_ANON_KEY must be set. "
                "Check your .env file or Streamlit secrets."
            )
        _dashboard_client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    return _dashboard_client


# ---------------------------------------------------------------------------
# Pipeline helper methods
# ---------------------------------------------------------------------------


def insert_pipeline_run(mode: str) -> str:
    """
    Insert a new pipeline_runs row with status='running'.
    Returns the generated run id (uuid as string).
    """
    client = get_pipeline_client()
    result = (
        client.table("pipeline_runs")
        .insert({"mode": mode, "status": "running"})
        .execute()
    )
    run_id = result.data[0]["id"]
    logger.info("Pipeline run started: %s (mode=%s)", run_id, mode)
    return run_id


def close_pipeline_run(
    run_id: str,
    status: str,
    counts: dict | None = None,
    error_summary: str | None = None,
    watermark: dict | None = None,
) -> None:
    """
    Update pipeline_runs with final status, counts, and timestamps.
    Called in the finally block of pipeline.py.
    """
    client = get_pipeline_client()
    update: dict[str, Any] = {
        "status": status,
        "finished_at": "now()",
    }
    if counts is not None:
        update["counts"] = counts
    if error_summary is not None:
        update["error_summary"] = error_summary
    if watermark is not None:
        update["watermark"] = watermark

    client.table("pipeline_runs").update(update).eq("id", run_id).execute()
    logger.info("Pipeline run closed: %s (status=%s)", run_id, status)


def upsert_raw_records(records: list[dict]) -> dict:
    """
    Insert raw records, ignoring duplicates (ON CONFLICT DO NOTHING).
    Returns a dict with counts: {inserted, skipped_duplicate}.

    Each record must have: id, source, raw_text, and optionally
    date_posted, url, ingest_run_id, source_meta.
    """
    if not records:
        return {"inserted": 0, "skipped_duplicate": 0}

    client = get_pipeline_client()
    # Supabase upsert with ignoreDuplicates=True gives ON CONFLICT DO NOTHING
    result = (
        client.table("raw_records")
        .upsert(records, on_conflict="id", ignore_duplicates=True)
        .execute()
    )
    inserted = len(result.data)
    skipped = len(records) - inserted
    logger.info(
        "Raw records: %d inserted, %d skipped (duplicate)", inserted, skipped
    )
    return {"inserted": inserted, "skipped_duplicate": skipped}


def insert_filter_result(
    raw_id: str,
    filter_status: str,
    filter_reason: str | None = None,
    model_filter: str | None = None,
) -> None:
    """
    Insert a classified_records row after Groq filtering.
    All taxonomy columns remain null until Gemini classifies.
    """
    client = get_pipeline_client()
    row = {
        "raw_id": raw_id,
        "filter_status": filter_status,
        "filter_reason": filter_reason,
        "model_filter": model_filter,
    }
    client.table("classified_records").upsert(
        row, on_conflict="raw_id", ignore_duplicates=True
    ).execute()


def update_classification(raw_id: str, tags: dict) -> None:
    """
    Update a classified_records row with Gemini taxonomy tags.
    Sets classified_at to now().
    """
    client = get_pipeline_client()
    update_data = {**tags, "classified_at": "now()"}
    client.table("classified_records").update(update_data).eq(
        "raw_id", raw_id
    ).execute()


def get_unfiltered_raw_ids() -> list[str]:
    """
    Return raw_record IDs that have no classified_records row yet.
    These need to go through the Groq filter.
    """
    client = get_pipeline_client()
    # Select raw_records that have no matching classified_records
    result = client.rpc(
        "get_unfiltered_ids",  # Fallback: use a direct query if RPC not set up
    ).execute()
    return [row["id"] for row in result.data]


def get_unclassified_relevant_ids() -> list[dict]:
    """
    Return classified_records where filter_status='relevant'
    and classified_at IS NULL — these need Gemini classification.
    """
    client = get_pipeline_client()
    result = (
        client.table("classified_records")
        .select("raw_id")
        .eq("filter_status", "relevant")
        .is_("classified_at", "null")
        .execute()
    )
    return [row["raw_id"] for row in result.data]


def get_raw_text(raw_id: str) -> str | None:
    """Fetch raw_text for a given raw_id."""
    client = get_pipeline_client()
    result = (
        client.table("raw_records")
        .select("raw_text, source")
        .eq("id", raw_id)
        .single()
        .execute()
    )
    return result.data if result.data else None


def upsert_weekly_theme_stats(rows: list[dict]) -> None:
    """Upsert weekly_theme_stats rows (idempotent on week_start + theme_key)."""
    if not rows:
        return
    client = get_pipeline_client()
    client.table("weekly_theme_stats").upsert(
        rows, on_conflict="week_start,theme_key"
    ).execute()


def upsert_opportunity_areas(rows: list[dict]) -> None:
    """Upsert opportunity_areas rows (idempotent on week_start + theme_key)."""
    if not rows:
        return
    client = get_pipeline_client()
    client.table("opportunity_areas").upsert(
        rows, on_conflict="week_start,theme_key"
    ).execute()


def upsert_opportunity_note(theme_key: str, so_what: str) -> None:
    """Write or update a 'so what' note for a theme (dashboard use)."""
    client = get_dashboard_client()
    client.table("opportunity_notes").upsert(
        {"theme_key": theme_key, "so_what": so_what, "updated_at": "now()"},
        on_conflict="theme_key",
    ).execute()


# ---------------------------------------------------------------------------
# Dashboard read helpers
# ---------------------------------------------------------------------------


def get_latest_board() -> list[dict]:
    """Read the v_opportunity_board view for the latest week."""
    client = get_dashboard_client()
    result = client.table("v_opportunity_board").select("*").execute()
    return result.data


def get_quotes_for_week() -> list[dict]:
    """Read the v_quotes view for the latest week."""
    client = get_dashboard_client()
    result = client.table("v_quotes").select("*").execute()
    return result.data


def get_last_pipeline_run() -> dict | None:
    """Get the most recent pipeline_runs row."""
    client = get_dashboard_client()
    result = (
        client.table("pipeline_runs")
        .select("*")
        .order("started_at", desc=True)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None
