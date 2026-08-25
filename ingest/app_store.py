"""
App Store scraper for the Discovery Engine.

Fetches recent reviews using Apple's public RSS JSON feed.
Handles Myntra, AJIO, and Nykaa Fashion.
"""

import logging
import time
import requests

from db.supabase_client import upsert_raw_records

logger = logging.getLogger(__name__)

# Configured App Store apps (Name -> App Store ID)
APPS = [
    {"name": "Myntra", "id": "907394059"},
    {"name": "AJIO", "id": "1113425372"},
    {"name": "Nykaa Fashion", "id": "1463326162"}
]

def fetch_app_store_records(run_id: str) -> dict:
    """
    Ingests recent reviews from the Apple App Store RSS feed.
    Loops through Myntra, AJIO, and Nykaa Fashion exactly once (page 1).
    """
    counts = {"fetched": 0, "inserted": 0, "skipped_duplicate": 0, "error": 0}
    
    for app in APPS:
        app_name = app["name"]
        app_id = app["id"]
        # Normalize brand to match database expectations (e.g. "nykaa_fashion")
        brand_key = app_name.lower().replace(" ", "_")
        
        url = f"https://itunes.apple.com/rss/customerreviews/id={app_id}/sortBy=mostRecent/json"
        logger.info("Fetching App Store reviews for %s...", app_name)
        
        try:
            # 1 retry attempt with a 3 second wait for timeouts
            try:
                response = requests.get(url, timeout=30)
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
                logger.warning("App Store request timed out for %s, retrying in 3 seconds...", app_name)
                time.sleep(3)
                response = requests.get(url, timeout=30)
                
            response.raise_for_status()
            data = response.json()
            
            feed = data.get("feed", {})
            entries = feed.get("entry", [])
            
            # The JSON feed sometimes returns a single dict if there's only one entry
            if isinstance(entries, dict):
                entries = [entries]
                
            db_records = []
            for entry in entries:
                # The first entry in the RSS feed is sometimes the app's metadata itself, not a review
                if "author" not in entry or "content" not in entry:
                    continue
                    
                raw_text = entry.get("content", {}).get("label", "").strip()
                title = entry.get("title", {}).get("label", "").strip()
                if title:
                    raw_text = f"{title}. {raw_text}"
                    
                if not raw_text:
                    continue
                    
                review_id = entry.get("id", {}).get("label", "")
                if not review_id:
                    continue
                    
                date_posted = entry.get("updated", {}).get("label", "")
                rating = entry.get("im:rating", {}).get("label", "")
                version = entry.get("im:version", {}).get("label", "")
                author = entry.get("author", {}).get("name", {}).get("label", "")
                
                # Extract review URL if possible, fallback to main app page
                link = ""
                link_data = entry.get("link")
                if isinstance(link_data, dict):
                    link = link_data.get("attributes", {}).get("href", "")
                elif isinstance(link_data, list) and len(link_data) > 0:
                    link = link_data[0].get("attributes", {}).get("href", "")
                
                if not link:
                    link = f"https://apps.apple.com/app/id{app_id}"
                
                record = {
                    "id": f"app_store_{app_id}_{review_id}",
                    "source": "app_store",
                    "brand": brand_key,
                    "raw_text": raw_text.strip(),
                    "date_posted": date_posted,
                    "url": link,
                    "ingest_run_id": run_id,
                    "source_meta": {
                        "rating": int(rating) if isinstance(rating, str) and rating.isdigit() else None,
                        "appVersion": version,
                        "author": author
                    }
                }
                db_records.append(record)
            
            counts["fetched"] += len(db_records)
            
            if db_records:
                try:
                    db_result = upsert_raw_records(db_records)
                    counts["inserted"] += db_result["inserted"]
                    counts["skipped_duplicate"] += db_result["skipped_duplicate"]
                except Exception as e:
                    logger.error("DB upsert failed for App Store %s: %s", app_name, e)
                    counts["error"] += 1
                    
        except Exception as e:
            logger.error("Failed to fetch or process App Store reviews for %s: %s", app_name, e)
            counts["error"] += 1
            
        # Hard delay between apps per requirements
        time.sleep(3)
        
    return counts
