"""
Unit tests for ingest/ids.py — canonical ID generation.

Covers Evals.md §1.1 (ID Canonicalization) and Edge_cases §1.1-1.3.
These tests use hardcoded test inputs to verify ID format correctness
and determinism. No fake data enters the pipeline or database.
"""

import hashlib

import pytest

from ingest.ids import (
    community_id,
    play_store_id,
    product_page_id,
    reddit_id,
    twitter_id,
    youtube_id,
)


# -----------------------------------------------------------------------
# Play Store
# -----------------------------------------------------------------------
class TestPlayStoreId:
    def test_basic(self):
        result = play_store_id("com.myntra.android", "abc123")
        assert result == "play:com.myntra.android:abc123"

    def test_strips_whitespace(self):
        result = play_store_id("  com.myntra.android  ", "  abc123  ")
        assert result == "play:com.myntra.android:abc123"

    def test_empty_package_raises(self):
        with pytest.raises(ValueError, match="package"):
            play_store_id("", "abc123")

    def test_whitespace_package_raises(self):
        with pytest.raises(ValueError, match="package"):
            play_store_id("   ", "abc123")

    def test_empty_review_id_raises(self):
        with pytest.raises(ValueError, match="review_id"):
            play_store_id("com.myntra.android", "")

    def test_deterministic(self):
        id1 = play_store_id("com.myntra.android", "xyz")
        id2 = play_store_id("com.myntra.android", "xyz")
        assert id1 == id2


# -----------------------------------------------------------------------
# Reddit
# -----------------------------------------------------------------------
class TestRedditId:
    def test_comment(self):
        result = reddit_id("t1_xyz789")
        assert result == "reddit:t1_xyz789"

    def test_post(self):
        result = reddit_id("t3_def456")
        assert result == "reddit:t3_def456"

    def test_strips_whitespace(self):
        result = reddit_id("  t1_abc  ")
        assert result == "reddit:t1_abc"

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="fullname"):
            reddit_id("")

    def test_whitespace_raises(self):
        with pytest.raises(ValueError, match="fullname"):
            reddit_id("   ")


# -----------------------------------------------------------------------
# YouTube
# -----------------------------------------------------------------------
class TestYouTubeId:
    def test_basic(self):
        result = youtube_id("Ugw1234abcXyz")
        assert result == "yt:Ugw1234abcXyz"

    def test_strips_whitespace(self):
        result = youtube_id("  Ugw1234  ")
        assert result == "yt:Ugw1234"

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="comment_id"):
            youtube_id("")


# -----------------------------------------------------------------------
# Product page
# -----------------------------------------------------------------------
class TestProductPageId:
    def test_with_site_review_key(self):
        result = product_page_id(review_key="12345")
        assert result == "pdp:myntra:12345"

    def test_with_site_review_key_strips(self):
        result = product_page_id(review_key="  12345  ")
        assert result == "pdp:myntra:12345"

    def test_hash_fallback(self):
        result = product_page_id(
            review_key=None,
            url="https://www.myntra.com/product/123",
            author="user1",
            date="2026-08-01",
            first200="Great quality fabric...",
        )
        assert result.startswith("pdp:myntra:")
        assert len(result.split(":")[-1]) == 24  # sha256[:24]

    def test_hash_deterministic(self):
        kwargs = {
            "url": "https://www.myntra.com/product/123",
            "author": "user1",
            "date": "2026-08-01",
            "first200": "Great quality fabric...",
        }
        id1 = product_page_id(review_key=None, **kwargs)
        id2 = product_page_id(review_key=None, **kwargs)
        assert id1 == id2

    def test_hash_different_inputs(self):
        id1 = product_page_id(
            review_key=None, url="url1", author="a", date="d", first200="t"
        )
        id2 = product_page_id(
            review_key=None, url="url2", author="a", date="d", first200="t"
        )
        assert id1 != id2

    def test_hash_matches_expected(self):
        """Verify the hash is computed correctly."""
        concat = "https://example.com|author|2026-01-01|some text"
        expected_hash = hashlib.sha256(concat.encode("utf-8")).hexdigest()[:24]
        result = product_page_id(
            review_key=None,
            url="https://example.com",
            author="author",
            date="2026-01-01",
            first200="some text",
        )
        assert result == f"pdp:myntra:{expected_hash}"

    def test_all_empty_raises(self):
        with pytest.raises(ValueError):
            product_page_id(review_key=None)

    def test_empty_review_key_uses_hash(self):
        result = product_page_id(
            review_key="", url="https://example.com", author="a", date="d", first200="t"
        )
        assert result.startswith("pdp:myntra:")
        assert len(result.split(":")[-1]) == 24


# -----------------------------------------------------------------------
# Twitter
# -----------------------------------------------------------------------
class TestTwitterId:
    def test_basic(self):
        result = twitter_id("9876543210")
        assert result == "tw:9876543210"

    def test_strips_whitespace(self):
        result = twitter_id("  9876543210  ")
        assert result == "tw:9876543210"

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="tweet_id"):
            twitter_id("")


# -----------------------------------------------------------------------
# Community
# -----------------------------------------------------------------------
class TestCommunityId:
    def test_basic(self):
        result = community_id(
            url="https://forum.example.com/thread/123",
            author="user1",
            date="2026-08-01",
            first200="I had trouble with the size chart...",
        )
        assert result.startswith("com:")
        assert len(result.split(":")[-1]) == 24

    def test_deterministic(self):
        kwargs = {
            "url": "https://forum.example.com/thread/123",
            "author": "user1",
            "date": "2026-08-01",
            "first200": "Test text here",
        }
        id1 = community_id(**kwargs)
        id2 = community_id(**kwargs)
        assert id1 == id2

    def test_different_inputs(self):
        id1 = community_id(url="url1", author="a", date="d", first200="t")
        id2 = community_id(url="url2", author="a", date="d", first200="t")
        assert id1 != id2

    def test_all_empty_raises(self):
        with pytest.raises(ValueError):
            community_id()

    def test_partial_inputs_ok(self):
        """At least one field is enough."""
        result = community_id(url="https://example.com")
        assert result.startswith("com:")

    def test_strips_whitespace(self):
        id1 = community_id(url="https://example.com")
        id2 = community_id(url="  https://example.com  ")
        assert id1 == id2
