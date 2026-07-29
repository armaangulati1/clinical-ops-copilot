"""Tests for the deterministic 277 responder and its response generator.

Includes the cross-layer consistency check: the finalized claims in the demo
claim store must match the 835 layer's self-authored fixtures claim for claim,
so the two demo layers cannot silently drift apart.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from edi.claim_status_277 import (
    CLAIM_STORE,
    DENIAL_SEGMENT,
    ClaimRejectReason,
    ClaimStatus,
    ClaimStatusResponse,
    StoredClaim,
    answer_276,
    build_277_response,
    resolve_claim_status,
)
from edi.denial_triage import DENIAL_CODE_TABLE
from edi.invented_segments import REJECT_SEGMENT, STATUS_SEGMENT
from edi.tokenizer import tokenize
from edi.x12_276 import parse_276_inquiry
from edi.x12_835 import parse_835

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "edi" / "fixtures" / "x276"
FIXTURES_835 = PROJECT_ROOT / "edi" / "fixtures" / "x835"


def _read(stem: str) -> str:
    return (FIXTURES / f"{stem}.276").read_text(encoding="utf-8")


def _resolve(stem: str) -> ClaimStatusResponse:
    return resolve_claim_status(parse_276_inquiry(_read(stem)))


def test_paid_claim_reports_finalized_paid() -> None:
    row = _resolve("single_paid").rows[0]
    assert row.status is ClaimStatus.FINALIZED_PAID
    assert row.billed == Decimal("500.00")
    assert row.paid == Decimal("500.00")
    assert row.denial_codes == []


def test_partial_payment_reports_finalized_partial() -> None:
    row = _resolve("partial_payment").rows[0]
    assert row.status is ClaimStatus.FINALIZED_PARTIAL
    assert row.billed == Decimal("450.00")
    assert row.paid == Decimal("180.00")


def test_denied_claim_echoes_self_authored_denial_codes() -> None:
    rows = _resolve("batch_three").rows
    assert [row.status for row in rows] == [
        ClaimStatus.FINALIZED_PAID,
        ClaimStatus.FINALIZED_DENIED,
        ClaimStatus.FINALIZED_DENIED,
    ]
    assert rows[1].denial_codes == ["DR-DOC-MISSING"]
    assert rows[2].denial_codes == ["DR-CODE-INVALID"]


def test_pending_claims_split_by_reason() -> None:
    assert _resolve("pending_review").rows[0].status is ClaimStatus.PENDING_REVIEW
    assert (
        _resolve("pending_documentation").rows[0].status
        is ClaimStatus.PENDING_DOCUMENTATION
    )


def test_unknown_claim_reports_not_found_with_a_reject_reason() -> None:
    row = _resolve("unknown_claim").rows[0]
    assert row.status is ClaimStatus.NOT_FOUND
    assert row.reject is ClaimRejectReason.CLAIM_NOT_FOUND
    assert row.billed is None


def test_unknown_claim_does_not_suppress_the_known_ones() -> None:
    rows = _resolve("mixed_known_unknown").rows
    assert [row.claim_ref for row in rows] == ["CLM-6001", "CLM-9998"]
    assert rows[0].status is ClaimStatus.FINALIZED_DENIED
    assert rows[1].status is ClaimStatus.NOT_FOUND


def test_unrecognized_adjudication_token_never_reports_finalized() -> None:
    # Fail safe: an adjudication token the mapping does not know must not be
    # reported as a completed outcome.
    CLAIM_STORE["CLM-TEST"] = StoredClaim(
        claim_ref="CLM-TEST", adjudication="WAT", billed=Decimal("10.00")
    )
    try:
        text = _read("single_paid").replace("CLM-1001", "CLM-TEST")
        row = resolve_claim_status(parse_276_inquiry(text)).rows[0]
        assert row.status is ClaimStatus.PENDING_REVIEW
    finally:
        del CLAIM_STORE["CLM-TEST"]


def test_denied_rationale_names_the_denial_reasons() -> None:
    row = _resolve("mixed_known_unknown").rows[0]
    assert "Coordination-of-benefits" in row.rationale


def test_generated_277_carries_status_rows_in_invented_segment() -> None:
    inquiry = parse_276_inquiry(_read("batch_three"))
    interchange = build_277_response(inquiry, resolve_claim_status(inquiry))
    segments, _ = tokenize(interchange)
    statuses = [s for s in segments if s.segment_id == STATUS_SEGMENT]
    assert [s.element(1) for s in statuses] == [
        "CS-FINALIZED-PAID",
        "CS-FINALIZED-DENIED",
        "CS-FINALIZED-DENIED",
    ]


def test_generated_277_is_a_277_transaction_and_echoes_the_trace() -> None:
    _, interchange = answer_276(_read("single_paid"))
    segments, _ = tokenize(interchange)
    st = next(s for s in segments if s.segment_id == "ST")
    assert st.element(1) == "277"
    trn = next(s for s in segments if s.segment_id == "TRN")
    assert trn.element(2) == "TRACE-S001"


def test_generated_277_carries_denial_codes_in_the_shared_drc_carrier() -> None:
    _, interchange = answer_276(_read("batch_three"))
    segments, _ = tokenize(interchange)
    denials = [s for s in segments if s.segment_id == DENIAL_SEGMENT]
    assert [s.element(1) for s in denials] == ["DR-DOC-MISSING", "DR-CODE-INVALID"]


def test_generated_277_emits_a_reject_carrier_for_unknown_claims() -> None:
    _, interchange = answer_276(_read("unknown_claim"))
    segments, _ = tokenize(interchange)
    rejects = [s for s in segments if s.segment_id == REJECT_SEGMENT]
    assert len(rejects) == 1
    assert rejects[0].element(1) == "RJ-CLAIM-NOT-FOUND"


def test_generated_277_round_trips_through_the_tokenizer() -> None:
    _, interchange = answer_276(_read("mixed_known_unknown"))
    segments, delimiters = tokenize(interchange)
    assert delimiters.distinct()
    assert [s.segment_id for s in segments][:3] == ["ISA", "GS", "ST"]


def test_se_segment_count_matches_the_transaction_body() -> None:
    _, interchange = answer_276(_read("batch_three"))
    segments, _ = tokenize(interchange)
    body = [s for s in segments if s.segment_id not in ("ISA", "GS", "GE", "IEA")]
    se = next(s for s in segments if s.segment_id == "SE")
    assert se.element(1) == str(len(body))


def test_store_uses_only_self_authored_denial_codes() -> None:
    for claim in CLAIM_STORE.values():
        for code in claim.denial_codes:
            assert code.startswith("DR-")
            assert code in DENIAL_CODE_TABLE


def test_store_matches_the_835_fixture_claims() -> None:
    """Cross-layer: every claim in both places must agree on the shapes."""
    from_835: dict[str, tuple[str, Decimal, Decimal, tuple[str, ...]]] = {}
    for path in sorted(FIXTURES_835.glob("*.835")):
        if path.name.startswith("malformed_"):
            continue
        for claim in parse_835(path.read_text(encoding="utf-8")).claims:
            from_835[claim.claim_ref] = (
                claim.status,
                claim.billed,
                claim.paid,
                tuple(claim.all_denial_codes()),
            )

    overlap = set(from_835) & set(CLAIM_STORE)
    assert len(overlap) >= 8, "the two demo layers should share their finalized claims"
    for ref in sorted(overlap):
        status, billed, paid, denial_codes = from_835[ref]
        stored = CLAIM_STORE[ref]
        assert stored.adjudication == status, ref
        assert stored.billed == billed, ref
        assert stored.paid == paid, ref
        assert stored.denial_codes == denial_codes, ref


def test_pending_claims_have_no_835_counterpart_by_design() -> None:
    # A remittance only exists once adjudication finished, so pending claims
    # must not appear in the 835 fixtures.
    refs_835 = {
        claim.claim_ref
        for path in FIXTURES_835.glob("*.835")
        if not path.name.startswith("malformed_")
        for claim in parse_835(path.read_text(encoding="utf-8")).claims
    }
    pending = {
        ref for ref, claim in CLAIM_STORE.items() if claim.adjudication == "PEND"
    }
    assert pending
    assert not (pending & refs_835)
