"""Route prior-auth extraction using payer policy and note context."""

from __future__ import annotations

from schemas.policies import PayerPolicy
from servers.clinical_data.policy_service import get_payer_policy
from servers.clinical_data.priorauth_extractor.types import (
    COMMON_FIELDS,
    CONDITION_FIELDS,
    ConditionPath,
    PipelineState,
    RoutePlan,
)


def condition_path_from_policy(policy: PayerPolicy) -> ConditionPath:
    """Map a payer policy to a prior-auth condition path."""
    condition = policy.condition.lower()
    drug = policy.drug.lower()
    if "rheumatoid" in condition or "humira" in drug or "adalimumab" in drug:
        return ConditionPath.RA
    if "diabetes" in condition or "ozempic" in drug or "semaglutide" in drug:
        return ConditionPath.T2D
    if "migraine" in condition or "aimovig" in drug or "erenumab" in drug:
        return ConditionPath.MIGRAINE
    msg = f"Unsupported prior-auth policy: {policy.drug!r} / {policy.condition!r}"
    raise ValueError(msg)


def infer_policy_from_note(note_text: str) -> PayerPolicy:
    """Infer payer policy from note keywords when not supplied by the caller."""
    lowered = note_text.lower()
    if any(
        token in lowered for token in ("rheumatoid arthritis", "humira", "adalimumab")
    ):
        return get_payer_policy("Humira", "rheumatoid arthritis")
    if any(token in lowered for token in ("type 2 diabetes", "ozempic", "semaglutide")):
        return get_payer_policy("Ozempic", "type 2 diabetes")
    if any(token in lowered for token in ("chronic migraine", "aimovig", "erenumab")):
        return get_payer_policy("Aimovig", "chronic migraine")
    msg = "Could not infer prior-auth policy from note text"
    raise ValueError(msg)


def resolve_policy(note_text: str, policy: PayerPolicy | None) -> PayerPolicy:
    if policy is not None:
        return policy
    return infer_policy_from_note(note_text)


def route(note_text: str, policy: PayerPolicy) -> RoutePlan:
    """Decide condition path and required fields from policy + note."""
    _ = note_text
    condition_path = condition_path_from_policy(policy)
    required = list(policy.required_criteria_fields)
    expected = set(CONDITION_FIELDS[condition_path]) | set(COMMON_FIELDS)
    if not set(required).issubset(expected):
        msg = (
            f"Policy required fields {required} do not match condition path "
            f"{condition_path.value}"
        )
        raise ValueError(msg)
    return RoutePlan(
        condition_path=condition_path,
        required_fields=required,
        extract_common=True,
        extract_condition_fields=True,
    )


def apply_router(state: PipelineState) -> PipelineState:
    state.route = route(state.note, state.policy)
    return state
