"""Unit tests for requires_approval policy."""

from __future__ import annotations

from agent.approval_policy import (
    DEFAULT_APPROVAL_CONFIDENCE_THRESHOLD,
    is_state_changing_action,
    requires_approval,
)
from schemas.decisions import Decision, DecisionAction, ProposedAction


def _decision(**overrides: object) -> Decision:
    base = {
        "action": DecisionAction.REQUEST_MORE_INFO,
        "confidence": 0.9,
        "rationale": "Sufficient documentation for triage.",
        "missing_fields": [],
        "needs_review": [],
        "proposed_action": None,
    }
    base.update(overrides)
    return Decision.model_validate(base)


def test_state_changing_tools_detected() -> None:
    action = ProposedAction(
        server="clinic-ops",
        tool="send_email",
        arguments={"idempotency_key": "k1"},
    )
    assert is_state_changing_action(action) is True
    assert (
        is_state_changing_action(
            ProposedAction(server="clinic-ops", tool="draft_email", arguments={})
        )
        is False
    )


def test_requires_approval_for_state_changing_proposal() -> None:
    decision = _decision(
        proposed_action={
            "server": "clinic-ops",
            "tool": "create_task",
            "arguments": {"idempotency_key": "k1"},
        }
    )
    assert requires_approval(decision) is True


def test_requires_approval_for_submit_action() -> None:
    decision = _decision(action=DecisionAction.SUBMIT)
    assert requires_approval(decision) is True


def test_requires_approval_for_low_confidence() -> None:
    decision = _decision(confidence=0.5)
    assert requires_approval(decision) is True


def test_requires_approval_for_needs_review() -> None:
    decision = _decision(needs_review=["das28_score"])
    assert requires_approval(decision) is True


def test_no_approval_for_low_risk_draft_email() -> None:
    decision = _decision(
        proposed_action={
            "server": "clinic-ops",
            "tool": "draft_email",
            "arguments": {"to": "a@b.com", "subject": "s", "body": "b"},
        }
    )
    assert requires_approval(decision) is False


def test_default_threshold_is_075() -> None:
    assert DEFAULT_APPROVAL_CONFIDENCE_THRESHOLD == 0.75
