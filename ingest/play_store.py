"""
Play Store scraper for the Discovery Engine.

Handles backfill and incremental fetching of Myntra reviews using google-play-scraper.
Paginated and rate-limited. Idempotent insertion into Supabase raw_records.
"""

import datetime
import logging
import time

from google_play_scraper import Sort, reviews

from config.settings import (
    PLAY_STORE_CONSECUTIVE_DUPE_PAGES,
    PLAY_STORE_MAX_PAGES,
    PLAY_STORE_SLEEP_SECONDS,
    load_sources,
)
from db.supabase_client import upsert_raw_records
from ingest.ids import play_store_id

logger = logging.getLogger(__name__)


def ingest_play_store(mode: str, ingest_run_id: str) -> dict:
    """
    Ingests reviews from Google Play Store.
    
    Args:
        mode: 'backfill' (run up to max_pages) or 'incremental' (stop early on dupes)
        ingest_run_id: UUID of the current pipeline run
        
    Returns:
        dict: {'fetched': int, 'inserted': int, 'skipped_duplicate': int, 'error': int}
    """
    sources = load_sources()
    play_config = sources.get("play_store", {})
    package = play_config.get("package_name", "com.myntra.android")
    country = play_config.get("country", "in")
    lang = play_config.get("language", "en")

    counts = {"fetched": 0, "inserted": 0, "skipped_duplicate": 0, "error": 0}

    continuation_token = None
    consecutive_dupe_pages = 0
    page = 0

    logger.info(
        "Starting Play Store ingest (mode=%s, package=%s)", mode, package
    )

    try:
        while page < PLAY_STORE_MAX_PAGES:
            page += 1
            logger.info("Fetching Play Store page %d...", page)

            try:
                page_reviews, continuation_token = reviews(
                    package,
                    lang=lang,
                    country=country,
                    sort=Sort.NEWEST,
                    count=100,  # 100 per page is a good balance
                    continuation_token=continuation_token,
                )
            except Exception as e:
                logger.error("Failed to fetch Play Store page %d: %s", page, e)
                counts["error"] += 1
                break

            if not page_reviews:
                logger.info("No more reviews found on page %d.", page)
                break

            counts["fetched"] += len(page_reviews)

            # Map to raw_records format
            db_records = []
            for r in page_reviews:
                # Some reviews might have a title, append it to content if present
                # google-play-scraper doesn't typically return 'title' but if it does:
                title = r.get("title")
                raw_text = r["content"]
                if title:
                    raw_text = f"{title}. {raw_text}"

                # Ensure text is valid
                if not raw_text or not raw_text.strip():
                    continue

                # Generate canonical ID
                try:
                    rid = play_store_id(package, r["reviewId"])
                except ValueError:
                    logger.warning("Skipping review due to missing ID components.")
                    continue

                date_posted = r["at"]
                if isinstance(date_posted, datetime.datetime):
                    date_posted_iso = date_posted.isoformat()
                else:
                    date_posted_iso = None

                record = {
                    "id": rid,
                    "source": "play_store",
                    "brand": "myntra",
                    "raw_text": raw_text.strip(),
                    "date_posted": date_posted_iso,
                    "url": f"https://play.google.com/store/apps/details?id={package}&reviewId={r['reviewId']}",
                    "ingest_run_id": ingest_run_id,
                    "source_meta": {
                        "rating": r.get("score"),
                        "thumbsUpCount": r.get("thumbsUpCount"),
                        "at": date_posted_iso,
                        "appVersion": r.get("appVersion"),
                    },
                }
                db_records.append(record)

            if not db_records:
                continue

            # Upsert into DB
            try:
                db_result = upsert_raw_records(db_records)
                inserted = db_result["inserted"]
                skipped = db_result["skipped_duplicate"]
                
                counts["inserted"] += inserted
                counts["skipped_duplicate"] += skipped

                # Incremental stopping condition
                if mode == "incremental" and inserted == 0 and skipped > 0:
                    consecutive_dupe_pages += 1
                    if consecutive_dupe_pages >= PLAY_STORE_CONSECUTIVE_DUPE_PAGES:
                        logger.info(
                            "Stopping incremental run: hit %d consecutive duplicate pages.",
                            PLAY_STORE_CONSECUTIVE_DUPE_PAGES,
                        )
                        break
                else:
                    consecutive_dupe_pages = 0

            except Exception as e:
                logger.error("DB upsert failed for page %d: %s", page, e)
                counts["error"] += 1
                break

            if not continuation_token:
                break

            time.sleep(PLAY_STORE_SLEEP_SECONDS)

    except Exception as e:
        logger.error("Unexpected error in Play Store ingest: %s", e)
        counts["error"] += 1

    logger.info("Play Store ingest finished. Counts: %s", counts)
    return counts
