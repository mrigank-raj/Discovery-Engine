"""
Canonical ID generation for each data source.

Every raw_records row has a stable, deterministic `id` so that
re-running ingestion never creates duplicates (ON CONFLICT DO NOTHING).

Formats (Architecture §6.2):
    Play Store  → play:{package}:{reviewId}
    Reddit      → reddit:{fullname}          (t1_ for comment, t3_ for post)
    YouTube     → yt:{commentId}
    Product page → pdp:myntra:{review_key}   (site id or sha256 hash)
    Twitter     → tw:{tweet_id}
    Community   → com:{sha256[:24]}

Edge cases handled:
    - Empty or whitespace-only inputs raise ValueError (Edge_cases §1.1)
    - Inputs are stripped before processing
    - Hash-based IDs are deterministic (same input → same output)
"""

import hashlib


def play_store_id(package: str, review_id: str) -> str:
    """
    Canonical ID for a Google Play Store review.

    Args:
        package: Android package name (e.g. 'com.myntra.android')
        review_id: The reviewId from google-play-scraper

    Returns:
        'play:{package}:{review_id}'

    Raises:
        ValueError: if package or review_id is empty/whitespace
    """
    package = package.strip()
    review_id = review_id.strip()
    if not package:
        raise ValueError("package must not be empty")
    if not review_id:
        raise ValueError("review_id must not be empty")
    return f"play:{package}:{review_id}"


def reddit_id(fullname: str) -> str:
    """
    Canonical ID for a Reddit post or comment.

    Args:
        fullname: Reddit fullname (e.g. 't1_abc123' for comment,
                  't3_def456' for post)

    Returns:
        'reddit:{fullname}'

    Raises:
        ValueError: if fullname is empty/whitespace
    """
    fullname = fullname.strip()
    if not fullname:
        raise ValueError("fullname must not be empty")
    return f"reddit:{fullname}"


def youtube_id(comment_id: str) -> str:
    """
    Canonical ID for a YouTube comment.

    Args:
        comment_id: YouTube comment resource id (e.g. 'Ugw1234abcXyz')

    Returns:
        'yt:{comment_id}'

    Raises:
        ValueError: if comment_id is empty/whitespace
    """
    comment_id = comment_id.strip()
    if not comment_id:
        raise ValueError("comment_id must not be empty")
    return f"yt:{comment_id}"


def product_page_id(review_key: str | None = None, **hash_parts: str) -> str:
    """
    Canonical ID for a Myntra product page review.

    If the site provides a stable review_key (review ID), use it directly.
    Otherwise, compute a SHA256 hash from url + author + date + first200 chars.

    Args:
        review_key: Site review ID if available. If provided and non-empty,
                    used directly.
        **hash_parts: Required if review_key is None/empty. Must include:
                      url, author, date, first200

    Returns:
        'pdp:myntra:{review_key}' or 'pdp:myntra:{sha256[:24]}'

    Raises:
        ValueError: if neither review_key nor hash_parts are sufficient
    """
    if review_key and review_key.strip():
        return f"pdp:myntra:{review_key.strip()}"

    # Fall back to hash
    url = hash_parts.get("url", "").strip()
    author = hash_parts.get("author", "").strip()
    date = hash_parts.get("date", "").strip()
    first200 = hash_parts.get("first200", "").strip()

    concat = f"{url}|{author}|{date}|{first200}"
    if not any([url, author, date, first200]):
        raise ValueError(
            "Either review_key or at least one of (url, author, date, first200) "
            "must be provided for product_page_id"
        )

    hash_hex = hashlib.sha256(concat.encode("utf-8")).hexdigest()[:24]
    return f"pdp:myntra:{hash_hex}"


def twitter_id(tweet_id: str) -> str:
    """
    Canonical ID for a Twitter/X post.

    Args:
        tweet_id: The tweet ID (numeric string)

    Returns:
        'tw:{tweet_id}'

    Raises:
        ValueError: if tweet_id is empty/whitespace
    """
    tweet_id = tweet_id.strip()
    if not tweet_id:
        raise ValueError("tweet_id must not be empty")
    return f"tw:{tweet_id}"


def community_id(
    url: str = "",
    author: str = "",
    date: str = "",
    first200: str = "",
) -> str:
    """
    Canonical ID for a community/forum post (Facebook groups, forums, etc).
    Always hash-based since community threads rarely have stable IDs.

    Args:
        url: Permalink or thread URL
        author: Author name/handle
        date: Post date string
        first200: First 200 characters of the post body

    Returns:
        'com:{sha256[:24]}'

    Raises:
        ValueError: if all inputs are empty
    """
    url = url.strip()
    author = author.strip()
    date = date.strip()
    first200 = first200.strip()

    if not any([url, author, date, first200]):
        raise ValueError(
            "At least one of (url, author, date, first200) must be provided "
            "for community_id"
        )

    concat = f"{url}|{author}|{date}|{first200}"
    hash_hex = hashlib.sha256(concat.encode("utf-8")).hexdigest()[:24]
    return f"com:{hash_hex}"
