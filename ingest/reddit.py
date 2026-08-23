"""
Reddit scraper for the Discovery Engine.

Searches specified subreddits for Myntra-related queries.
Fetches posts and top-level comments.
"""

import os
import logging
import praw
from datetime import datetime
from prawcore.exceptions import ResponseException

from config.settings import load_sources, REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT
from db.supabase_client import upsert_raw_records

logger = logging.getLogger(__name__)

def get_reddit_client():
    """Initializes and returns the PRAW Reddit client."""
    if not all([REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT]):
        logger.warning("Reddit API credentials not fully configured in .env")
        return None
        
    try:
        reddit = praw.Reddit(
            client_id=REDDIT_CLIENT_ID,
            client_secret=REDDIT_CLIENT_SECRET,
            user_agent=REDDIT_USER_AGENT,
            read_only=True
        )
        return reddit
    except Exception as e:
        logger.error(f"Failed to initialize Reddit client: {e}")
        return None

def fetch_reddit_records(run_id: str, limit_per_query: int = 20) -> dict:
    """
    Fetches Reddit posts and comments based on sources.json config.
    Returns tracking counts.
    """
    counts = {"fetched": 0, "inserted": 0, "skipped_duplicate": 0, "error": 0}
    
    reddit = get_reddit_client()
    use_fallback = False
    if not reddit or REDDIT_CLIENT_ID == "your-reddit-client-id":
        logger.info("Reddit credentials missing or invalid. Using JSON fallback method.")
        use_fallback = True

    sources = load_sources().get("reddit", {})
    subreddits = sources.get("subreddits", [])
    queries = sources.get("search_queries", [])
    
    if not subreddits or not queries:
        logger.info("No subreddits or queries configured. Skipping Reddit ingest.")
        return counts

    # Search each subreddit
    for sub_name in subreddits:
        try:
            if not use_fallback:
                subreddit = reddit.subreddit(sub_name)
                
            logger.info(f"Searching r/{sub_name}...")
            
            for query in queries:
                try:
                    if use_fallback:
                        import requests
                        import urllib.parse
                        import time
                        
                        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
                        encoded_query = urllib.parse.quote(query)
                        url = f"https://www.reddit.com/r/{sub_name}/search.json?q={encoded_query}&restrict_sr=1&sort=new&limit={limit_per_query}"
                        
                        logger.info(f"Fallback JSON fetching: {url}")
                        time.sleep(3.0) # Hard delay to avoid rate limits
                        
                        response = requests.get(url, headers=headers)
                        if response.status_code != 200:
                            logger.error(f"Fallback JSON failed with status {response.status_code}")
                            counts["error"] += 1
                            continue
                            
                        data = response.json()
                        records = []
                        for child in data.get("data", {}).get("children", []):
                            post = child.get("data", {})
                            if not post.get("id"):
                                continue
                                
                            records.append({
                                "id": f"reddit:post:{post.get('id')}",
                                "source": "reddit",
                                "brand": "myntra",
                                "raw_text": f"Title: {post.get('title', '')}\n{post.get('selftext', '')}",
                                "url": f"https://reddit.com{post.get('permalink', '')}",
                                "date_posted": datetime.utcfromtimestamp(post.get("created_utc", 0)).isoformat(),
                                "ingest_run_id": run_id,
                                "source_meta": {
                                    "subreddit": sub_name,
                                    "type": "post",
                                    "score": post.get("score", 0),
                                    "num_comments": post.get("num_comments", 0)
                                }
                            })
                            
                        if records:
                            counts["fetched"] += len(records)
                            res = upsert_raw_records(records)
                            counts["inserted"] += res["inserted"]
                            counts["skipped_duplicate"] += res["skipped_duplicate"]
                            
                    else:
                        # Perform search using PRAW
                        for submission in subreddit.search(query, sort="new", limit=limit_per_query):
                            records = []
                            
                            # 1. Store the post itself
                            post_id = f"reddit:post:{submission.id}"
                            post_text = f"Title: {submission.title}\n{submission.selftext}"
                            post_date = datetime.utcfromtimestamp(submission.created_utc).isoformat()
                            post_url = f"https://reddit.com{submission.permalink}"
                            
                            records.append({
                                "id": post_id,
                                "source": "reddit",
                                "brand": "myntra",
                                "raw_text": post_text,
                                "url": post_url,
                                "date_posted": post_date,
                                "ingest_run_id": run_id,
                                "source_meta": {
                                    "subreddit": sub_name,
                                    "type": "post",
                                    "score": submission.score,
                                    "num_comments": submission.num_comments
                                }
                            })
                            
                            # 2. Store top-level comments
                            submission.comments.replace_more(limit=0) # Only top-level
                            for comment in submission.comments:
                                comment_id = f"reddit:comment:{comment.id}"
                                comment_date = datetime.utcfromtimestamp(comment.created_utc).isoformat()
                                
                                records.append({
                                    "id": comment_id,
                                    "source": "reddit",
                                    "brand": "myntra",
                                    "raw_text": comment.body,
                                    "url": f"https://reddit.com{comment.permalink}",
                                    "date_posted": comment_date,
                                    "ingest_run_id": run_id,
                                    "source_meta": {
                                        "subreddit": sub_name,
                                        "type": "comment",
                                        "score": comment.score,
                                        "parent_post_id": submission.id
                                    }
                                })
                                
                            # Batch insert
                            if records:
                                counts["fetched"] += len(records)
                                res = upsert_raw_records(records)
                                counts["inserted"] += res["inserted"]
                                counts["skipped_duplicate"] += res["skipped_duplicate"]
                                
                except Exception as e:
                    logger.error(f"Error searching query '{query}' in r/{sub_name}: {e}")
                    counts["error"] += 1
                    
        except ResponseException as re:
            if re.response.status_code == 401:
                logger.error("Reddit API Authentication failed. Check your credentials.")
                counts["error"] = 1
                break
        except Exception as e:
            logger.error(f"Error accessing r/{sub_name}: {e}")
            counts["error"] += 1

    logger.info(f"Reddit ingest finished. Counts: {counts}")
    return counts
