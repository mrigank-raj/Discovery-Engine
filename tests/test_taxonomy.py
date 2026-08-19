"""
Validation tests for taxonomy.json.

Ensures the taxonomy file is well-formed, complete, and consistent
with the classification schema defined in Context.md.
No fake data — these tests validate the schema definition itself.
"""

import json
from pathlib import Path

import pytest

TAXONOMY_PATH = Path(__file__).resolve().parent.parent / "taxonomy.json"


@pytest.fixture
def taxonomy():
    with open(TAXONOMY_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


class TestTaxonomyStructure:
    def test_file_exists(self):
        assert TAXONOMY_PATH.exists(), "taxonomy.json must exist at project root"

    def test_valid_json(self):
        with open(TAXONOMY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_has_fields(self, taxonomy):
        assert "fields" in taxonomy
        assert isinstance(taxonomy["fields"], dict)
        assert len(taxonomy["fields"]) > 0

    def test_has_version(self, taxonomy):
        assert "version" in taxonomy


class TestTaxonomyFields:
    """Verify every expected field exists with correct type and values."""

    EXPECTED_ENUM_FIELDS = {
        "purchase_outcome": ["purchased", "not_purchased", "unclear"],
        "wishlist_motive": [
            "liked_product", "waiting_for_sale", "saving_for_later",
            "comparing_options", "no_immediate_budget", "not_stated",
        ],
        "purchase_blocker": [
            "price_too_high", "size_fit_doubt", "quality_doubt",
            "found_alternative", "no_longer_needed", "bad_reviews",
            "delivery_return_concern", "forgot", "not_stated",
        ],
        "post_selection_uncertainty": [
            "fit_size", "quality_material", "color_accuracy",
            "authenticity", "styling_fit_for_occasion", "none_stated",
        ],
        "purchase_postponement_reason": [
            "waiting_for_discount", "waiting_for_payday_budget",
            "waiting_for_occasion", "seeking_more_reviews",
            "comparing_more_options", "not_stated",
        ],
        "comparison_behavior": [
            "price_comparison", "review_rating_comparison",
            "brand_comparison", "feature_comparison",
            "cross_platform_comparison", "not_mentioned",
        ],
        "external_info_sought": [
            "youtube_review", "influencer_opinion",
            "friends_family_opinion", "other_site_price_check",
            "other_site_reviews", "not_mentioned",
        ],
        "wishlist_intent_type": ["genuine_intent", "bookmarking_only", "unclear"],
        "segment_signal": [
            "gender_context", "budget_conscious", "premium_oriented",
            "first_time_shopper", "frequent_shopper", "not_evident",
        ],
        "sentiment": ["positive", "negative", "neutral"],
    }

    EXPECTED_BOOLEAN_FIELDS = [
        "fit_size_signal",
        "styling_signal",
        "price_signal",
        "reviews_signal",
        "occasion_signal",
        "social_validation_signal",
    ]

    EXPECTED_OPEN_TEXT_FIELDS = ["unmet_need"]

    def test_all_enum_fields_present(self, taxonomy):
        fields = taxonomy["fields"]
        for field_name in self.EXPECTED_ENUM_FIELDS:
            assert field_name in fields, f"Missing enum field: {field_name}"

    def test_enum_values_match(self, taxonomy):
        fields = taxonomy["fields"]
        for field_name, expected_values in self.EXPECTED_ENUM_FIELDS.items():
            field = fields[field_name]
            assert field["type"] == "enum", f"{field_name} should be type 'enum'"
            assert sorted(field["values"]) == sorted(expected_values), (
                f"{field_name} values mismatch. "
                f"Expected: {sorted(expected_values)}, "
                f"Got: {sorted(field['values'])}"
            )

    def test_all_boolean_fields_present(self, taxonomy):
        fields = taxonomy["fields"]
        for field_name in self.EXPECTED_BOOLEAN_FIELDS:
            assert field_name in fields, f"Missing boolean field: {field_name}"
            assert fields[field_name]["type"] == "boolean"

    def test_open_text_fields_present(self, taxonomy):
        fields = taxonomy["fields"]
        for field_name in self.EXPECTED_OPEN_TEXT_FIELDS:
            assert field_name in fields, f"Missing open_text field: {field_name}"
            assert fields[field_name]["type"] == "open_text"

    def test_every_field_has_default(self, taxonomy):
        for name, field in taxonomy["fields"].items():
            assert "default" in field, f"Field '{name}' missing 'default'"

    def test_every_field_has_description(self, taxonomy):
        for name, field in taxonomy["fields"].items():
            assert "description" in field, f"Field '{name}' missing 'description'"
            assert len(field["description"]) > 0

    def test_enum_defaults_are_valid(self, taxonomy):
        """Default value must be one of the allowed values."""
        for name, field in taxonomy["fields"].items():
            if field["type"] == "enum":
                assert field["default"] in field["values"], (
                    f"Field '{name}' default '{field['default']}' "
                    f"not in values {field['values']}"
                )

    def test_total_field_count(self, taxonomy):
        """Ensure no extra fields were accidentally added."""
        expected_count = (
            len(self.EXPECTED_ENUM_FIELDS)
            + len(self.EXPECTED_BOOLEAN_FIELDS)
            + len(self.EXPECTED_OPEN_TEXT_FIELDS)
        )
        actual_count = len(taxonomy["fields"])
        assert actual_count == expected_count, (
            f"Expected {expected_count} fields, got {actual_count}. "
            "Do not add fields beyond the taxonomy."
        )


class TestTaxonomyRules:
    """Verify taxonomy-level rules and metadata."""

    def test_purchase_outcome_not_skipped(self, taxonomy):
        """purchase_outcome must never be skipped in theme explosion."""
        field = taxonomy["fields"]["purchase_outcome"]
        assert field.get("skip_in_theme_explosion") is False

    def test_sentiment_not_ranked(self, taxonomy):
        """sentiment is not a ranked opportunity theme."""
        field = taxonomy["fields"]["sentiment"]
        assert field.get("ranked_as_opportunity") is False

    def test_purchase_outcome_not_ranked(self, taxonomy):
        """purchase_outcome is not ranked as an opportunity theme itself."""
        field = taxonomy["fields"]["purchase_outcome"]
        assert field.get("ranked_as_opportunity") is False

    def test_has_skip_values_global(self, taxonomy):
        """Global skip values list should exist."""
        assert "skip_values_global" in taxonomy
        skip = taxonomy["skip_values_global"]
        assert "not_stated" in skip
        assert "not_mentioned" in skip
        assert "none_stated" in skip
