"""
Theme Explosion and Normalization for Aggregation Engine.

Extracts a list of `theme_keys` from a classified record based on the taxonomy.
"""

import re
import string

# Taxonomy defaults that should NOT be expanded into themes
SKIP_VALUES = {
    "not_stated",
    "none_stated",
    "not_mentioned",
    "unclear",
    "not_evident",
    None,
    "",
}

# Fields that are excluded from being treated as primary themes 
# (they are used as supporting metrics like severity and conversion)
NON_THEME_FIELDS = {
    "purchase_outcome",
    "sentiment"
}

def normalize_unmet_need(text: str) -> str:
    """
    Normalizes 'unmet_need' open text:
    Lowercase, strip whitespace, strip trailing punctuation.
    """
    if not text:
        return ""
    # Lowercase
    t = text.lower()
    # Strip leading/trailing whitespace
    t = t.strip()
    # Collapse internal whitespace
    t = re.sub(r'\s+', ' ', t)
    # Strip trailing punctuation
    t = t.rstrip(string.punctuation)
    return t

def extract_themes(record: dict, taxonomy: dict) -> list[str]:
    """
    Given a classified record and the taxonomy definition, returns a list of theme keys.
    Format: `{field}:{value}`
    """
    themes = []
    
    for field, f_def in taxonomy["fields"].items():
        if field in NON_THEME_FIELDS:
            continue
            
        val = record.get(field)
        
        if f_def["type"] == "enum":
            if val not in SKIP_VALUES:
                themes.append(f"{field}:{val}")
                
        elif f_def["type"] == "boolean":
            if val is True:
                themes.append(f"{field}:true")
                
        elif f_def["type"] == "open_text" and field == "unmet_need":
            if val and isinstance(val, str):
                norm = normalize_unmet_need(val)
                if norm and norm not in SKIP_VALUES:
                    themes.append(f"{field}:{norm}")
                    
    return list(set(themes))  # Deduplicate just in case
