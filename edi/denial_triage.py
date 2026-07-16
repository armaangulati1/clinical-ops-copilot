"""Deterministic denial triage over a parsed 835 remittance (demo subset).

Given a :class:`~edi.x12_835.RemittanceAdvice`, this module recommends a next
action per claim using a small, transparent, self-authored denial-code table.
There is no scoring model and no LLM: every recommendation is a pure function of
the denial codes present, so the output is fully reproducible offline.

Invented code system (honest scope): the ``DR-*`` codes below are a demo
vocabulary authored for this project. They are NOT the real CARC/RARC adjustment
reason codes used in production 835 remittances, and this table is not a mapping
of any real payer's denial logic. It exists to demonstrate a rules-driven triage
pattern over remittance data.

Recommendation classes:

* ``resubmit-with-documentation`` - the claim can likely be paid on resubmission
  once the missing supporting material is attached (no data is wrong, something
  is absent).
* ``correct-and-rebill`` - the claim carried incorrect/mismatched data that must
  be fixed before it can be paid.
* ``needs-human-review`` - ambiguous, duplicate, or coordination issues that a
  human must adjudicate before any automated action. Unrecognized codes and
  unexplained shortfalls also route here (fail safe, never fail silent).
* ``no-action`` - claim paid in full with no denial reasons.

When a claim carries several denial codes, the most conservative recommendation
wins (human review > correct-and-rebill > resubmit > no-action).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from edi.x12_835 import ClaimPayment, RemittanceAdvice


class TriageRecommendation(StrEnum):
    """The next action recommended for a claim."""

    NO_ACTION = "no-action"
    RESUBMIT_WITH_DOCUMENTATION = "resubmit-with-documentation"
    CORRECT_AND_REBILL = "correct-and-rebill"
    NEEDS_HUMAN_REVIEW = "needs-human-review"


@dataclass(frozen=True)
class DenialRule:
    """A self-authored denial code, its recommendation, and a plain rationale."""

    code: str
    recommendation: TriageRecommendation
    description: str


# Single source of truth for the invented denial-code vocabulary. Rendered as a
# table in edi/README.md. These are NOT real CARC/RARC codes.
DENIAL_CODE_TABLE: dict[str, DenialRule] = {
    "DR-DOC-MISSING": DenialRule(
        code="DR-DOC-MISSING",
        recommendation=TriageRecommendation.RESUBMIT_WITH_DOCUMENTATION,
        description="Supporting documentation absent; attach and resubmit.",
    ),
    "DR-AUTH-ABSENT": DenialRule(
        code="DR-AUTH-ABSENT",
        recommendation=TriageRecommendation.RESUBMIT_WITH_DOCUMENTATION,
        description="Prior authorization not on file; obtain and resubmit.",
    ),
    "DR-CODE-INVALID": DenialRule(
        code="DR-CODE-INVALID",
        recommendation=TriageRecommendation.CORRECT_AND_REBILL,
        description="Service code invalid or mismatched; correct and rebill.",
    ),
    "DR-ELIG-LAPSED": DenialRule(
        code="DR-ELIG-LAPSED",
        recommendation=TriageRecommendation.CORRECT_AND_REBILL,
        description="Member eligibility data stale; verify and rebill corrected.",
    ),
    "DR-DUPLICATE": DenialRule(
        code="DR-DUPLICATE",
        recommendation=TriageRecommendation.NEEDS_HUMAN_REVIEW,
        description="Flagged as a duplicate; human confirms before any action.",
    ),
    "DR-COORD-BENEFITS": DenialRule(
        code="DR-COORD-BENEFITS",
        recommendation=TriageRecommendation.NEEDS_HUMAN_REVIEW,
        description="Coordination-of-benefits / other-payer issue; human review.",
    ),
}

# Conservative ordering: a higher rank overrides a lower one on the same claim.
_PRECEDENCE: dict[TriageRecommendation, int] = {
    TriageRecommendation.NO_ACTION: 0,
    TriageRecommendation.RESUBMIT_WITH_DOCUMENTATION: 1,
    TriageRecommendation.CORRECT_AND_REBILL: 2,
    TriageRecommendation.NEEDS_HUMAN_REVIEW: 3,
}


@dataclass(frozen=True)
class ClaimTriage:
    """The triage outcome for a single claim."""

    claim_ref: str
    recommendation: TriageRecommendation
    rationale: str
    matched_codes: list[str] = field(default_factory=list)
    unrecognized_codes: list[str] = field(default_factory=list)


def triage_claim(claim: ClaimPayment) -> ClaimTriage:
    """Recommend a next action for one claim from its denial codes and amounts."""
    codes = claim.all_denial_codes()

    if not codes:
        if claim.paid >= claim.billed:
            return ClaimTriage(
                claim_ref=claim.claim_ref,
                recommendation=TriageRecommendation.NO_ACTION,
                rationale="Paid in full with no denial reasons.",
            )
        # Paid short with no coded reason: never guess, route to a human.
        return ClaimTriage(
            claim_ref=claim.claim_ref,
            recommendation=TriageRecommendation.NEEDS_HUMAN_REVIEW,
            rationale=(
                "Underpaid relative to billed amount with no denial code; "
                "requires human review."
            ),
        )

    recognized: list[DenialRule] = []
    unrecognized: list[str] = []
    for code in codes:
        rule = DENIAL_CODE_TABLE.get(code)
        if rule is None:
            unrecognized.append(code)
        else:
            recognized.append(rule)

    # Unrecognized codes cannot be classified: fail safe to human review.
    candidate_recs = [rule.recommendation for rule in recognized]
    if unrecognized:
        candidate_recs.append(TriageRecommendation.NEEDS_HUMAN_REVIEW)

    winner = max(candidate_recs, key=lambda rec: _PRECEDENCE[rec])

    rationale = _build_rationale(winner, recognized, unrecognized)
    return ClaimTriage(
        claim_ref=claim.claim_ref,
        recommendation=winner,
        rationale=rationale,
        matched_codes=[rule.code for rule in recognized],
        unrecognized_codes=unrecognized,
    )


def _build_rationale(
    winner: TriageRecommendation,
    recognized: list[DenialRule],
    unrecognized: list[str],
) -> str:
    """Assemble a deterministic, transparent rationale for the winning class."""
    parts: list[str] = []
    driving = [rule for rule in recognized if rule.recommendation == winner]
    for rule in driving:
        parts.append(f"{rule.code}: {rule.description}")
    if winner is TriageRecommendation.NEEDS_HUMAN_REVIEW and unrecognized:
        parts.append(
            "Unrecognized denial code(s) "
            + ", ".join(unrecognized)
            + " require review."
        )
    if not parts:
        parts.append("Routed to human review.")
    return " ".join(parts)


def triage_remittance(remittance: RemittanceAdvice) -> list[ClaimTriage]:
    """Triage every claim in a parsed remittance, in document order."""
    return [triage_claim(claim) for claim in remittance.claims]
