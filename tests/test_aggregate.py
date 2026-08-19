import pytest
import pandas as pd
from aggregate.themes import extract_themes, normalize_unmet_need
from aggregate.weekly_rollup import calculate_severity, calculate_trend

def test_normalize_unmet_need():
    assert normalize_unmet_need("  I want BIGGER POCKETS!!! ") == "i want bigger pockets"
    assert normalize_unmet_need("Nothing") == "nothing"
    assert normalize_unmet_need("") == ""
    assert normalize_unmet_need(None) == ""

def test_extract_themes():
    taxonomy = {
        "fields": {
            "purchase_outcome": {"type": "enum", "values": ["purchased", "not_purchased", "unclear"], "default": "unclear"},
            "purchase_blocker": {"type": "enum", "values": ["price", "none_stated"], "default": "none_stated"},
            "deal_seeking": {"type": "boolean", "default": False},
            "unmet_need": {"type": "open_text", "default": ""},
        }
    }
    
    # Missing fields get ignored
    assert extract_themes({"purchase_outcome": "purchased"}, taxonomy) == []
    
    # Valid non-default themes
    themes = extract_themes({
        "purchase_blocker": "price",
        "deal_seeking": True,
        "unmet_need": "more colors"
    }, taxonomy)
    
    assert set(themes) == {"purchase_blocker:price", "deal_seeking:true", "unmet_need:more colors"}

def test_calculate_severity():
    # 50% rate = severity 3
    df_severe = pd.DataFrame([
        {"purchase_outcome": "not_purchased", "sentiment": "negative"},
        {"purchase_outcome": "purchased", "sentiment": "positive"}
    ])
    assert calculate_severity(df_severe) == 3.0
    
    # 25% rate = severity 2
    df_med = pd.DataFrame([
        {"purchase_outcome": "not_purchased", "sentiment": "negative"},
        {"purchase_outcome": "purchased", "sentiment": "positive"},
        {"purchase_outcome": "purchased", "sentiment": "positive"},
        {"purchase_outcome": "purchased", "sentiment": "positive"}
    ])
    assert calculate_severity(df_med) == 2.0
    
    # 0% rate = severity 1
    df_low = pd.DataFrame([
        {"purchase_outcome": "purchased", "sentiment": "positive"},
        {"purchase_outcome": "purchased", "sentiment": "positive"}
    ])
    assert calculate_severity(df_low) == 1.0

def test_calculate_trend():
    # From 0 to something = rising, 1.2
    assert calculate_trend(10, 0) == ("rising", 1.2, None)
    
    # Rising > 10%
    assert calculate_trend(12, 10) == ("rising", 1.2, 0.2)
    
    # Flat (within +/- 10%)
    assert calculate_trend(10, 10) == ("flat", 1.0, 0.0)
    assert calculate_trend(10, 11) == ("flat", 1.0, -1/11) # approx -9%
    
    # Falling < 10%
    assert calculate_trend(5, 10) == ("falling", 0.8, -0.5)
