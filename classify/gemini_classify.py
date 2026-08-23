"""
Gemini classification stage.

Classifies relevant text using Gemini, adhering strictly to the schema
defined in taxonomy.json.
"""

import json
import logging
import time
from typing import Any, Tuple

import google.generativeai as genai
from google.generativeai.types import GenerationConfig
from google.api_core.exceptions import ResourceExhausted, InternalServerError
from groq import Groq

from config.settings import (
    GROQ_API_KEY,
    GEMINI_API_KEY,
    GEMINI_API_KEY_FALLBACK,
    LLM_BACKOFF_BASE,
    LLM_MAX_RETRIES,
    MAX_CLASSIFY_PER_RUN,
    load_taxonomy,
)
from db.supabase_client import (
    get_raw_text,
    get_unclassified_relevant_ids,
    update_classification,
)

logger = logging.getLogger(__name__)

SYSTEM_INSTRUCTION = (
    "Tag this user-generated text about shopping on Myntra. "
    "Use ONLY the specific enums provided in the JSON schema. "
    "If the text does not state something explicitly, use the 'not_stated' or equivalent default value. "
    "Never infer segment signals unless explicitly evident in the text.\n"
    "This text may not mention 'wishlist' explicitly. Still classify it if it describes hesitation, "
    "delay, comparison, or a decision not to buy something the person liked or considered — "
    "the behavior matters more than the literal word wishlist. Ignore and do not classify generic "
    "delivery, return, payment, or app-bug complaints that have nothing to do with a delayed or hesitant purchase decision."
)

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
        system_instruction=SYSTEM_INSTRUCTION
    )

def validate_and_coerce(response_data: dict, taxonomy: dict) -> tuple[dict, list[str]]:
    """
    Validates Gemini output against the taxonomy definition.
    Coerces missing or invalid fields to their defaults.
    
    Returns:
        tuple: (coerced_tags_dict, list_of_validation_warnings)
    """
    fields = taxonomy["fields"]
    coerced = {}
    warnings = []

    for field_name, field_def in fields.items():
        val = response_data.get(field_name)
        default_val = field_def["default"]

        if field_def["type"] == "enum":
            if val not in field_def["values"]:
                if val is not None:
                    warnings.append(f"Field '{field_name}' invalid enum '{val}'. Coerced to '{default_val}'.")
                else:
                    warnings.append(f"Field '{field_name}' missing. Coerced to '{default_val}'.")
                coerced[field_name] = default_val
            else:
                coerced[field_name] = val

        elif field_def["type"] == "boolean":
            if not isinstance(val, bool):
                if val is not None:
                    warnings.append(f"Field '{field_name}' expected boolean, got {type(val)}. Coerced to {default_val}.")
                else:
                    warnings.append(f"Field '{field_name}' missing. Coerced to {default_val}.")
                coerced[field_name] = default_val
            else:
                coerced[field_name] = val

        elif field_def["type"] == "open_text":
            if not isinstance(val, str):
                warnings.append(f"Field '{field_name}' expected string. Coerced to empty string.")
                coerced[field_name] = default_val
            else:
                coerced[field_name] = val

    return coerced, warnings

def build_json_schema(taxonomy: dict) -> dict:
    """
    Builds a JSON schema from taxonomy.json for Gemini's structured output.
    Note: Gemini requires OpenAPI 3.0 schema format.
    """
    properties = {}
    for name, f_def in taxonomy["fields"].items():
        if f_def["type"] == "enum":
            properties[name] = {
                "type": "string",
                "enum": f_def["values"],
                "description": f_def.get("description", "")
            }
        elif f_def["type"] == "boolean":
            properties[name] = {
                "type": "boolean",
                "description": f_def.get("description", "")
            }
        elif f_def["type"] == "open_text":
            properties[name] = {
                "type": "string",
                "description": f_def.get("description", "")
            }

    return {
        "type": "object",
        "properties": properties,
        "required": list(taxonomy["fields"].keys())
    }

