"""Pure, deterministic rules for ValerIA wholesale lead scoring."""

from decimal import Decimal
from math import isfinite
from numbers import Real


CRITERIA_FIELDS = (
    "segment",
    "monthly_volume_kg",
    "supplier_reason",
    "purchase_timing",
    "purchase_intent",
)

_SEGMENT_POINTS = {
    "cafeteria": 2,
    "emporio": 1,
    "specialty_store": 1,
    "wine_shop": 1,
    "cheese_shop": 1,
    "natural_products_store": 1,
    "bulk_store": 1,
    "artisan_store": 1,
    "colonial_store": 1,
    "rural_store": 1,
    "supermarket": 0,
    "hotel": 0,
    "restaurant": 0,
    "bakery": 0,
    "other": 0,
}
_SUPPLIER_REASONS = frozenset({
    "replace", "second_supplier", "expand_mix", "start_specialty_coffee", "research", "other",
})
_PURCHASE_TIMINGS = frozenset({
    "within_15_days", "days_16_30", "months_1_3", "more_than_3_months", "no_timeline",
})
_PURCHASE_INTENTS = frozenset({"clear", "unclear"})


def _value(criteria: dict, field: str):
    return criteria.get(field)


def _validate_choice(field: str, value, allowed: frozenset | dict) -> None:
    if value is not None and value not in allowed:
        raise ValueError(f"Invalid {field}: {value!r}")


def _validate(criteria: dict) -> None:
    unknown = set(criteria) - set(CRITERIA_FIELDS)
    if unknown:
        raise ValueError(f"Unknown score criteria: {', '.join(sorted(unknown))}")
    _validate_choice("segment", _value(criteria, "segment"), _SEGMENT_POINTS)
    _validate_choice("supplier_reason", _value(criteria, "supplier_reason"), _SUPPLIER_REASONS)
    _validate_choice("purchase_timing", _value(criteria, "purchase_timing"), _PURCHASE_TIMINGS)
    _validate_choice("purchase_intent", _value(criteria, "purchase_intent"), _PURCHASE_INTENTS)
    volume = _value(criteria, "monthly_volume_kg")
    if volume is not None and (
        isinstance(volume, bool)
        or not isinstance(volume, (Real, Decimal))
        or (isinstance(volume, Decimal) and not volume.is_finite())
        or (isinstance(volume, Real) and not isfinite(volume))
    ):
        raise ValueError("monthly_volume_kg must be a non-negative number")
    if volume is not None and volume < 0:
        raise ValueError("monthly_volume_kg must be a non-negative number")


def calculate_score(criteria: dict) -> dict:
    """Calculate a score from normalized objective criteria only.

    Missing values are unknown (and therefore provisional), while known negative
    values earn zero points. The special replacement-plus-clear-intent rule
    yields 10 regardless of the normal score.
    """
    _validate(criteria)

    segment = _value(criteria, "segment")
    volume = _value(criteria, "monthly_volume_kg")
    supplier_reason = _value(criteria, "supplier_reason")
    purchase_timing = _value(criteria, "purchase_timing")
    purchase_intent = _value(criteria, "purchase_intent")

    normal_score = (
        _SEGMENT_POINTS.get(segment, 0)
        + int(volume is not None and volume <= 30)
        + int(supplier_reason == "replace") * 2
        + int(purchase_timing == "within_15_days")
        + int(purchase_intent == "clear") * 2
    )
    final_score = 10 if supplier_reason == "replace" and purchase_intent == "clear" else normal_score
    priority = (
        "maximum" if final_score == 10 else
        "high" if final_score >= 5 else
        "moderate" if final_score >= 3 else
        "low"
    )
    return {
        "normal_score": normal_score,
        "final_score": final_score,
        "priority": priority,
        "is_provisional": any(_value(criteria, field) is None for field in CRITERIA_FIELDS),
    }
