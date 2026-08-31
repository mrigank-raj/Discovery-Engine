"""
Configuration and settings for the Discovery Engine pipeline.

Loads environment variables from .env and provides typed access
to all secrets, source config, and tuning knobs.
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Load .env (no-op if missing — in GitHub Actions, vars come from secrets)
# ---------------------------------------------------------------------------
load_dotenv()

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCES_PATH = PROJECT_ROOT / "config" / "sources.json"
TAXONOMY_PATH = PROJECT_ROOT / "taxonomy.json"
SAMPLE_BOARD_PATH = PROJECT_ROOT / "app" / "sample_board.json"
OPPORTUNITY_NOTES_PATH = PROJECT_ROOT / "data" / "opportunity_notes.json"

# ---------------------------------------------------------------------------
# Supabase
# ---------------------------------------------------------------------------
SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_ANON_KEY: str = os.getenv("SUPABASE_ANON_KEY", "")

# ---------------------------------------------------------------------------
# LLM keys
# ---------------------------------------------------------------------------
GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
GEMINI_API_KEY_FALLBACK: str = os.getenv("GEMINI_API_KEY_FALLBACK", "")

# ---------------------------------------------------------------------------
# Reddit API
# ---------------------------------------------------------------------------
REDDIT_CLIENT_ID: str = os.getenv("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET: str = os.getenv("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT: str = os.getenv(
    "REDDIT_USER_AGENT", "discovery-engine:v1.0 (by /u/unknown)"
)

# ---------------------------------------------------------------------------
# YouTube Data API v3
# ---------------------------------------------------------------------------
YOUTUBE_API_KEY: str = os.getenv("YOUTUBE_API_KEY", "")

# ---------------------------------------------------------------------------
# Pipeline tuning knobs (adjustable per Architecture §14)
# ---------------------------------------------------------------------------
# MAX_FILTER_PER_RUN was 800, which — combined with GROQ_BATCH_SIZE=3 and a
# fixed 2.5s inter-batch sleep tuned only for request-rate (RPM) — took long
# enough that Groq's rate limiter started throwing sustained 429s partway
# through, on what's likely a combined RPM+TPM limit, not request count
# alone. Lowered to a size that reliably completes within a single scheduled
# run even with retry friction, based on the observed real throughput of
# this run (~250-300 records processed in ~9 minutes before it was
# cancelled for taking too long).
MAX_FILTER_PER_RUN: int = int(os.getenv("MAX_FILTER_PER_RUN", "250"))
MAX_CLASSIFY_PER_RUN: int = int(os.getenv("MAX_CLASSIFY_PER_RUN", "300"))
MIN_THEME_COUNT: int = int(os.getenv("MIN_THEME_COUNT", "2"))

# Play Store scraper
PLAY_STORE_MAX_PAGES: int = int(os.getenv("PLAY_STORE_MAX_PAGES", "50"))
PLAY_STORE_CONSECUTIVE_DUPE_PAGES: int = int(
    os.getenv("PLAY_STORE_CONSECUTIVE_DUPE_PAGES", "2")
)
PLAY_STORE_SLEEP_SECONDS: float = float(
    os.getenv("PLAY_STORE_SLEEP_SECONDS", "1.5")
)

# Product page scraper
PDP_SLEEP_SECONDS: float = float(os.getenv("PDP_SLEEP_SECONDS", "1.5"))

# LLM retry
LLM_MAX_RETRIES: int = int(os.getenv("LLM_MAX_RETRIES", "3"))
LLM_BACKOFF_BASE: float = float(os.getenv("LLM_BACKOFF_BASE", "2.0"))

# Groq batching
# Raised from 3 to 5: fewer total API calls for the same record volume
# directly reduces how often the per-minute request-rate limit is hit.
GROQ_BATCH_SIZE: int = int(os.getenv("GROQ_BATCH_SIZE", "5"))

# ---------------------------------------------------------------------------
# Source configuration (from sources.json)
# ---------------------------------------------------------------------------
def load_sources() -> dict:
    """Load source configuration from sources.json."""
    with open(SOURCES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_taxonomy() -> dict:
    """Load the classification taxonomy from taxonomy.json."""
    with open(TAXONOMY_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------
def require_env(name: str) -> str:
    """
    Return the value of an environment variable, raising a clear error
    if it is missing or empty.

    Used at pipeline startup to fail fast on misconfiguration
    (Edge_cases §6.4).
    """
    value = os.getenv(name, "")
    if not value:
        raise EnvironmentError(
            f"Required environment variable '{name}' is not set. "
            f"Check your .env file or GitHub Actions secrets."
        )
    return value


def validate_pipeline_env() -> None:
    """
    Validate that all required environment variables for the pipeline
    are set. Call this at the start of pipeline.py.

    Raises EnvironmentError with the first missing variable.
    """
    required = [
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
        "GROQ_API_KEY",
        "GEMINI_API_KEY",
    ]
    for var in required:
        require_env(var)


def validate_dashboard_env() -> None:
    """
    Validate environment variables required for the Streamlit dashboard.
    The dashboard needs read access only (anon key).
    """
    require_env("SUPABASE_URL")
    require_env("SUPABASE_ANON_KEY")
