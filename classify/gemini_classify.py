"""
Gemini classification stage.

Classifies relevant text using Gemini, adhering strictly to the schema
defined in taxonomy.json.
"""

import json
import logging
import time
from typing import Any

import google.generativeai as genai
from google.generativeai.types import GenerationConfig
from google.api_core.exceptions import ResourceExhausted, InternalServerError

from config.settings import (
    GEMINI_API_KEY,
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

GEMINI_MODEL = "gemini-3.5-flash"  # Fast and supports JSON mode

def get_gemini_client() -> Any:
    """Initialize Gemini."""
    if not GEMINI_API_KEY:
        raise EnvironmentError("GEMINI_API_KEY is not set.")
    genai.configure(api_key=GEMINI_API_KEY)
    # Return the model instance
    return genai.GenerativeModel(
        model_name=GEMINI_MODEL,
        system_instruction=(
            "Tag this user-generated text about shopping on Myntra. "
            "Use ONLY the specific enums provided in the JSON schema. "
            "If the text does not state something explicitly, use the 'not_stated' or equivalent default value. "
            "Never infer segment signals unless explicitly evident in the text."
        )
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

def classify_text(model: Any, text: str, source: str, schema: dict) -> dict:
    """
    Call Gemini to classify a single text.
    Returns the parsed JSON dictionary.
    """
    user_prompt = f"Source: {source}\nBrand: Myntra\nText: {text}"
    
    for attempt in range(1, LLM_MAX_RETRIES + 1):
        try:
            response = model.generate_content(
                user_prompt,
                generation_config=GenerationConfig(
                    response_mime_type="application/json",
                    response_schema=schema,
                    temperature=0.1,
                )
            )
            content = response.text
            if not content:
                raise ValueError("Empty response from Gemini")

            return json.loads(content)

        except (ResourceExhausted, InternalServerError) as e:
            if attempt == LLM_MAX_RETRIES:
                logger.error("Gemini API failed after %d retries: %s", attempt, e)
                raise
            sleep_time = LLM_BACKOFF_BASE ** attempt
            logger.warning("Gemini API error (attempt %d/%d). Sleeping %.1fs: %s", attempt, LLM_MAX_RETRIES, sleep_time, e)
            time.sleep(sleep_time)
        except json.JSONDecodeError as e:
            logger.error("Failed to parse Gemini JSON response: %s", e)
            # Fail this item, no retry on bad JSON
            raise
        except Exception as e:
            logger.error("Unexpected error calling Gemini: %s", e)
            raise
            
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
    try:
        model = get_gemini_client()
        taxonomy = load_taxonomy()
        gemini_schema = build_json_schema(taxonomy)
    except EnvironmentError as e:
        logger.error("Skipping classify stage: %s", e)
        counts["error"] = 1
        return counts

    unclassified_ids = get_unclassified_relevant_ids()
    logger.info("Found %d unclassified relevant records.", len(unclassified_ids))

    if not unclassified_ids:
        return counts

    ids_to_process = unclassified_ids[:MAX_CLASSIFY_PER_RUN]
    if len(unclassified_ids) > MAX_CLASSIFY_PER_RUN:
        logger.info("Capping at %d records for this run.", MAX_CLASSIFY_PER_RUN)

    for raw_id in ids_to_process:
        text_data = get_raw_text(raw_id)
        if not text_data:
            logger.warning("Could not fetch text for raw_id: %s", raw_id)
            counts["error"] += 1
            continue

        raw_text = text_data["raw_text"]
        source = text_data["source"]

        try:
            response_data = classify_text(model, raw_text, source, gemini_schema)
        except json.JSONDecodeError:
            counts["invalid_json"] += 1
            counts["error"] += 1
            continue
        except Exception:
            counts["error"] += 1
            continue

        counts["processed"] += 1

        # Validate and coerce
        tags, warnings = validate_and_coerce(response_data, taxonomy)
        
        # Prepare DB update
        tags["model_classify"] = GEMINI_MODEL
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
