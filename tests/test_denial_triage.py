"""Tests for the deterministic denial-triage rules."""

from __future__ import annotations

from decimal import Decimal

from edi.denial_triage import (
    DENIAL_CODE_TABLE,
    TriageRecommendation,
    triage_claim,
    triage_remittance,
)
from edi.x12_835 import ClaimPayment, RemittanceAdvice, ServiceLine


def _claim(codes: list[str], *, billed: str = "100", paid: str = "0") -> ClaimPayment:
    return ClaimPayment(
        claim_ref="CLM-T",
        status="DENY",
        billed=Decimal(billed),
        paid=Decimal(paid),
        denial_codes=list(codes),
    )


def test_paid_in_full_no_codes_is_no_action() -> None:
    claim = _claim([], billed="100", paid="100")
    result = triage_claim(claim)
    assert result.recommendation is TriageRecommendation.NO_ACTION


def test_doc_missing_is_resubmit() -> None:
    result = triage_claim(_claim(["DR-DOC-MISSING"]))
    assert result.recommendation is TriageRecommendation.RESUBMIT_WITH_DOCUMENTATION
    assert "DR-DOC-MISSING" in result.rationale


def test_auth_absent_is_resubmit() -> None:
    result = triage_claim(_claim(["DR-AUTH-ABSENT"]))
    assert result.recommendation is TriageRecommendation.RESUBMIT_WITH_DOCUMENTATION


def test_code_invalid_is_correct_and_rebill() -> None:
    result = triage_claim(_claim(["DR-CODE-INVALID"]))
    assert result.recommendation is TriageRecommendation.CORRECT_AND_REBILL


def test_elig_lapsed_is_correct_and_rebill() -> None:
    result = triage_claim(_claim(["DR-ELIG-LAPSED"]))
    assert result.recommendation is TriageRecommendation.CORRECT_AND_REBILL


def test_duplicate_is_human_review() -> None:
    result = triage_claim(_claim(["DR-DUPLICATE"]))
    assert result.recommendation is TriageRecommendation.NEEDS_HUMAN_REVIEW


def test_cob_is_human_review() -> None:
    result = triage_claim(_claim(["DR-COORD-BENEFITS"]))
    assert result.recommendation is TriageRecommendation.NEEDS_HUMAN_REVIEW


def test_unrecognized_code_routes_to_human_review() -> None:
    result = triage_claim(_claim(["DR-NOT-A-REAL-CODE"]))
    assert result.recommendation is TriageRecommendation.NEEDS_HUMAN_REVIEW
    assert result.unrecognized_codes == ["DR-NOT-A-REAL-CODE"]


def test_precedence_human_review_wins_over_resubmit() -> None:
    # doc-missing (resubmit) + duplicate (human) -> human review
    result = triage_claim(_claim(["DR-DOC-MISSING", "DR-DUPLICATE"]))
    assert result.recommendation is TriageRecommendation.NEEDS_HUMAN_REVIEW


def test_precedence_correct_rebill_wins_over_resubmit() -> None:
    result = triage_claim(_claim(["DR-DOC-MISSING", "DR-CODE-INVALID"]))
    assert result.recommendation is TriageRecommendation.CORRECT_AND_REBILL


def test_underpaid_without_code_routes_to_human_review() -> None:
    claim = _claim([], billed="100", paid="40")
    result = triage_claim(claim)
    assert result.recommendation is TriageRecommendation.NEEDS_HUMAN_REVIEW


def test_line_level_codes_are_considered() -> None:
    claim = ClaimPayment(
        claim_ref="CLM-L",
        status="DENY",
        billed=Decimal("100"),
        paid=Decimal("0"),
        service_lines=[
            ServiceLine(procedure="PROC-A", denial_codes=["DR-CODE-INVALID"])
        ],
    )
    result = triage_claim(claim)
    assert result.recommendation is TriageRecommendation.CORRECT_AND_REBILL


def test_triage_remittance_preserves_order() -> None:
    remit = RemittanceAdvice(
        claims=[
            _claim([], billed="10", paid="10"),
            _claim(["DR-DOC-MISSING"]),
        ]
    )
    results = triage_remittance(remit)
    assert [r.recommendation for r in results] == [
        TriageRecommendation.NO_ACTION,
        TriageRecommendation.RESUBMIT_WITH_DOCUMENTATION,
    ]


def test_every_table_code_maps_to_a_real_recommendation() -> None:
    for rule in DENIAL_CODE_TABLE.values():
        assert isinstance(rule.recommendation, TriageRecommendation)
        assert rule.recommendation is not TriageRecommendation.NO_ACTION
        assert rule.code.startswith("DR-")
