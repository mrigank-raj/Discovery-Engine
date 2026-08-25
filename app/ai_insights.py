"""
AI Insights generation module for the Myntra PM Discovery Engine.
Uses Gemini API to synthesize weekly executive summaries and answer PM queries.
"""
import os
import json
import logging
import google.generativeai as genai
from groq import Groq
from config.settings import GEMINI_API_KEY, GROQ_API_KEY

logger = logging.getLogger(__name__)

# Configure Gemini
if GEMINI_API_KEY and GEMINI_API_KEY != "your-gemini-api-key":
    genai.configure(api_key=GEMINI_API_KEY)

def generate_with_fallback(prompt: str) -> str:
    """Try Gemini first, fallback to Groq if quota is exceeded."""
    try:
        if not GEMINI_API_KEY or GEMINI_API_KEY == "your-gemini-api-key":
            raise ValueError("Gemini API key missing")
        model = genai.GenerativeModel('gemini-3.5-flash')
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        logger.warning(f"Gemini generation failed ({e}), falling back to Groq.")
        if not GROQ_API_KEY or GROQ_API_KEY == "your-groq-api-key":
            logger.error("No Groq fallback key available.")
            return "⚠️ **AI synthesis is temporarily unavailable due to API rate limits — the opportunity data below is unaffected and fully up to date.**"
        
        try:
            client = Groq(api_key=GROQ_API_KEY)
            response = client.chat.completions.create(
                model="openai/gpt-oss-20b",
                messages=[
                    {"role": "system", "content": "You are a senior PM assistant."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2
            )
            return response.choices[0].message.content
        except Exception as groq_e:
            logger.error(f"Groq fallback also failed. Gemini: {e} | Groq: {groq_e}")
            return "⚠️ **AI synthesis is temporarily unavailable due to API rate limits — the opportunity data below is unaffected and fully up to date.**"

def generate_executive_synthesis(df_board, df_quotes, week_start):
    """
    Generates a Staff-PM level executive synthesis of the week's data.
    Decomposes Wishlist -> Purchase Conversion into product outcomes and user behaviors.
    """
    if df_board.empty:
        return "No data available for synthesis this week."

    # Prepare data context for the AI
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

RULES FOR NARRATIVE TONE & CONFIDENCE:
1. Match your confidence language to the sample size. If frequency_mentions is 1-2, describe it as 'a single/early signal' or 'worth monitoring, low volume' — never use language like 'critical,' 'clear drop-off,' 'rising friction,' or 'requires targeted action' for anything with frequency_mentions below 5. If frequency_mentions is 5-10, you may use moderate language like 'an emerging pattern.' Only use strong language ('significant,' 'primary driver') for frequency_mentions above 10.
2. Do not invent causal narrative connectors that aren't in the data — phrases like 'indicating a clear drop-off,' 'stalls checkout motivation,' or 'accelerating their decision to purchase' assert a mechanism the raw counts don't establish. State the finding plainly (e.g. 'X was mentioned N times') and let the number speak for itself rather than dressing it in a confident causal story.
3. Do not recommend or imply solutions or incentives (e.g. 'requires targeted activation incentives') — this synthesis describes patterns only, it does not prescribe actions. This rule was already established and must continue to apply.
4. At the top of the synthesis output, before any insight cards, include one honest sentence stating the total sample size analyzed this run (e.g. 'Based on N classified signals this week') so readers can calibrate confidence in what follows.

TASK:
Write a concise, high-impact Executive Synthesis tailored specifically for Growth PMs. 
You MUST format your output as 3-4 distinct "Insight Cards" rather than a wall of text.
For each insight, provide:
- A bold, punchy title (e.g., **01 — Delivery uncertainty is a recurring purchase barrier**)
- A short 1-2 sentence explanation.
- Only mention a segment (e.g. first-time shoppers, price-sensitive users) if the word 'segment' or a specific named group appears in the underlying theme data provided. If no segment information is present in the context_data for this theme, omit any mention of a segment entirely — do not guess, infer, or generalize one. Do not fabricate demographic labels like 'Gen Z' or 'Tier 2 users' under any circumstances unless that exact information is present in the input data.

Every number you report (severity score, frequency, impact score) must be copied exactly from the context_data provided — never estimate, round dramatically, or invent a number not present in the input.

After the insight cards, you MUST explicitly break down the core business metric: **Wishlist → Purchase Conversion (within 30 days)**.

Decompose this metric into:
1. The **User Behaviors** that are currently causing friction or driving intent (based on the data).

Do NOT just list the data. Synthesize it. Tell the Growth PMs exactly what the data means for the business.
Format with clean markdown for readability. Do not use greeting/closing phrases, just output the structured synthesis.
"""
    return generate_with_fallback(prompt)


def ask_the_engine(question, df_board):
    """
    Guarded chat interface for PMs to ask questions about the data.
    """
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
    return generate_with_fallback(prompt)
