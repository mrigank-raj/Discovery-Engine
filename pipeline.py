"""
Main orchestrator for the Discovery Engine pipeline.

CLI Entry Point:
    python pipeline.py --mode backfill
    python pipeline.py --mode incremental
    python pipeline.py --stage aggregate
"""

import argparse
import logging
import sys

from config.settings import validate_pipeline_env
from db.supabase_client import close_pipeline_run, insert_pipeline_run
from ingest.play_store import ingest_play_store
from ingest.reddit import ingest_reddit
from ingest.youtube import ingest_youtube
from filter.groq_filter import run_groq_filter
from classify.gemini_classify import run_gemini_classify

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def run_pipeline(mode: str) -> None:
    """
    Executes the full pipeline in the given mode.
    Phase 1: Only runs Play Store ingest.
    """
    logger.info("Starting pipeline in mode: %s", mode)
    
    # 1. Start run tracking
    try:
        run_id = insert_pipeline_run(mode)
    except Exception as e:
        logger.error("Failed to start pipeline run in DB: %s", e)
        sys.exit(1)

    overall_status = "success"
    counts = {
        "ingest": {
            "play_store": {"fetched": 0, "inserted": 0, "skipped_duplicate": 0, "error": 0},
            # reddit, youtube, product_page to be added
        },
        "filter": {"processed": 0, "relevant": 0, "discarded": 0, "error": 0},
        "classify": {"processed": 0, "success": 0, "invalid_json": 0, "error": 0},
    }
    error_summary = []

    try:
        # ---------------------------------------------------------
        # STAGE 1: INGEST
        # ---------------------------------------------------------
        logger.info("--- STAGE 1: INGEST ---")
        
        # 1A. Play Store
        try:
            play_store_counts = ingest_play_store(mode, run_id)
            counts["ingest"]["play_store"] = play_store_counts
            if play_store_counts.get("error", 0) > 0:
                overall_status = "partial"
                error_summary.append("Play Store ingest encountered errors.")
        except Exception as e:
            logger.exception("Play Store ingest failed entirely.")
            overall_status = "partial"
            error_summary.append(f"Play Store failed: {e}")

        # 1B. Reddit
        try:
            reddit_counts = ingest_reddit(mode, run_id)
            counts["ingest"]["reddit"] = reddit_counts
            if reddit_counts.get("error", 0) > 0:
                overall_status = "partial"
                error_summary.append("Reddit ingest encountered errors.")
        except Exception as e:
            logger.exception("Reddit ingest failed entirely.")
            overall_status = "partial"
            error_summary.append(f"Reddit failed: {e}")

        # 1C. YouTube
        try:
            youtube_counts = ingest_youtube(mode, run_id)
            counts["ingest"]["youtube"] = youtube_counts
            if youtube_counts.get("error", 0) > 0:
                overall_status = "partial"
                error_summary.append("YouTube ingest encountered errors.")
        except Exception as e:
            logger.exception("YouTube ingest failed entirely.")
            overall_status = "partial"
            error_summary.append(f"YouTube failed: {e}")

        # ---------------------------------------------------------
        # STAGE 2: FILTER & CLASSIFY (Phase 2)
        # ---------------------------------------------------------
        logger.info("--- STAGE 2: FILTER ---")
        try:
            filter_counts = run_groq_filter()
            counts["filter"] = filter_counts
            if filter_counts.get("error", 0) > 0:
                overall_status = "partial"
                error_summary.append("Groq filter encountered errors.")
        except Exception as e:
            logger.exception("Groq filter failed entirely.")
            overall_status = "partial"
            error_summary.append(f"Filter failed: {e}")

        logger.info("--- STAGE 2: CLASSIFY ---")
        try:
            classify_counts = run_gemini_classify()
            counts["classify"] = classify_counts
            if classify_counts.get("error", 0) > 0:
                overall_status = "partial"
                error_summary.append("Gemini classify encountered errors.")
        except Exception as e:
            logger.exception("Gemini classify failed entirely.")
            overall_status = "partial"
            error_summary.append(f"Classify failed: {e}")

        # ---------------------------------------------------------
        # STAGE 3: AGGREGATE (Phase 3)
        # ---------------------------------------------------------
        logger.info("--- STAGE 3: AGGREGATE ---")
        try:
            from aggregate.weekly_rollup import run_weekly_rollup
            agg_counts = run_weekly_rollup()
            counts["aggregate"] = agg_counts
            if agg_counts.get("error", 0) > 0:
                overall_status = "partial"
                error_summary.append("Aggregation encountered errors.")
        except Exception as e:
            logger.exception("Aggregation failed entirely.")
            overall_status = "partial"
            error_summary.append(f"Aggregate failed: {e}")

    except Exception as e:
        logger.exception("Unexpected fatal error in pipeline.")
        overall_status = "failed"
        error_summary.append(f"Fatal error: {e}")
    finally:
        # 2. Close run tracking
        summary_str = "; ".join(error_summary) if error_summary else None
        try:
            close_pipeline_run(
                run_id=run_id,
                status=overall_status,
                counts=counts,
                error_summary=summary_str,
            )
            logger.info("Pipeline run closed with status: %s", overall_status)
        except Exception as e:
            logger.error("Failed to close pipeline run in DB: %s", e)
            sys.exit(1)


def run_aggregate_only() -> None:
    """Runs only the aggregation stage (Phase 3)."""
    logger.info("Running stage: aggregate")
    from aggregate.weekly_rollup import run_weekly_rollup
    run_weekly_rollup()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI-Powered Discovery Engine Pipeline")
    parser.add_argument(
        "--mode",
        choices=["backfill", "incremental"],
        help="Run full pipeline in backfill or incremental mode.",
    )
    parser.add_argument(
        "--stage",
        choices=["aggregate"],
        help="Run a specific stage standalone.",
    )

    args = parser.parse_args()

    # Fail fast if environment is misconfigured
    try:
        validate_pipeline_env()
    except EnvironmentError as e:
        logger.error("Environment Validation Failed: %s", e)
        sys.exit(1)

    if args.stage == "aggregate":
        run_aggregate_only()
    elif args.mode:
        run_pipeline(args.mode)
    else:
        parser.print_help()
        sys.exit(1)
