"""Tests for the self-authored X12 835 remittance parser."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from edi.tokenizer import detect_delimiters, tokenize
from edi.x12_835 import parse_835

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "edi" / "fixtures" / "x835"

WELL_FORMED = sorted(
    p for p in FIXTURES.glob("*.835") if not p.name.startswith("malformed_")
)


def _read(stem: str) -> str:
    return (FIXTURES / f"{stem}.835").read_text(encoding="utf-8")


def test_fixtures_exist() -> None:
    assert len(WELL_FORMED) >= 6


def test_delimiters_detected_from_isa() -> None:
    delimiters = detect_delimiters(_read("paid_full_single"))
    assert delimiters.element == "*"
    assert delimiters.component == ">"
    assert delimiters.segment == "~"
    assert delimiters.repetition == "^"
    assert delimiters.distinct()


def test_tokenize_yields_expected_segments() -> None:
    segments, _ = tokenize(_read("batch_mixed"))
    ids = [seg.segment_id for seg in segments]
    for required in ("ISA", "GS", "ST", "BPR", "CLP", "SVC", "DRC", "SE", "IEA"):
        assert required in ids


def test_parse_paid_full_single() -> None:
    remit = parse_835(_read("paid_full_single"))
    assert remit.transaction_control == "0001"
    assert remit.trace_number == "TRACE-0001"
    assert remit.total_paid == Decimal("500.00")
    assert len(remit.claims) == 1
    claim = remit.claims[0]
    assert claim.claim_ref == "CLM-1001"
    assert claim.status == "PAID"
    assert claim.billed == Decimal("500.00")
    assert claim.paid == Decimal("500.00")
    assert claim.all_denial_codes() == []
    assert len(claim.service_lines) == 1
    assert claim.service_lines[0].procedure == "PROC-A"


def test_parse_multi_claim_batch() -> None:
    remit = parse_835(_read("batch_mixed"))
    refs = [c.claim_ref for c in remit.claims]
    assert refs == ["CLM-2001", "CLM-2002", "CLM-2003"]
    # denial codes attach to the correct claim's service line
    assert remit.claims[0].all_denial_codes() == []
    assert remit.claims[1].all_denial_codes() == ["DR-DOC-MISSING"]
    assert remit.claims[2].all_denial_codes() == ["DR-CODE-INVALID"]


def test_claim_level_denial_code_before_svc() -> None:
    # denied_auth_absent puts the DRC before the SVC line -> claim-level
    remit = parse_835(_read("denied_auth_absent"))
    claim = remit.claims[0]
    assert claim.denial_codes == ["DR-AUTH-ABSENT"]
    assert claim.service_lines[0].denial_codes == []
    assert claim.all_denial_codes() == ["DR-AUTH-ABSENT"]


def test_multi_reason_mixes_claim_and_line_codes() -> None:
    remit = parse_835(_read("denied_multi_reason"))
    claim = remit.claims[0]
    assert claim.denial_codes == ["DR-DOC-MISSING"]
    assert claim.service_lines[0].denial_codes == ["DR-DUPLICATE"]
    assert claim.all_denial_codes() == ["DR-DOC-MISSING", "DR-DUPLICATE"]


def test_partial_payment_amounts() -> None:
    remit = parse_835(_read("partial_doc_missing"))
    claim = remit.claims[0]
    assert claim.status == "PART"
    assert claim.billed == Decimal("450.00")
    assert claim.paid == Decimal("180.00")
    assert claim.paid < claim.billed


@pytest.mark.parametrize("path", WELL_FORMED, ids=lambda p: p.stem)
def test_all_well_formed_parse_without_error(path: Path) -> None:
    remit = parse_835(path.read_text(encoding="utf-8"))
    assert len(remit.claims) >= 1
    for claim in remit.claims:
        assert claim.claim_ref
        assert claim.billed >= Decimal("0")


def test_unknown_segments_are_ignored_not_fatal() -> None:
    text = _read("paid_full_single").replace("~BPR", "~ZZZ*ignored*me~BPR")
    remit = parse_835(text)
    assert remit.claims[0].claim_ref == "CLM-1001"
