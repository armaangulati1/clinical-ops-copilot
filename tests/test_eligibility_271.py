"""Tests for the deterministic 271 responder and its response generator."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from edi.eligibility_271 import (
    BENEFIT_SEGMENT,
    COVERAGE_TABLE,
    REJECT_SEGMENT,
    SERVICE_TYPES,
    BenefitOutcome,
    EligibilityResponse,
    MemberCoverage,
    RejectReason,
    ServiceBenefit,
    answer_270,
    build_271_response,
    resolve_eligibility,
)
from edi.errors import InvalidSegmentError
from edi.tokenizer import tokenize
from edi.x12_270 import parse_270_inquiry

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "edi" / "fixtures" / "x270"


def _read(stem: str) -> str:
    return (FIXTURES / f"{stem}.270").read_text(encoding="utf-8")


def _resolve(stem: str) -> EligibilityResponse:
    return resolve_eligibility(parse_270_inquiry(_read(stem)))


def test_active_coverage_reports_copay() -> None:
    response = _resolve("active_medical_single")
    assert not response.rejected
    assert response.plan_name == "DEMO PLAN A"
    row = response.rows[0]
    assert row.outcome is BenefitOutcome.ACTIVE_COVERED
    assert row.copay == Decimal("25.00")
    assert row.deductible_remaining == Decimal("0")


def test_prior_auth_outranks_active_coverage() -> None:
    response = _resolve("multi_service_types")
    outcomes = [row.outcome for row in response.rows]
    assert outcomes == [
        BenefitOutcome.ACTIVE_COVERED,
        BenefitOutcome.ACTIVE_COVERED,
        BenefitOutcome.AUTH_REQUIRED,
    ]


def test_unmet_deductible_reported_with_remaining_amount() -> None:
    row = _resolve("deductible_unmet").rows[0]
    assert row.outcome is BenefitOutcome.DEDUCTIBLE_UNMET
    assert row.deductible_remaining == Decimal("400.00")


def test_service_type_absent_from_plan_is_not_covered() -> None:
    row = _resolve("not_covered_service").rows[0]
    assert row.outcome is BenefitOutcome.NOT_COVERED
    assert row.copay is None
    assert row.deductible_remaining is None


def test_inactive_plan_overrides_every_service_type() -> None:
    response = _resolve("inactive_plan")
    assert [row.outcome for row in response.rows] == [
        BenefitOutcome.INACTIVE,
        BenefitOutcome.INACTIVE,
    ]


def test_unknown_member_rejects_the_whole_inquiry() -> None:
    response = _resolve("unknown_member")
    assert response.rejected
    assert response.reject is RejectReason.MEMBER_NOT_FOUND
    assert response.rows == []


def test_birth_date_mismatch_rejects_rather_than_resolving() -> None:
    response = _resolve("dob_mismatch")
    assert response.reject is RejectReason.DOB_MISMATCH
    assert response.rows == []


def test_inquiry_without_member_id_raises_structured_error() -> None:
    text = _read("active_medical_single").replace("*MI*MBR-1001", "*ZZ*MBR-1001")
    with pytest.raises(InvalidSegmentError):
        resolve_eligibility(parse_270_inquiry(text))


def test_auth_required_outranks_unmet_deductible() -> None:
    # A benefit carrying both flags must report the more restrictive outcome.
    coverage = MemberCoverage(
        member_id="MBR-TEST",
        last_name="TEST",
        birth_date="19900101",
        plan_name="DEMO PLAN T",
        plan_active=True,
        benefits={
            "SRV-MEDICAL": ServiceBenefit(
                copay=Decimal("10.00"),
                deductible_remaining=Decimal("100.00"),
                prior_auth_required=True,
            )
        },
    )
    COVERAGE_TABLE["MBR-TEST"] = coverage
    try:
        text = (
            _read("active_medical_single")
            .replace("MBR-1001", "MBR-TEST")
            .replace("19850214", "19900101")
        )
        row = resolve_eligibility(parse_270_inquiry(text)).rows[0]
        assert row.outcome is BenefitOutcome.AUTH_REQUIRED
    finally:
        del COVERAGE_TABLE["MBR-TEST"]


def test_unrecognized_service_type_is_not_covered_not_a_crash() -> None:
    text = _read("active_medical_single").replace("SRV-MEDICAL", "SRV-NOT-A-BENEFIT")
    row = resolve_eligibility(parse_270_inquiry(text)).rows[0]
    assert row.outcome is BenefitOutcome.NOT_COVERED


def test_generated_271_carries_benefit_rows_in_invented_segment() -> None:
    inquiry = parse_270_inquiry(_read("multi_service_types"))
    response = resolve_eligibility(inquiry)
    interchange = build_271_response(inquiry, response)
    segments, _ = tokenize(interchange)
    benefit_rows = [s for s in segments if s.segment_id == BENEFIT_SEGMENT]
    assert len(benefit_rows) == 3
    assert benefit_rows[0].element(1) == "SRV-MEDICAL"
    assert benefit_rows[0].element(2) == "EB-ACTIVE-COVERED"
    assert benefit_rows[2].element(2) == "EB-AUTH-REQUIRED"


def test_generated_271_is_a_271_transaction_and_echoes_the_member() -> None:
    inquiry = parse_270_inquiry(_read("active_medical_single"))
    interchange = build_271_response(inquiry, resolve_eligibility(inquiry))
    segments, _ = tokenize(interchange)
    st = next(s for s in segments if s.segment_id == "ST")
    assert st.element(1) == "271"
    subscriber = next(
        s for s in segments if s.segment_id == "NM1" and s.element(1) == "IL"
    )
    assert subscriber.element(9) == "MBR-1001"


def test_generated_271_round_trips_through_the_tokenizer() -> None:
    # The generated response must be tokenizable by the shared ISA bootstrap.
    _, interchange = answer_270(_read("inactive_plan"))
    segments, delimiters = tokenize(interchange)
    assert delimiters.distinct()
    assert [s.segment_id for s in segments][:3] == ["ISA", "GS", "ST"]


def test_rejected_inquiry_emits_reject_carrier_and_no_benefit_rows() -> None:
    _, interchange = answer_270(_read("unknown_member"))
    segments, _ = tokenize(interchange)
    rejects = [s for s in segments if s.segment_id == REJECT_SEGMENT]
    assert len(rejects) == 1
    assert rejects[0].element(1) == "RJ-MEMBER-NOT-FOUND"
    assert not [s for s in segments if s.segment_id == BENEFIT_SEGMENT]


def test_se_segment_count_matches_the_transaction_body() -> None:
    _, interchange = answer_270(_read("multi_service_types"))
    segments, _ = tokenize(interchange)
    body = [s for s in segments if s.segment_id not in ("ISA", "GS", "GE", "IEA")]
    se = next(s for s in segments if s.segment_id == "SE")
    assert se.element(1) == str(len(body))


def test_every_service_type_in_the_table_has_a_description() -> None:
    used = {
        service_type
        for coverage in COVERAGE_TABLE.values()
        for service_type in coverage.benefits
    }
    assert used
    assert used <= set(SERVICE_TYPES)


def test_coverage_table_uses_only_self_authored_vocabularies() -> None:
    for member_id, coverage in COVERAGE_TABLE.items():
        assert member_id.startswith("MBR-")
        assert coverage.member_id == member_id
        for service_type in coverage.benefits:
            assert service_type.startswith("SRV-")
