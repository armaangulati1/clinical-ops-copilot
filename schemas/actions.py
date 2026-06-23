"""Downstream actions triggered by a prior-auth decision."""

from enum import StrEnum

from pydantic import BaseModel, Field


class ActionType(StrEnum):
    """Effect of executing a prior-auth decision."""

    DRAFT_SUBMISSION = "draft_submission"
    REQUEST_INFO_EMAIL = "request_info_email"
    FLAG_FOR_REVIEW = "flag_for_review"


class Action(BaseModel):
    """Concrete downstream action for a decided case."""

    effect: ActionType
    case_id: str = Field(..., pattern=r"^case-\d{3}$")
    details: str = Field(..., min_length=5)
