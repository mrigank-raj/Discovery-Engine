"""
Groq filtering stage.

Filters incoming raw records to separate genuine Myntra shopping behavior
from spam, off-topic content, or mentions of other retailers only.
Relevant records proceed to Gemini classification.
"""

import json
import logging
import time
from typing import Any

from groq import Groq, InternalServerError, RateLimitError

from config.settings import (
    GROQ_API_KEY,
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


def get_groq_client() -> Groq:
    """Initialize the Groq client."""
    if not GROQ_API_KEY:
        raise EnvironmentError("GROQ_API_KEY is not set.")
    return Groq(api_key=GROQ_API_KEY)


def filter_batch(client: Groq, batch: list[dict]) -> dict[str, Any]:
    """
    Call Groq to filter a batch of records.
    Returns a dict mapping raw_id -> {'relevant': bool, 'reason': str}
    """
    # Prepare the user prompt with the batch
    user_content = {"texts": batch}
    
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT.strip()},
        {"role": "user", "content": json.dumps(user_content, ensure_ascii=False)},
    ]

    GROQ_MAX_RETRIES = 8

    for attempt in range(1, GROQ_MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.0, # Deterministic
            )
            content = response.choices[0].message.content
            if not content:
                raise ValueError("Empty response from Groq")

            parsed = json.loads(content)
            if "results" not in parsed:
                raise ValueError("Response missing 'results' array")

            # Map results by ID
            mapped_results = {}
            for res in parsed["results"]:
                if "id" in res and "relevant" in res:
                    mapped_results[res["id"]] = {
                        "relevant": bool(res["relevant"]),
                        "reason": res.get("reason", ""),
                    }
            return mapped_results

        except (RateLimitError, InternalServerError) as e:
            if attempt == GROQ_MAX_RETRIES:
                logger.error("Groq API failed after %d retries: %s", attempt, e)
                raise
            sleep_time = 10 * (2 ** (attempt - 1))
            logger.warning("Groq API error (attempt %d/%d). Sleeping %ds: %s", attempt, GROQ_MAX_RETRIES, sleep_time, e)
            time.sleep(sleep_time)
        except json.JSONDecodeError as e:
            logger.error("Failed to parse Groq JSON response: %s", e)
            # We don't retry on bad JSON to save time/quota — just fail this batch
            # Next pipeline run can pick these up again
            return {}
        except Exception as e:
            logger.error("Unexpected error calling Groq: %s", e)
            return {}
            
    return {}


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
    try:
        client = get_groq_client()
    except EnvironmentError as e:
        logger.error("Skipping filter stage: %s", e)
        counts["error"] = 1
        return counts

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
            
            # Hard delay to stay under the 30 RPM limit
            time.sleep(2.5)

            try:
                results = filter_batch(client, batch)
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
                            model_filter=GROQ_MODEL
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
