"""Schema and range validation for prior-auth extractions."""

from __future__ import annotations

from typing import Any

from schemas.extraction import Extraction
from servers.clinical_data.priorauth_extractor.types import PipelineState

# Validator ranges (may be wider than Pydantic model bounds for flagging).
FIELD_RANGES: dict[str, tuple[float, float]] = {
    "age": (0, 120),
    "disease_duration_months": (0, 600),
    "failed_dmards": (0, 20),
    "das28_score": (0.0, 10.0),
    "methotrexate_trial_weeks": (0, 260),
    "a1c_percent": (0.0, 20.0),
    "metformin_trial_months": (0, 120),
    "bmi": (0.0, 80.0),
    "diabetes_duration_years": (0, 100),
    "migraine_days_per_month": (0, 31),
    "failed_triptans": (0, 20),
    "preventive_trial_failed": (0, 20),
}

NON_NEGATIVE_INT_FIELDS = {
    "disease_duration_months",
    "failed_dmards",
    "methotrexate_trial_weeks",
    "metformin_trial_months",
    "diabetes_duration_years",
    "migraine_days_per_month",
    "failed_triptans",
    "preventive_trial_failed",
}


def _flag(state: PipelineState, field_name: str, reason: str) -> None:
    state.flags.setdefault(field_name, []).append(reason)


def _value_in_range(field_name: str, value: Any) -> bool:
    if field_name in NON_NEGATIVE_INT_FIELDS and isinstance(value, int) and value < 0:
        return False
    if field_name not in FIELD_RANGES:
        return True
    low, high = FIELD_RANGES[field_name]
    if not isinstance(value, (int, float)):
        return False
    return low <= float(value) <= high


def validate_values(state: PipelineState) -> Extraction:
    """Validate and sanitize candidate values; out-of-range fields are cleared."""
    payload: dict[str, Any] = {}
    for field_name in state.target_fields():
        candidate = state.candidates.get(field_name)
        if candidate is None:
            payload[field_name] = None
            continue
        value = candidate.value
        if value is None or value == "":
            payload[field_name] = None
            continue
        if not _value_in_range(field_name, value):
            _flag(state, field_name, "out_of_range")
            payload[field_name] = None
            continue
        payload[field_name] = value

    extraction = Extraction.model_validate(payload)
    state.extraction = extraction
    return extraction


def apply_validator(state: PipelineState) -> PipelineState:
    validate_values(state)
    return state
