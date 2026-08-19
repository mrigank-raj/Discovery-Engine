# Myntra Discovery Engine

An autonomous, AI-powered pipeline that continuously ingests, classifies, scores, and visualizes qualitative user feedback about Myntra across multiple platforms (Google Play Store, Reddit, YouTube).

## Overview

The Discovery Engine eliminates the manual work of reading through thousands of user reviews and forum posts. Instead, it:
1. **Scrapes** data from key user touchpoints.
2. **Filters** out noise (e.g. delivery complaints) using Groq.
3. **Classifies** the remaining relevant feedback using Google Gemini into a rigid taxonomy (Wishlist motives, Purchase blockers, etc).
4. **Scores** each theme based on severity, frequency, and week-over-week trends.
5. **Visualizes** the ranked "Opportunity Areas" in an interactive Streamlit dashboard.

## Folder Structure

- `app/`: Streamlit dashboard (`streamlit run app/streamlit_app.py`)
- `db/`: Supabase schema and database client interface.
- `ingest/`: Scrapers for Google Play Store, Reddit (PRAW), and YouTube (Google API).
- `filter/`: Groq LLM integration to filter out noise.
- `classify/`: Gemini LLM integration to map unstructured text into the taxonomy.
- `aggregate/`: Pandas logic to calculate week-over-week trends and final Opportunity Scores.
- `config/`: JSON configs for search targets (subreddits, video IDs, app details).
- `docs/`: Technical specifications, architecture diagrams, and the original Implementation Plan.

## Getting Started

1. Clone the repository.
2. Create a Python 3.11 virtual environment and `pip install -r requirements.txt`.
3. Rename `.env.example` to `.env` and fill in your API keys (Supabase, Groq, Gemini, Reddit, YouTube).
4. Ensure the database schema is loaded into your Supabase instance (run `db/schema.sql`).
5. Run the pipeline: `python pipeline.py --mode backfill`
6. View the dashboard: `streamlit run app/streamlit_app.py`

## Automation

This repository includes a GitHub Actions workflow (`.github/workflows/weekly-pipeline.yml`) that automatically runs the pipeline in `incremental` mode every Monday morning to pull the latest week's feedback.
