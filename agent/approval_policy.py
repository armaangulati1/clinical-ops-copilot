"""Pure approval policy for prior-auth decisions."""

from __future__ import annotations

from schemas.decisions import Decision, DecisionAction, ProposedAction

DEFAULT_APPROVAL_CONFIDENCE_THRESHOLD = 0.75

STATE_CHANGING_CLINIC_OPS_TOOLS = frozenset(
    {"send_email", "schedule_followup", "create_task"},
)


def is_state_changing_action(action: ProposedAction | None) -> bool:
    """Return True when a proposed clinic-ops tool mutates external state."""
    if action is None:
        return False
    return action.tool in STATE_CHANGING_CLINIC_OPS_TOOLS


def requires_approval(
    decision: Decision,
    *,
    confidence_threshold: float = DEFAULT_APPROVAL_CONFIDENCE_THRESHOLD,
) -> bool:
    """Return True when human approval is required before any external action."""
    if is_state_changing_action(decision.proposed_action):
        return True
    if decision.action in {DecisionAction.SUBMIT, DecisionAction.DENY_RISK}:
        return True
    if decision.confidence < confidence_threshold:
        return True
    return bool(decision.needs_review)
