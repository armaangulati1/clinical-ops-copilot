"""Deterministic guardrails applied after planner decisions."""

from __future__ import annotations

from dataclasses import dataclass

from schemas.decisions import Decision, DecisionAction, ProposedAction
from schemas.extraction_result import ExtractionResult
from schemas.policies import PayerPolicy

GUARDRAIL_CONFIDENCE_CAP = 0.5

SUBMISSION_TOOLS = frozenset({"create_task", "send_email", "schedule_followup"})


@dataclass(frozen=True)
class GuardrailResult:
    """Outcome of required-field enforcement on a planner decision."""

    decision: Decision
    triggered: bool
    missing_fields: tuple[str, ...] = ()
    original_action: DecisionAction | None = None
    original_confidence: float | None = None


def missing_required_fields(
    extraction_result: ExtractionResult,
    policy: PayerPolicy,
) -> list[str]:
    """Return required policy fields that are absent or flagged for review."""
    absent: list[str] = []
    needs_review = set(extraction_result.needs_review)
    for field_name in policy.required_criteria_fields:
        value = getattr(extraction_result.extraction, field_name, None)
        if value is None or field_name in needs_review:
            absent.append(field_name)
    return sorted(set(absent))


def enforce_required_fields(
    decision: Decision,
    extraction_result: ExtractionResult,
    policy: PayerPolicy,
) -> Decision:
    """Block submit when required policy fields are missing from extraction."""
    return evaluate_required_field_guardrail(
        decision,
        extraction_result,
        policy,
    ).decision


def evaluate_required_field_guardrail(
    decision: Decision,
    extraction_result: ExtractionResult,
    policy: PayerPolicy,
) -> GuardrailResult:
    """Apply the submit guardrail and return the adjusted decision plus metadata."""
    if decision.action != DecisionAction.SUBMIT:
        return GuardrailResult(decision=decision, triggered=False)

    absent = missing_required_fields(extraction_result, policy)
    if not absent:
        return GuardrailResult(decision=decision, triggered=False)

    capped_confidence = min(decision.confidence, GUARDRAIL_CONFIDENCE_CAP)
    guardrail_note = (
        "Deterministic guardrail: submit overridden to request-more-info "
        f"because required field(s) are missing or flagged for review: "
        f"{', '.join(absent)}."
    )
    rationale = f"{decision.rationale.strip()} [{guardrail_note}]"

    needs_review = sorted(
        set(decision.needs_review) | set(extraction_result.needs_review) | set(absent)
    )

    overridden = decision.model_copy(
        update={
            "action": DecisionAction.REQUEST_MORE_INFO,
            "confidence": capped_confidence,
            "rationale": rationale,
            "missing_fields": absent,
            "needs_review": needs_review,
            "proposed_action": _request_info_proposed_action(absent),
        }
    )

    return GuardrailResult(
        decision=overridden,
        triggered=True,
        missing_fields=tuple(absent),
        original_action=decision.action,
        original_confidence=decision.confidence,
    )


def guardrail_audit_payload(result: GuardrailResult) -> dict[str, object]:
    """Build a PHI-safe audit payload for a triggered guardrail."""
    if not result.triggered:
        return {}
    return {
        "event": "required_field_guardrail",
        "original_action": (
            result.original_action.value if result.original_action else None
        ),
        "overridden_action": DecisionAction.REQUEST_MORE_INFO.value,
        "missing_fields": list(result.missing_fields),
        "original_confidence": result.original_confidence,
        "new_confidence": result.decision.confidence,
    }


def _request_info_proposed_action(missing_fields: list[str]) -> ProposedAction:
    return ProposedAction(
        server="clinic-ops",
        tool="draft_email",
        arguments={
            "to": "provider@clinic.example",
            "subject": "Additional documentation needed for prior authorization",
            "body": (
                "Please provide documentation for the following required fields: "
                f"{', '.join(missing_fields)}."
            ),
        },
    )


def implies_submission(proposed_action: ProposedAction | None) -> bool:
    """Whether a proposed clinic-ops action would advance a submission."""
    if proposed_action is None:
        return False
    return proposed_action.tool in SUBMISSION_TOOLS
