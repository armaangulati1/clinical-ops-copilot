"""Approval gate models for Phase 5 human-in-the-loop."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from schemas.decisions import Decision, ProposedAction
from schemas.extraction_result import ExtractionResult
from schemas.policies import PayerPolicy


class ApprovalStatus(StrEnum):
    """Lifecycle state for a pending approval record."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EDITED_AND_APPROVED = "edited_and_approved"


class ApprovalResolution(StrEnum):
    """Human reviewer outcome."""

    APPROVE = "approve"
    REJECT = "reject"
    EDIT_AND_APPROVE = "edit_and_approve"


class PendingApproval(BaseModel):
    """Persisted approval record while workflow is paused."""

    approval_id: str = Field(..., min_length=1)
    case_id: str = Field(..., pattern=r"^case-\d{3}$")
    status: ApprovalStatus = ApprovalStatus.PENDING
    decision: Decision
    extraction: ExtractionResult
    policy: PayerPolicy
    proposed_action: ProposedAction | None = None
    edited_action: ProposedAction | None = None
    created_at: datetime
    resolved_at: datetime | None = None
    reviewer: str | None = None
    execution_result: dict[str, Any] | None = None


class AuditEventType(StrEnum):
    """Ordered audit-trail event kinds."""

    TOOL_CALL = "tool_call"
    DECISION = "decision"
    APPROVAL_PENDING = "approval_pending"
    APPROVAL_RESOLVED = "approval_resolved"
    ACTION_EXECUTED = "action_executed"
    SECURITY_EVENT = "security_event"
    GUARDRAIL_EVENT = "guardrail_event"
    FIELD_PROVENANCE = "field_provenance"
    FHIR_FALLBACK = "fhir_fallback"


class AuditEvent(BaseModel):
    """Single append-only audit event for a case."""

    case_id: str = Field(..., pattern=r"^case-\d{3}$")
    event_type: AuditEventType
    timestamp: datetime
    payload: dict[str, Any] = Field(default_factory=dict)
    sequence: int = Field(..., ge=0)


class WorkflowStatus(StrEnum):
    """Outcome of an agent run with the approval gate."""

    COMPLETED = "completed"
    PENDING_APPROVAL = "pending_approval"


class WorkflowResult(BaseModel):
    """Result of running the gated prior-auth workflow."""

    case_id: str
    status: WorkflowStatus
    decision: Decision
    approval_id: str | None = None
    message: str = ""
