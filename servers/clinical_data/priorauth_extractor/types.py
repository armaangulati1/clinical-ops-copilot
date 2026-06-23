"""Shared types for the prior-auth agentic extractor pipeline.

This pipeline targets ``schemas.extraction.Extraction`` for specialty-medication
prior-auth. It is separate from ChartExtractor's oncology API.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from schemas.extraction import Extraction
from schemas.policies import PayerPolicy


class ConditionPath(StrEnum):
    """Prior-auth condition routing paths."""

    RA = "rheumatoid_arthritis"
    T2D = "type_2_diabetes"
    MIGRAINE = "chronic_migraine"


COMMON_FIELDS = ("patient_name", "age")

CONDITION_FIELDS: dict[ConditionPath, tuple[str, ...]] = {
    ConditionPath.RA: (
        "diagnosis_confirmed",
        "disease_duration_months",
        "failed_dmards",
        "das28_score",
        "methotrexate_trial_weeks",
    ),
    ConditionPath.T2D: (
        "a1c_percent",
        "metformin_trial_months",
        "bmi",
        "diabetes_duration_years",
    ),
    ConditionPath.MIGRAINE: (
        "migraine_days_per_month",
        "chronic_migraine_diagnosis",
        "failed_triptans",
        "preventive_trial_failed",
    ),
}


class RoutePlan(BaseModel):
    """Router output: which condition path and fields to extract."""

    condition_path: ConditionPath
    required_fields: list[str] = Field(min_length=1)
    extract_common: bool = True
    extract_condition_fields: bool = True


@dataclass
class FieldCandidate:
    value: Any
    confidence: float = 0.85
    evidence: str = ""
    source: str = ""


@dataclass
class PipelineState:
    note: str
    policy: PayerPolicy
    route: RoutePlan | None = None
    candidates: dict[str, FieldCandidate] = field(default_factory=dict)
    flags: dict[str, list[str]] = field(default_factory=dict)
    extraction: Extraction | None = None
    field_confidence: dict[str, float] = field(default_factory=dict)
    evidence: dict[str, str] = field(default_factory=dict)
    needs_review: list[str] = field(default_factory=list)
    review_threshold: float = 0.75

    def target_fields(self) -> list[str]:
        if self.route is None:
            return []
        fields = list(COMMON_FIELDS) if self.route.extract_common else []
        if self.route.extract_condition_fields:
            fields.extend(CONDITION_FIELDS[self.route.condition_path])
        return fields
