"""
Groq filtering stage.

Filters incoming raw records to separate genuine Myntra shopping behavior
from spam, off-topic content, or mentions of other retailers only.
Relevant records proceed to Gemini classification.
"""

import json
import logging
import time
from typing import Any, Tuple

from groq import Groq, InternalServerError, RateLimitError
import google.generativeai as genai
from google.generativeai.types import GenerationConfig

from config.settings import (
    GROQ_API_KEY,
    GEMINI_API_KEY,
    GEMINI_API_KEY_FALLBACK,
    GROQ_BATCH_SIZE,
    LLM_BACKOFF_BASE,
    LLM_MAX_RETRIES,
    MAX_FILTER_PER_RUN,
)
from db.supabase_client import (
    get_raw_text,
    get_unfiltered_raw_ids,
    insert_filter_result,
)

logger = logging.getLogger(__name__)

# Use a fast model for the binary classification gate
GROQ_MODEL = "openai/gpt-oss-20b"

SYSTEM_PROMPT = """
You are a data filtering assistant. Your job is to identify if user-generated texts are relevant to Myntra shopping behavior.
A text is RELEVANT if it discusses:
- Adding items to a wishlist or shortlist
- Purchasing or intent to purchase on Myntra
- Returning items on Myntra
- Fit, size, quality, price, or reviews of Myntra products

A text is NOT RELEVANT (discarded) if it is:
- Spam, gibberish, or generic praise ("nice video", "first comment")
- Completely off-topic (politics, memes, non-shopping content)
- Exclusively about other retailers (AJIO, Nykaa, Amazon) with no Myntra context
- About app crashes or bugs with no connection to shopping behavior

You must reply in strict JSON format matching exactly this schema:
{
  "results": [
    {
      "id": "the_exact_input_id",
      "relevant": true/false,
      "reason": "Short 1-sentence explanation"
    }
  ]
}
"""

def get_groq_client():
    if not GROQ_API_KEY:
        return None
    return Groq(api_key=GROQ_API_KEY)

def get_gemini_client(api_key: str) -> Any:
    if not api_key:
        return None
    genai.configure(api_key=api_key)
    return genai.GenerativeModel(
        model_name="gemini-3.5-flash",
        system_instruction=SYSTEM_PROMPT.strip()
    )


def filter_batch(batch: list[dict]) -> Tuple[dict[str, Any], str]:
    """
    Call LLM to filter a batch of records, falling back from Groq to Gemini Primary to Gemini Fallback.
    Returns (dict mapping raw_id -> {'relevant': bool, 'reason': str}, model_used)
    """
    # Prepare the user prompt with the batch
    user_content = {"texts": batch}
    user_prompt = json.dumps(user_content, ensure_ascii=False)
    
    MAX_RETRIES = 3

    # 1. Primary: Groq
    groq_client = get_groq_client()
    if groq_client:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT.strip()},
            {"role": "user", "content": user_prompt},
        ]
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = groq_client.chat.completions.create(
                    model=GROQ_MODEL,
                    messages=messages,
                    response_format={"type": "json_object"},
                    temperature=0.0,
                )
                content = response.choices[0].message.content
                if not content:
                    raise ValueError("Empty response from Groq")
                parsed = json.loads(content)
                if "results" not in parsed:
                    raise ValueError("Response missing 'results' array")

                mapped_results = {}
                for res in parsed["results"]:
                    if "id" in res and "relevant" in res:
                        mapped_results[res["id"]] = {
                            "relevant": bool(res["relevant"]),
                            "reason": res.get("reason", ""),
                        }
                return mapped_results, "groq:openai/gpt-oss-20b"
            except json.JSONDecodeError:
                logger.error("Groq JSON parse error, falling back to next provider.")
                break
            except Exception as e:
                if attempt == MAX_RETRIES:
                    logger.error(f"Groq failed after {attempt} retries: {e}")
                    break
                sleep_time = 5 * (2 ** (attempt - 1))
                logger.warning(f"Groq rate limit/error, waiting {sleep_time}s (attempt {attempt}/{MAX_RETRIES}): {e}")
                time.sleep(sleep_time)

    # 2. Secondary: Gemini Primary
    gemini_primary = get_gemini_client(GEMINI_API_KEY)
    if gemini_primary:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = gemini_primary.generate_content(
                    user_prompt,
                    generation_config=GenerationConfig(
                        response_mime_type="application/json",
                        temperature=0.0,
                    )
                )
                content = response.text
                if not content:
                    raise ValueError("Empty response from Gemini Primary")
                
                parsed = json.loads(content)
                if "results" not in parsed:
                    raise ValueError("Response missing 'results' array")
                mapped_results = {}
                for res in parsed["results"]:
                    if "id" in res and "relevant" in res:
                        mapped_results[res["id"]] = {
                            "relevant": bool(res["relevant"]),
                            "reason": res.get("reason", ""),
                        }
                return mapped_results, "gemini-primary:gemini-3.5-flash"
            except json.JSONDecodeError:
                logger.error("Gemini Primary JSON parse error, falling back to next provider.")
                break
            except Exception as e:
                if attempt == MAX_RETRIES:
                    logger.error(f"Gemini Primary failed after {attempt} retries: {e}")
                    break
                sleep_time = 5 * (2 ** (attempt - 1))
                logger.warning(f"Gemini Primary rate limit/error, waiting {sleep_time}s (attempt {attempt}/{MAX_RETRIES}): {e}")
                time.sleep(sleep_time)

    # 3. Tertiary: Gemini Fallback
    gemini_fallback = get_gemini_client(GEMINI_API_KEY_FALLBACK)
    if gemini_fallback:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = gemini_fallback.generate_content(
                    user_prompt,
                    generation_config=GenerationConfig(
                        response_mime_type="application/json",
                        temperature=0.0,
                    )
                )
                content = response.text
                if not content:
                    raise ValueError("Empty response from Gemini Fallback")
                
                parsed = json.loads(content)
                if "results" not in parsed:
                    raise ValueError("Response missing 'results' array")
                mapped_results = {}
                for res in parsed["results"]:
                    if "id" in res and "relevant" in res:
                        mapped_results[res["id"]] = {
                            "relevant": bool(res["relevant"]),
                            "reason": res.get("reason", ""),
                        }
                return mapped_results, "gemini-fallback:gemini-3.5-flash"
            except json.JSONDecodeError:
                logger.error("Gemini Fallback JSON parse error.")
                break
            except Exception as e:
                if attempt == MAX_RETRIES:
                    logger.error(f"Gemini Fallback failed after {attempt} retries: {e}")
                    break
                sleep_time = 5 * (2 ** (attempt - 1))
                logger.warning(f"Gemini Fallback rate limit/error, waiting {sleep_time}s (attempt {attempt}/{MAX_RETRIES}): {e}")
                time.sleep(sleep_time)
            
    logger.error("All filtering providers failed for this batch.")
    return {}, ""