def classify_text(text: str, source: str, schema: dict) -> Tuple[dict, str]:
    """
    Attempts to classify text using Groq, then Gemini Primary, then Gemini Fallback.
    Returns (response_dict, model_name).
    """
    user_prompt = f"Source: {source}\nBrand: Myntra\nText: {text}"
    MAX_RETRIES = 3

    # 1. Primary: Groq
    groq_client = get_groq_client()
    if groq_client:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                completion = groq_client.chat.completions.create(
                    model="openai/gpt-oss-20b",
                    messages=[
                        {"role": "system", "content": SYSTEM_INSTRUCTION + "\nRespond strictly in valid JSON matching the schema."},
                        {"role": "user", "content": f"Schema: {json.dumps(schema)}\n\n{user_prompt}"}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.1,
                )
                content = completion.choices[0].message.content
                if not content:
                    raise ValueError("Empty response from Groq")
                return json.loads(content), "groq:openai/gpt-oss-20b"
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
                        response_schema=schema,
                        temperature=0.1,
                    )
                )
                content = response.text
                if not content:
                    raise ValueError("Empty response from Gemini Primary")
                return json.loads(content), "gemini-primary:gemini-3.5-flash"
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
                        response_schema=schema,
                        temperature=0.1,
                    )
                )
                content = response.text
                if not content:
                    raise ValueError("Empty response from Gemini Fallback")
                return json.loads(content), "gemini-fallback:gemini-3.5-flash"
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
            
    raise RuntimeError("Failed to classify text after retries.")

def run_gemini_classify() -> dict:
    """
    Main entry point for the classify stage.
    Fetches unclassified relevant records, calls Gemini, validates output,
    and updates the database.
    
    Returns:
        dict: {'processed': int, 'success': int, 'invalid_json': int, 'error': int}
    """
    counts = {"processed": 0, "success": 0, "invalid_json": 0, "error": 0}

    logger.info("Starting Gemini classify stage.")

    taxonomy = load_taxonomy()
    gemini_schema = build_json_schema(taxonomy)

    unclassified_ids = get_unclassified_relevant_ids()
    logger.info("Found %d unclassified relevant records.", len(unclassified_ids))

    if not unclassified_ids:
        return counts

    ids_to_process = unclassified_ids[:MAX_CLASSIFY_PER_RUN]
    if len(unclassified_ids) > MAX_CLASSIFY_PER_RUN:
        logger.info("Capping at %d records for this run.", MAX_CLASSIFY_PER_RUN)

    for raw_id in ids_to_process:
        # Hard delay to stay safely under 30 RPM combined Groq limit (filter + classify)
        time.sleep(3.5)

        text_data = get_raw_text(raw_id)
        if not text_data:
            logger.warning("Could not fetch text for raw_id: %s", raw_id)
            counts["error"] += 1
            continue

        raw_text = text_data["raw_text"]
        source = text_data["source"]

        try:
            response_data, success_model = classify_text(raw_text, source, gemini_schema)
        except json.JSONDecodeError:
            counts["invalid_json"] += 1
            counts["error"] += 1
            continue
        except Exception as e:
            logger.error("Failed completely to classify %s: %s. Skipping to next record.", raw_id, e)
            counts["error"] += 1
            continue

        counts["processed"] += 1

        # Validate and coerce
        tags, warnings = validate_and_coerce(response_data, taxonomy)
        
        # Prepare DB update
        tags["model_classify"] = success_model
        if warnings:
            tags["validation_warnings"] = warnings
            logger.debug("Validation warnings for %s: %s", raw_id, warnings)

        try:
            update_classification(raw_id, tags)
            counts["success"] += 1
        except Exception as e:
            logger.error("Failed to update DB for %s: %s", raw_id, e)
            counts["error"] += 1

    logger.info("Gemini classify stage finished. Counts: %s", counts)
    return counts
