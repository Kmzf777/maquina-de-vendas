from decimal import Decimal

import pytest

from app.lead_score.model import calculate_score


def test_score_sums_known_objective_criteria():
    """Changing any point rule must change the returned normal score."""
    result = calculate_score({
        "segment": "cafeteria",
        "monthly_volume_kg": 30,
        "supplier_reason": "replace",
        "purchase_timing": "within_15_days",
        "purchase_intent": "clear",
    })

    assert result == {
        "normal_score": 8,
        "final_score": 10,
        "priority": "maximum",
        "is_provisional": False,
    }


def test_replacement_and_clear_intent_override_normal_scale():
    """The exceptional 10 must not depend on unrelated criteria."""
    result = calculate_score({
        "segment": "other",
        "monthly_volume_kg": 31,
        "supplier_reason": "replace",
        "purchase_timing": "no_timeline",
        "purchase_intent": "clear",
    })

    assert result["normal_score"] == 4
    assert result["final_score"] == 10
    assert result["priority"] == "maximum"


def test_missing_criteria_are_zero_and_provisional():
    result = calculate_score({})

    assert result == {
        "normal_score": 0,
        "final_score": 0,
        "priority": "low",
        "is_provisional": True,
    }


@pytest.mark.parametrize(
    ("volume", "timing", "expected_score"),
    [
        (30, "within_15_days", 2),
        (30.01, "within_15_days", 1),
        (None, "within_15_days", 1),
        (30, "days_16_30", 1),
    ],
)
def test_volume_and_timing_boundaries(volume, timing, expected_score):
    result = calculate_score({
        "segment": "other",
        "monthly_volume_kg": volume,
        "supplier_reason": "other",
        "purchase_timing": timing,
        "purchase_intent": "unclear",
    })

    assert result["normal_score"] == expected_score


def test_invalid_categorical_value_is_rejected():
    with pytest.raises(ValueError, match="segment"):
        calculate_score({"segment": "coffee_shop"})


def test_decimal_volume_from_database_is_scored_at_the_boundary():
    result = calculate_score({
        "segment": "other",
        "monthly_volume_kg": Decimal("30.0"),
        "supplier_reason": "other",
        "purchase_timing": "no_timeline",
        "purchase_intent": "unclear",
    })

    assert result["normal_score"] == 1
