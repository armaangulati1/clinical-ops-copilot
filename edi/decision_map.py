"""Decision -> X12 278 response (HCR) mapping.

The agent emits one of three internal decisions. This module maps each onto an
HCR (Health Care Services Review) action code for the 278 RESPONSE.

Role framing: the agent's decisions are provider-side. A 278 RESPONSE is issued
by the payer/UMO side, so this mapping and the response generator simulate the
utilization-review side for demo purposes, showing what a payer-side
determination would look like given the agent's assessment. It is
pre-adjudication demo output, not a claim that the agent is a
utilization-management organization.

Honest mapping note: the agent's ``deny-risk`` is a *risk flag behind a human
approval gate*, not a denial authority. It therefore does NOT map to HCR A3
(Not Certified / denied). It maps to A4 (Pended) with a review reason, exactly
like ``request-more-info``, but with a distinct reason so a human reviewer sees
why it was flagged. Only a human, downstream of this system, can issue A3.
"""

from __future__ import annotations

from dataclasses import dataclass

from schemas.decisions import DecisionAction


@dataclass(frozen=True)
class HcrMapping:
    """An HCR action code plus a human-readable reason for a decision."""

    action_code: str  # HCR01
    action_label: str
    reason: str  # surfaced in MSG (PHI-safe)


# Single source of truth for the mapping (also rendered in the README table).
DECISION_TO_HCR: dict[DecisionAction, HcrMapping] = {
    DecisionAction.SUBMIT: HcrMapping(
        action_code="A1",
        action_label="Certified in Total",
        reason="Required policy criteria met; cleared to submit.",
    ),
    DecisionAction.REQUEST_MORE_INFO: HcrMapping(
        action_code="A4",
        action_label="Pended",
        reason="Additional documentation required before a determination.",
    ),
    DecisionAction.DENY_RISK: HcrMapping(
        action_code="A4",
        action_label="Pended",
        reason=(
            "Flagged as denial risk for human review; "
            "not an automated denial (no A3 authority)."
        ),
    ),
}


def map_decision(action: DecisionAction) -> HcrMapping:
    """Return the HCR mapping for a decision action."""
    return DECISION_TO_HCR[action]
