"""Case input and held-out label models."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from schemas.decisions import DecisionAction
from schemas.policies import PayerPolicy


class Difficulty(StrEnum):
    """Deliberate difficulty tag for eval stratification."""

    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class Case(BaseModel):
    """Agent-visible prior-auth case input (no ground-truth labels)."""

    case_id: str = Field(..., pattern=r"^case-\d{3}$")
    clinical_note: str = Field(..., min_length=50)
    payer_policy: PayerPolicy
    drug: str = Field(..., min_length=1)
    condition: str = Field(..., min_length=1)
    patient_id: str | None = Field(
        default=None,
        description="Optional FHIR Patient id for structured fact fusion.",
    )


class CaseLabel(BaseModel):
    """Held-out ground truth for a single case."""

    correct_action: DecisionAction
    required_fields_present: dict[str, bool] = Field(
        ...,
        description="Whether each required policy field is present and unambiguous.",
    )
    fields_missing: list[str] = Field(
        default_factory=list,
        description="Required policy fields absent or ambiguous in the note.",
    )
    label_rationale: str = Field(..., min_length=10)
    difficulty: Difficulty


class CaseLabelsFile(BaseModel):
    """Top-level labels file mapping case_id to ground truth."""

    labels: dict[str, CaseLabel]

    def get(self, case_id: str) -> CaseLabel:
        if case_id not in self.labels:
            msg = f"No label found for case_id={case_id!r}"
            raise KeyError(msg)
        return self.labels[case_id]


# Candidate used during human review before approval.
class ReviewCandidate(BaseModel):
    """Proposed case + label awaiting human confirmation."""

    case: Case
    proposed_action: DecisionAction
    proposed_rationale: str = Field(..., min_length=10)
    difficulty: Difficulty
    required_fields_present: dict[str, bool]
    fields_missing: list[str] = Field(default_factory=list)
    review_status: Literal["pending", "approved", "rejected"] = "pending"
