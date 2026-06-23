"""Decision models for prior-auth triage."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class DecisionAction(StrEnum):
    """Triage outcome for a prior-auth case."""

    SUBMIT = "submit"
    REQUEST_MORE_INFO = "request-more-info"
    DENY_RISK = "deny-risk"


class ProposedAction(BaseModel):
    """Tool call proposed for Phase 5 approval (not executed in Phase 4)."""

    server: str = Field(..., min_length=1, description="MCP server name.")
    tool: str = Field(..., min_length=1, description="Tool name on that server.")
    arguments: dict[str, Any] = Field(
        default_factory=dict,
        description="Arguments for the tool if approved.",
    )

    @property
    def qualified_name(self) -> str:
        return f"{self.server}/{self.tool}"


class Decision(BaseModel):
    """Structured agent decision on a prior-auth case."""

    action: DecisionAction
    confidence: float = Field(..., ge=0.0, le=1.0)
    rationale: str = Field(..., min_length=10)
    missing_fields: list[str] = Field(
        default_factory=list,
        description="Required policy fields that are missing or ambiguous.",
    )
    needs_review: list[str] = Field(
        default_factory=list,
        description="Extraction or policy fields flagged for human review.",
    )
    proposed_action: ProposedAction | None = Field(
        default=None,
        description="Downstream clinic-ops tool to run after human approval.",
    )
