"""
YouTube scraper for the Discovery Engine.

Fetches top-level comments from specific video IDs.
"""

import os
import logging
from datetime import datetime
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from config.settings import load_sources, YOUTUBE_API_KEY
from db.supabase_client import upsert_raw_records

logger = logging.getLogger(__name__)

def get_youtube_client():
    """Initializes and returns the YouTube Data API client."""
    if not YOUTUBE_API_KEY or YOUTUBE_API_KEY == "your-youtube-api-key":
        logger.warning("YouTube API key not configured in .env")
        return None
        
    try:
        youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
        return youtube
    except Exception as e:
        logger.error(f"Failed to initialize YouTube client: {e}")
        return None

def fetch_youtube_records(run_id: str, max_pages_per_video: int = 5) -> dict:
    """
    Fetches YouTube comments based on sources.json config.
    Returns tracking counts.
    """
    counts = {"fetched": 0, "inserted": 0, "skipped_duplicate": 0, "error": 0}
    
    youtube = get_youtube_client()
    if not youtube:
        counts["error"] = 1
        return counts

    sources = load_sources().get("youtube", {})
    video_ids = sources.get("video_ids", [])
    search_queries = sources.get("search_queries", ["Myntra haul review"])
    
    videos_to_fetch = []
    
    if video_ids:
        for vid in video_ids:
            videos_to_fetch.append((vid, "manual"))
    else:
        logger.info("No YouTube video IDs configured. Auto-discovering via Search API...")
        for query in search_queries:
            try:
                search_response = youtube.search().list(
                    q=query,
                    part="id",
                    maxResults=5,
                    type="video",
                    order="relevance"
                ).execute()
                found_ids = [item["id"]["videoId"] for item in search_response.get("items", [])]
                logger.info(f"Auto-discovered {len(found_ids)} videos for query '{query}': {found_ids}")
                for vid in found_ids:
                    videos_to_fetch.append((vid, query))
            except Exception as e:
                logger.error(f"Failed to auto-discover videos for query '{query}': {e}")
            
    if not videos_to_fetch:
        logger.info("No YouTube video IDs found. Skipping YouTube ingest.")
        return counts

    for video_id, query_used in videos_to_fetch:
        logger.info(f"Fetching comments for YouTube video: {video_id} (Query: {query_used})")
        
        try:
            next_page_token = None
            pages_fetched = 0
            
            while pages_fetched < max_pages_per_video:
                request = youtube.commentThreads().list(
                    part="snippet",
                    videoId=video_id,
                    maxResults=100,
                    pageToken=next_page_token,
                    textFormat="plainText"
                )
                
                response = request.execute()
                records = []
                
                for item in response.get("items", []):
                    comment = item["snippet"]["topLevelComment"]["snippet"]
                    comment_id = f"youtube:{item['id']}"
                    
                    records.append({
                        "id": comment_id,
                        "source": "youtube",
                        "brand": "myntra",
                        "raw_text": comment["textDisplay"],
                        "url": f"https://www.youtube.com/watch?v={video_id}&lc={item['id']}",
                        "date_posted": comment["publishedAt"], # Already ISO 8601
                        "ingest_run_id": run_id,
                        "source_meta": {
                            "video_id": video_id,
                            "search_query": query_used,
                            "author": comment.get("authorDisplayName", "Unknown"),
                            "like_count": comment.get("likeCount", 0)
                        }
                    })
                    
                if records:
                    counts["fetched"] += len(records)
                    res = upsert_raw_records(records)
                    counts["inserted"] += res["inserted"]
                    counts["skipped_duplicate"] += res["skipped_duplicate"]
                    
                next_page_token = response.get("nextPageToken")
                pages_fetched += 1
                
                if not next_page_token:
                    break
                    
        except HttpError as e:
            if e.resp.status == 403:
                logger.error("YouTube API quota exceeded or key invalid.")
                counts["error"] = 1
                break
            elif e.resp.status == 404:
                logger.warning(f"YouTube video {video_id} not found or comments disabled.")
            else:
                logger.error(f"YouTube API error for video {video_id}: {e}")
                counts["error"] += 1
        except Exception as e:
            logger.error(f"Unexpected error fetching video {video_id}: {e}")
            counts["error"] += 1

    logger.info(f"YouTube ingest finished. Counts: {counts}")
    return counts
