"""Tests for the self-authored X12 276 claim-status inquiry parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from edi.tokenizer import detect_delimiters, tokenize
from edi.x12_276 import parse_276_inquiry

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "edi" / "fixtures" / "x276"

WELL_FORMED = sorted(
    p for p in FIXTURES.glob("*.276") if not p.name.startswith("malformed_")
)


def _read(stem: str) -> str:
    return (FIXTURES / f"{stem}.276").read_text(encoding="utf-8")


def test_fixtures_exist() -> None:
    assert len(WELL_FORMED) >= 7


def test_delimiters_detected_from_isa() -> None:
    delimiters = detect_delimiters(_read("single_paid"))
    assert delimiters.element == "*"
    assert delimiters.component == ">"
    assert delimiters.segment == "~"
    assert delimiters.repetition == "^"
    assert delimiters.distinct()


def test_tokenize_yields_expected_segments() -> None:
    segments, _ = tokenize(_read("batch_three"))
    ids = [seg.segment_id for seg in segments]
    for required in ("ISA", "GS", "ST", "BHT", "TRN", "HL", "NM1", "REF", "SE", "IEA"):
        assert required in ids


def test_parse_single_claim_inquiry() -> None:
    inquiry = parse_276_inquiry(_read("single_paid"))
    assert inquiry.transaction_control == "0001"
    assert inquiry.submitter_reference == "STA-0001"
    assert inquiry.trace_number == "TRACE-S001"
    assert inquiry.payer_name == "SYNTHETIC PAYER"
    assert inquiry.claim_refs == ["CLM-1001"]
    assert inquiry.service_date == "20260701"


def test_parse_subscriber_and_provider_identity() -> None:
    inquiry = parse_276_inquiry(_read("single_paid"))
    assert inquiry.subscriber.last_name == "ALPHA"
    assert inquiry.subscriber.member_id == "MBR-1001"
    assert inquiry.provider.npi == "1999999984"


def test_multiple_claim_refs_collect_in_document_order() -> None:
    inquiry = parse_276_inquiry(_read("batch_three"))
    assert inquiry.claim_refs == ["CLM-2001", "CLM-2002", "CLM-2003"]


@pytest.mark.parametrize("path", WELL_FORMED, ids=lambda p: p.stem)
def test_all_well_formed_parse_without_error(path: Path) -> None:
    inquiry = parse_276_inquiry(path.read_text(encoding="utf-8"))
    assert inquiry.submitter_reference
    assert inquiry.claim_refs
    for claim_ref in inquiry.claim_refs:
        assert claim_ref.startswith("CLM-")


def test_unknown_segments_are_ignored_not_fatal() -> None:
    text = _read("single_paid").replace("~DTP", "~ZZZ*ignored*me~DTP")
    inquiry = parse_276_inquiry(text)
    assert inquiry.claim_refs == ["CLM-1001"]


def test_ref_with_a_different_tag_is_not_a_claim_carrier() -> None:
    # Only REF*ZZ carriers tagged CLAIM in REF03 are read as claim references.
    text = _read("batch_three").replace("*CLM-2001*CLAIM", "*CLM-2001*OTHER")
    inquiry = parse_276_inquiry(text)
    assert inquiry.claim_refs == ["CLM-2002", "CLM-2003"]


def test_ref_with_a_different_qualifier_is_ignored() -> None:
    text = _read("batch_three").replace(
        "REF*ZZ*CLM-2003*CLAIM", "REF*1L*CLM-2003*CLAIM"
    )
    inquiry = parse_276_inquiry(text)
    assert inquiry.claim_refs == ["CLM-2001", "CLM-2002"]
