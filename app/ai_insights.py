"""
AI Insights generation module for the Myntra PM Discovery Engine.
Uses Gemini API to synthesize weekly executive summaries and answer PM queries.
"""
import os
import json
import logging
import google.generativeai as genai
from config.settings import GEMINI_API_KEY

logger = logging.getLogger(__name__)

# Configure Gemini
if GEMINI_API_KEY and GEMINI_API_KEY != "your-gemini-api-key":
    genai.configure(api_key=GEMINI_API_KEY)

def generate_executive_synthesis(df_board, df_quotes, week_start):
    """
    Generates a Staff-PM level executive synthesis of the week's data.
    Decomposes Wishlist -> Purchase Conversion into product outcomes and user behaviors.
    """
    if not GEMINI_API_KEY or GEMINI_API_KEY == "your-gemini-api-key":
        return "⚠️ **AI Insights Disabled**: Gemini API key is missing. Please configure it in the .env file."
        
    if df_board.empty:
        return "No data available for synthesis this week."

    # Prepare data context for the AI
    # We take the top 15 highest-scoring opportunity areas across all questions
    top_opps = df_board.sort_values(by="score", ascending=False).head(15)
    
    context_data = []
    for _, row in top_opps.iterrows():
        theme = f"{row.get('theme_field', '')}: {row.get('theme_value', '')}"
        context_data.append({
            "theme": theme,
            "frequency_mentions": row.get("frequency", 0),
            "severity_score": row.get("severity", 1),
            "trend": row.get("trend", "flat"),
            "overall_impact_score": row.get("score", 0)
        })

    prompt = f"""
You are a Staff Product Manager on the Growth Team at Myntra, presenting a weekly Discovery Engine synthesis to your leadership team.
Your company’s strategic goal is to: "Increase the percentage of users who purchase at least one item from their wishlist within 30 days of adding it."
Improving this metric increases purchase frequency, improves monetization from existing users, and extracts greater value from high-intent demand.

Here is the raw data for the highest-scoring opportunity areas discovered this week ({week_start}):
{json.dumps(context_data, indent=2)}

TASK:
Write a concise, high-impact Executive Synthesis tailored specifically for Growth PMs. 
You MUST format your output as 3-4 distinct "Insight Cards" rather than a wall of text.
For each insight, provide:
- A bold, punchy title (e.g., **01 — Delivery uncertainty is a recurring purchase barrier**)
- A short 1-2 sentence explanation.
- The relevant segment or signal strength if applicable.

After the insight cards, you MUST explicitly break down the core business metric: **Wishlist → Purchase Conversion (within 30 days)**.

Decompose this metric into:
1. The **User Behaviors** that are currently causing friction or driving intent (based on the data).
2. The specific **Product Outcomes** that Growth PMs need to drive in order to unblock that conversion and improve the metric.
3. **Actionable User Research Hypotheses**: Provide 2-3 specific, testable hypotheses derived from these insights that a PM could immediately take to a User Research team to validate.
   - **CRITICAL**: Assume Myntra already has baseline e-commerce features (e.g., standard 14-day return policies, standard delivery dates on the Product Page, standard wishlists). 
   - DO NOT suggest building things Myntra already has. 
   - Instead, your hypotheses MUST focus on novel Growth tactics, discovery UX improvements, context-aware nudges (e.g., surfacing existing policies dynamically in the Wishlist), urgency triggers, or addressing specific friction points in new ways.

Do NOT just list the data. Synthesize it. Tell the Growth PMs exactly what the data means for the business.
Format with clean markdown for readability. Do not use greeting/closing phrases, just output the structured synthesis.
"""

    try:
        model = genai.GenerativeModel('gemini-3.5-flash')
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        logger.error(f"Failed to generate synthesis: {e}")
        return f"⚠️ **AI Synthesis Error**: Failed to generate insights. ({str(e)})"


def ask_the_engine(question, df_board):
    """
    Guarded chat interface for PMs to ask questions about the data.
    """
    if not GEMINI_API_KEY or GEMINI_API_KEY == "your-gemini-api-key":
        return "⚠️ **AI Insights Disabled**: Gemini API key is missing."

    # Prepare context (top 30 themes)
    top_opps = df_board.sort_values(by="score", ascending=False).head(30)
    context_data = []
    for _, row in top_opps.iterrows():
        context_data.append({
            "theme_category": row.get('theme_field', ''),
            "theme_value": row.get('theme_value', ''),
            "score": row.get("score", 0),
            "trend": row.get("trend", "flat")
        })

    prompt = f"""
You are the AI brain behind the Myntra Discovery Engine. A Myntra Product Manager is asking you a question about user behavior, wishlist intent, and purchase conversion.

GUARDRAIL POLICY:
You are STRICTLY FORBIDDEN from answering questions that are unrelated to Myntra, e-commerce, shopping behavior, or the provided dataset. If the PM asks you to write code, tell a joke, or answer general knowledge questions, you MUST refuse and state: "I am the Discovery Engine. I can only assist with product insights related to Myntra user behavior and the current dataset."

Here is the current dataset of top user behavior themes:
{json.dumps(context_data, indent=2)}

PM's Question: "{question}"

Answer the question professionally, directly referencing the dataset where possible to provide trustable, data-backed insights.
"""

    try:
        model = genai.GenerativeModel('gemini-3.5-flash')
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        logger.error(f"Failed to answer query: {e}")
        return f"⚠️ Error generating response: {str(e)}"
