"""Error taxonomy for misclassified prior-auth decisions."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from schemas.cases import CaseLabel
from schemas.decisions import DecisionAction


class ErrorCategory(StrEnum):
    """Buckets for decision mistakes."""

    MISSED_MISSING_FIELD = "missed-missing-field"
    WRONG_CRITERIA_CALL = "wrong-criteria-call"
    OVER_REQUEST_INFO = "over-request-info"
    UNDER_REQUEST_INFO = "under-request-info"
    OTHER = "other"


class ErrorTaxonomyEntry(BaseModel):
    case_id: str
    predicted: str
    truth: str
    category: ErrorCategory
    detail: str = Field(..., min_length=1)


def classify_decision_error(
    *,
    case_id: str,
    predicted: DecisionAction,
    truth: DecisionAction,
    label: CaseLabel,
) -> ErrorTaxonomyEntry | None:
    """Classify a single mis-prediction; return None when prediction is correct."""
    if predicted == truth:
        return None

    missing_fields = set(label.fields_missing)
    predicted_missing = predicted == DecisionAction.REQUEST_MORE_INFO
    truth_missing = truth == DecisionAction.REQUEST_MORE_INFO
    truth_deny = truth == DecisionAction.DENY_RISK
    predicted_submit = predicted == DecisionAction.SUBMIT

    if truth_missing and predicted_submit and missing_fields:
        category = ErrorCategory.MISSED_MISSING_FIELD
        detail = f"Submitted despite missing fields: {sorted(missing_fields)}"
    elif truth_deny and predicted_submit:
        category = ErrorCategory.WRONG_CRITERIA_CALL
        detail = "Submitted when criteria are not met (deny-risk expected)."
    elif truth_missing and predicted == DecisionAction.DENY_RISK:
        category = ErrorCategory.UNDER_REQUEST_INFO
        detail = "Denied risk instead of requesting missing documentation."
    elif not truth_missing and predicted_missing:
        category = ErrorCategory.OVER_REQUEST_INFO
        detail = "Requested more info when documentation was sufficient."
    elif predicted == DecisionAction.DENY_RISK and truth == DecisionAction.SUBMIT:
        category = ErrorCategory.WRONG_CRITERIA_CALL
        detail = "Denied risk when submit was appropriate."
    else:
        category = ErrorCategory.OTHER
        detail = f"Predicted {predicted.value}; expected {truth.value}."

    return ErrorTaxonomyEntry(
        case_id=case_id,
        predicted=predicted.value,
        truth=truth.value,
        category=category,
        detail=detail,
    )