def run_groq_filter() -> dict:
    """
    Main entry point for the filter stage.
    Fetches unfiltered IDs, fetches their text, batches them, calls Groq,
    and inserts the results.
    
    Returns:
        dict: {'processed': int, 'relevant': int, 'discarded': int, 'error': int}
    """
    counts = {"processed": 0, "relevant": 0, "discarded": 0, "error": 0}

    logger.info("Starting Groq filter stage.")

    unfiltered_ids = get_unfiltered_raw_ids()
    logger.info("Found %d unfiltered records.", len(unfiltered_ids))

    if not unfiltered_ids:
        return counts

    # Apply cap
    ids_to_process = unfiltered_ids[:MAX_FILTER_PER_RUN]
    if len(unfiltered_ids) > MAX_FILTER_PER_RUN:
        logger.info("Capping at %d records for this run.", MAX_FILTER_PER_RUN)

    # Process in batches
    batch = []
    
    for i, raw_id in enumerate(ids_to_process):
        text_data = get_raw_text(raw_id)
        if not text_data:
            logger.warning("Could not fetch text for raw_id: %s", raw_id)
            counts["error"] += 1
            continue

        batch.append({"id": raw_id, "text": text_data["raw_text"], "source": text_data["source"]})

        # When batch is full or it's the last item
        if len(batch) >= GROQ_BATCH_SIZE or i == len(ids_to_process) - 1:
            logger.info("Filtering batch of %d records...", len(batch))
            
            # Hard delay to stay under Groq's per-minute limits (request rate
            # AND token throughput). Raised from 2.5s to 3.5s to match the
            # classify stage's existing margin, after 2.5s proved insufficient
            # once cumulative token usage climbed over a long run.
            time.sleep(3.5)

            try:
                results, success_model = filter_batch(batch)
            except Exception as e:
                logger.error("Filter batch failed completely: %s. Skipping to next batch.", e)
                counts["error"] += len(batch)
                batch = []
                continue

            if not results:
                counts["error"] += len(batch)
                batch = []
                continue

            # Process results
            for item in batch:
                item_id = item["id"]
                if item_id in results:
                    res = results[item_id]
                    is_relevant = res["relevant"]
                    reason = res["reason"]
                    
                    status = "relevant" if is_relevant else "discarded"
                    
                    try:
                        insert_filter_result(
                            raw_id=item_id,
                            filter_status=status,
                            filter_reason=reason,
                            model_filter=success_model
                        )
                        counts["processed"] += 1
                        if is_relevant:
                            counts["relevant"] += 1
                        else:
                            counts["discarded"] += 1
                    except Exception as e:
                        logger.error("Failed to insert filter result for %s: %s", item_id, e)
                        counts["error"] += 1
                else:
                    logger.warning("Groq response missing result for ID: %s", item_id)
                    counts["error"] += 1

            batch = []

    logger.info("Groq filter stage finished. Counts: %s", counts)
    return counts
