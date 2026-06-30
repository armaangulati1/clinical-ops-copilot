"""Unit tests for deterministic required-field guardrails."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent.approval_store import InMemoryApprovalStore
from agent.audit import InMemoryAuditTrail, get_case_history
from agent.config import load_config
from agent.decision_guardrail import (
    GUARDRAIL_CONFIDENCE_CAP,
    enforce_required_fields,
    evaluate_required_field_guardrail,
    guardrail_audit_payload,
    implies_submission,
    missing_required_fields,
)
from agent.executor import ActionExecutor
from agent.gate import ApprovalGate
from agent.mcp_host import DiscoveredTool, MockMcpHost
from agent.workflow import run_case_with_gate
from schemas.approval import AuditEventType, WorkflowStatus
from schemas.cases import Case
from schemas.decisions import Decision, DecisionAction, ProposedAction
from schemas.extraction import Extraction
from schemas.extraction_result import ExtractionResult
from schemas.policies import PayerPolicy
from schemas.run_metrics import PlannerRunMetrics

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _ra_policy() -> PayerPolicy:
    return PayerPolicy(
        drug="Humira",
        condition="rheumatoid arthritis",
        required_criteria_fields=[
            "diagnosis_confirmed",
            "disease_duration_months",
            "failed_dmards",
            "das28_score",
            "methotrexate_trial_weeks",
        ],
        rules="Synthetic RA policy for guardrail unit tests.",
    )


def _submit_decision(**updates: object) -> Decision:
    base = Decision(
        action=DecisionAction.SUBMIT,
        confidence=0.95,
        rationale="All documented criteria appear satisfied for submission.",
        missing_fields=[],
        proposed_action=ProposedAction(
            server="clinic-ops",
            tool="create_task",
            arguments={
                "title": "Submit prior authorization",
                "details": "Prepare payer submission packet.",
                "idempotency_key": "case-test-submit",
            },
        ),
    )
    return base.model_copy(update=updates)


def _deny_risk_decision(**updates: object) -> Decision:
    base = Decision(
        action=DecisionAction.DENY_RISK,
        confidence=0.9,
        rationale="Documented criteria fail payer thresholds; denial recommended.",
        missing_fields=[],
        proposed_action=ProposedAction(
            server="clinic-ops",
            tool="create_task",
            arguments={
                "title": "Document prior-auth denial",
                "details": "Criteria not met for coverage.",
                "idempotency_key": "case-test-deny",
            },
        ),
    )
    return base.model_copy(update=updates)


def _extraction(**fields: Any) -> ExtractionResult:
    return ExtractionResult(
        extraction=Extraction(**fields),
        needs_review=[],
    )


def test_missing_required_fields_detects_null_and_needs_review() -> None:
    policy = _ra_policy()
    extraction = _extraction(
        diagnosis_confirmed=True,
        disease_duration_months=12,
        failed_dmards=2,
        das28_score=4.2,
        methotrexate_trial_weeks=None,
    )
    assert missing_required_fields(extraction, policy) == ["methotrexate_trial_weeks"]

    flagged = ExtractionResult(
        extraction=Extraction(
            diagnosis_confirmed=True,
            disease_duration_months=12,
            failed_dmards=2,
            das28_score=4.2,
            methotrexate_trial_weeks=16,
        ),
        needs_review=["das28_score"],
    )
    assert missing_required_fields(flagged, policy) == ["das28_score"]


def test_submit_with_missing_required_field_is_overridden() -> None:
    policy = _ra_policy()
    extraction = _extraction(
        diagnosis_confirmed=True,
        disease_duration_months=12,
        failed_dmards=2,
        das28_score=4.2,
        methotrexate_trial_weeks=None,
    )
    original = _submit_decision()
    result = evaluate_required_field_guardrail(original, extraction, policy)

    assert result.triggered is True
    assert result.missing_fields == ("methotrexate_trial_weeks",)
    decision = result.decision
    assert decision.action == DecisionAction.REQUEST_MORE_INFO
    assert decision.missing_fields == ["methotrexate_trial_weeks"]
    assert decision.confidence == GUARDRAIL_CONFIDENCE_CAP
    assert "Deterministic guardrail" in decision.rationale
    assert decision.proposed_action is not None
    assert decision.proposed_action.tool == "draft_email"
    assert not implies_submission(decision.proposed_action)
    assert implies_submission(original.proposed_action)

    payload = guardrail_audit_payload(result)
    assert payload["event"] == "required_field_guardrail"
    assert payload["missing_fields"] == ["methotrexate_trial_weeks"]


def test_submit_with_all_required_fields_present_is_unchanged() -> None:
    policy = _ra_policy()
    extraction = _extraction(
        diagnosis_confirmed=True,
        disease_duration_months=12,
        failed_dmards=2,
        das28_score=4.2,
        methotrexate_trial_weeks=16,
    )
    original = _submit_decision()
    guarded = enforce_required_fields(original, extraction, policy)
    assert guarded == original


@pytest.mark.parametrize("action", [DecisionAction.REQUEST_MORE_INFO])
def test_request_more_info_decisions_are_unchanged(action: DecisionAction) -> None:
    policy = _ra_policy()
    extraction = _extraction(
        diagnosis_confirmed=None,
        disease_duration_months=None,
        failed_dmards=None,
        das28_score=None,
        methotrexate_trial_weeks=None,
    )
    decision = Decision(
        action=action,
        confidence=0.8,
        rationale="Synthetic non-submit decision for guardrail pass-through test.",
        missing_fields=(
            ["das28_score"] if action == DecisionAction.REQUEST_MORE_INFO else []
        ),
        proposed_action=ProposedAction(
            server="clinic-ops",
            tool="draft_email",
            arguments={"to": "a@b.com", "subject": "Info", "body": "Need docs"},
        ),
    )
    guarded = enforce_required_fields(decision, extraction, policy)
    assert guarded == decision


def test_deny_risk_with_missing_required_field_is_overridden() -> None:
    policy = _ra_policy()
    extraction = _extraction(
        diagnosis_confirmed=True,
        disease_duration_months=12,
        failed_dmards=2,
        das28_score=4.2,
        methotrexate_trial_weeks=None,
    )
    original = _deny_risk_decision()
    result = evaluate_required_field_guardrail(original, extraction, policy)

    assert result.triggered is True
    assert result.missing_fields == ("methotrexate_trial_weeks",)
    assert result.original_action == DecisionAction.DENY_RISK
    decision = result.decision
    assert decision.action == DecisionAction.REQUEST_MORE_INFO
    assert decision.missing_fields == ["methotrexate_trial_weeks"]
    assert decision.confidence == GUARDRAIL_CONFIDENCE_CAP
    assert "Deterministic guardrail" in decision.rationale
    assert "routed to request-more-info" in decision.rationale
    assert decision.proposed_action is not None
    assert decision.proposed_action.tool == "draft_email"
    assert not implies_submission(decision.proposed_action)

    payload = guardrail_audit_payload(result)
    assert payload["event"] == "required_field_guardrail"
    assert payload["original_action"] == "deny-risk"
    assert payload["overridden_action"] == "request-more-info"
    assert payload["missing_fields"] == ["methotrexate_trial_weeks"]


def test_deny_risk_with_all_required_fields_present_is_unchanged() -> None:
    """Legitimate denial when criteria fail but every required field is documented."""
    policy = _ra_policy()
    extraction = _extraction(
        diagnosis_confirmed=True,
        disease_duration_months=12,
        failed_dmards=2,
        das28_score=2.5,
        methotrexate_trial_weeks=16,
    )
    original = _deny_risk_decision()
    guarded = enforce_required_fields(original, extraction, policy)
    assert guarded == original


class SubmitOnlyPlanner:
    """Always returns a high-confidence submit (for guardrail e2e tests)."""

    async def plan_decision(
        self,
        case: Case,
        extraction: ExtractionResult,
        policy: PayerPolicy,
        discovered_tools: list[DiscoveredTool],
    ) -> Decision:
        _ = (case, extraction, policy, discovered_tools)
        return Decision(
            action=DecisionAction.SUBMIT,
            confidence=0.95,
            rationale="Planner output forced to submit for guardrail integration test.",
            missing_fields=[],
            proposed_action=ProposedAction(
                server="clinic-ops",
                tool="create_task",
                arguments={
                    "title": "Submit prior authorization",
                    "details": "Should be blocked by guardrail.",
                    "idempotency_key": "guardrail-e2e",
                },
            ),
        )

    @property
    def last_metrics(self) -> PlannerRunMetrics:
        return PlannerRunMetrics(model="submit-only-test")


class DenyRiskPlanner:
    """Always returns a high-confidence deny-risk (for guardrail e2e tests)."""

    async def plan_decision(
        self,
        case: Case,
        extraction: ExtractionResult,
        policy: PayerPolicy,
        discovered_tools: list[DiscoveredTool],
    ) -> Decision:
        _ = (case, extraction, policy, discovered_tools)
        return Decision(
            action=DecisionAction.DENY_RISK,
            confidence=0.9,
            rationale="Planner output forced to deny-risk for guardrail integration test.",
            missing_fields=[],
            proposed_action=ProposedAction(
                server="clinic-ops",
                tool="create_task",
                arguments={
                    "title": "Document prior-auth denial",
                    "details": "Should be blocked by guardrail when fields are missing.",
                    "idempotency_key": "guardrail-deny-e2e",
                },
            ),
        )

    @property
    def last_metrics(self) -> PlannerRunMetrics:
        return PlannerRunMetrics(model="deny-risk-only-test")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_guardrail_blocks_submit_end_to_end_and_logs_audit_event() -> None:
    policy = _ra_policy()
    case = Case(
        case_id="case-097",
        clinical_note=(
            "Synthetic prior-auth note for guardrail integration testing with "
            "incomplete methotrexate documentation in the chart."
        ),
        payer_policy=policy,
        drug=policy.drug,
        condition=policy.condition,
    )
    extraction = ExtractionResult(
        extraction=Extraction(
            diagnosis_confirmed=True,
            disease_duration_months=14,
            failed_dmards=2,
            das28_score=4.1,
            methotrexate_trial_weeks=None,
        ),
    )
    host = MockMcpHost(
        extraction_payload=extraction.model_dump(mode="json"),
        policy_payload=policy.model_dump(mode="json"),
    )
    audit = InMemoryAuditTrail()
    gate = ApprovalGate(
        InMemoryApprovalStore(),
        audit,
        ActionExecutor(host, audit),
    )

    result = await run_case_with_gate(
        case,
        host,
        SubmitOnlyPlanner(),
        gate,
        config=load_config(PROJECT_ROOT),
    )

    assert result.decision.action == DecisionAction.REQUEST_MORE_INFO
    assert result.decision.missing_fields == ["methotrexate_trial_weeks"]
    assert result.decision.confidence <= GUARDRAIL_CONFIDENCE_CAP
    assert result.decision.proposed_action is not None
    assert result.decision.proposed_action.tool == "draft_email"
    assert not implies_submission(result.decision.proposed_action)
    assert host.clinic_ops_counters.get("create_task", 0) == 0
    assert result.status == WorkflowStatus.PENDING_APPROVAL

    history = get_case_history(case.case_id, audit)
    guardrail_events = [
        event for event in history if event.event_type == AuditEventType.GUARDRAIL_EVENT
    ]
    assert len(guardrail_events) == 1
    payload = guardrail_events[0].payload
    assert payload["event"] == "required_field_guardrail"
    assert payload["missing_fields"] == ["methotrexate_trial_weeks"]
    assert payload["original_action"] == "submit"

    decision_index = next(
        index
        for index, event in enumerate(history)
        if event.event_type == AuditEventType.DECISION
    )
    guardrail_index = next(
        index
        for index, event in enumerate(history)
        if event.event_type == AuditEventType.GUARDRAIL_EVENT
    )
    assert guardrail_index < decision_index


@pytest.mark.anyio
async def test_guardrail_blocks_deny_risk_end_to_end_and_logs_audit_event() -> None:
    policy = _ra_policy()
    case = Case(
        case_id="case-098",
        clinical_note=(
            "Synthetic prior-auth note for deny-risk guardrail integration testing with "
            "incomplete methotrexate documentation in the chart."
        ),
        payer_policy=policy,
        drug=policy.drug,
        condition=policy.condition,
    )
    extraction = ExtractionResult(
        extraction=Extraction(
            diagnosis_confirmed=True,
            disease_duration_months=14,
            failed_dmards=2,
            das28_score=4.1,
            methotrexate_trial_weeks=None,
        ),
    )
    host = MockMcpHost(
        extraction_payload=extraction.model_dump(mode="json"),
        policy_payload=policy.model_dump(mode="json"),
    )
    audit = InMemoryAuditTrail()
    gate = ApprovalGate(
        InMemoryApprovalStore(),
        audit,
        ActionExecutor(host, audit),
    )

    result = await run_case_with_gate(
        case,
        host,
        DenyRiskPlanner(),
        gate,
        config=load_config(PROJECT_ROOT),
    )

    assert result.decision.action == DecisionAction.REQUEST_MORE_INFO
    assert result.decision.missing_fields == ["methotrexate_trial_weeks"]
    assert result.decision.confidence <= GUARDRAIL_CONFIDENCE_CAP
    assert result.decision.proposed_action is not None
    assert result.decision.proposed_action.tool == "draft_email"
    assert not implies_submission(result.decision.proposed_action)
    assert host.clinic_ops_counters.get("create_task", 0) == 0
    assert result.status == WorkflowStatus.PENDING_APPROVAL

    history = get_case_history(case.case_id, audit)
    guardrail_events = [
        event for event in history if event.event_type == AuditEventType.GUARDRAIL_EVENT
    ]
    assert len(guardrail_events) == 1
    payload = guardrail_events[0].payload
    assert payload["event"] == "required_field_guardrail"
    assert payload["missing_fields"] == ["methotrexate_trial_weeks"]
    assert payload["original_action"] == "deny-risk"
