# Deployment Guide

This document outlines how to deploy the Wishlist Signal Engine dashboard to evaluators via a public link using Streamlit Community Cloud.

## 1. Prerequisites
Before deploying, ensure you have:
- A GitHub account with access to this repository.
- A free [Streamlit Community Cloud](https://streamlit.io/cloud) account.
- Your Supabase database already running and populated with data.
- Your local `.env` file containing your API keys (these will be securely pasted into Streamlit).

> **Important:** Ensure all your latest local code changes have been committed and pushed to GitHub, as Streamlit Cloud pulls directly from the `main` branch.

## 2. Step-by-Step Deployment Instructions
1. Log in to [share.streamlit.io](https://share.streamlit.io).
2. Click **New app** (or **Deploy an app**).
3. Authorize Streamlit to access your GitHub repositories if prompted.
4. Fill out the deployment form:
   - **Repository:** `mrigank-raj/Discovery-Engine`
   - **Branch:** `main`
   - **Main file path:** `app/streamlit_app.py`
5. Click **Advanced settings** (this is critical for your API keys).
6. Under the **Secrets** section, paste the contents of your local `.env` file exactly as they are formatted locally (TOML format works out of the box with KEY=VALUE). You must include:
   ```toml
   SUPABASE_URL="https://your-project-id.supabase.co"
   SUPABASE_SERVICE_ROLE_KEY="..."
   SUPABASE_ANON_KEY="..."
   GROQ_API_KEY="..."
   GEMINI_API_KEY="..."
   GEMINI_API_KEY_FALLBACK="..."
   REDDIT_CLIENT_ID="..."
   REDDIT_CLIENT_SECRET="..."
   REDDIT_USER_AGENT="..."
   YOUTUBE_API_KEY="..."
   ```
7. Click **Deploy!**

## 3. Note on API Quotas
The AI Executive Synthesis feature relies on the free tiers of Groq and Gemini. Because this is an academic/prototype project relying on free quotas, users may occasionally encounter a temporary rate-limit message in the AI insights section. 

**This is expected behavior.** If this happens, the underlying data pipeline, taxonomy metrics, and opportunity area cards will remain fully functional and visible regardless of the LLM quota status.

## 4. Verification
Once Streamlit finishes booting the app:
1. The dashboard should load and display "Wishlist Signal Engine".
2. The **Opportunity Board** should populate with data fetched from your live Supabase database.
3. The AI Insights sidebar should successfully synthesize a summary based on the current data without throwing an unhandled exception.

## 5. Live Public URL
*After deployment, update this file with your live link:*
**URL:** `[To be filled after deployment]`
