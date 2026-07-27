"""Tests for the self-authored X12 270 eligibility-inquiry parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from edi.errors import InvalidSegmentError
from edi.tokenizer import detect_delimiters, tokenize
from edi.x12_270 import parse_270_inquiry

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "edi" / "fixtures" / "x270"

WELL_FORMED = sorted(
    p for p in FIXTURES.glob("*.270") if not p.name.startswith("malformed_")
)


def _read(stem: str) -> str:
    return (FIXTURES / f"{stem}.270").read_text(encoding="utf-8")


def test_fixtures_exist() -> None:
    assert len(WELL_FORMED) >= 8


def test_delimiters_detected_from_isa() -> None:
    delimiters = detect_delimiters(_read("active_medical_single"))
    assert delimiters.element == "*"
    assert delimiters.component == ">"
    assert delimiters.segment == "~"
    assert delimiters.repetition == "^"
    assert delimiters.distinct()


def test_tokenize_yields_expected_segments() -> None:
    segments, _ = tokenize(_read("multi_service_types"))
    ids = [seg.segment_id for seg in segments]
    for required in ("ISA", "GS", "ST", "BHT", "HL", "NM1", "DMG", "EQ", "SE", "IEA"):
        assert required in ids


def test_parse_single_service_type_inquiry() -> None:
    inquiry = parse_270_inquiry(_read("active_medical_single"))
    assert inquiry.transaction_control == "0001"
    assert inquiry.submitter_reference == "ELG-0001"
    assert inquiry.payer_name == "SYNTHETIC PAYER"
    assert inquiry.service_types == ["SRV-MEDICAL"]
    assert inquiry.service_date == "20260727"


def test_parse_subscriber_identity_and_demographics() -> None:
    inquiry = parse_270_inquiry(_read("active_medical_single"))
    assert inquiry.subscriber.last_name == "ALPHA"
    assert inquiry.subscriber.first_name == "ANA"
    assert inquiry.subscriber.member_id == "MBR-1001"
    assert inquiry.subscriber.birth_date == "19850214"
    assert inquiry.subscriber.gender == "U"


def test_parse_requesting_provider_npi() -> None:
    inquiry = parse_270_inquiry(_read("active_medical_single"))
    assert inquiry.provider.last_name == "PROVIDER"
    assert inquiry.provider.npi == "1999999984"


def test_multiple_eq_segments_collect_in_document_order() -> None:
    inquiry = parse_270_inquiry(_read("multi_service_types"))
    assert inquiry.service_types == ["SRV-MEDICAL", "SRV-SPECIALIST", "SRV-IMAGING"]


@pytest.mark.parametrize("path", WELL_FORMED, ids=lambda p: p.stem)
def test_all_well_formed_parse_without_error(path: Path) -> None:
    inquiry = parse_270_inquiry(path.read_text(encoding="utf-8"))
    assert inquiry.submitter_reference
    assert inquiry.service_types
    for service_type in inquiry.service_types:
        # every fixture must use the self-authored vocabulary, never a real code
        assert service_type.startswith("SRV-")


def test_unknown_segments_are_ignored_not_fatal() -> None:
    text = _read("active_medical_single").replace("~DTP", "~ZZZ*ignored*me~DTP")
    inquiry = parse_270_inquiry(text)
    assert inquiry.subscriber.member_id == "MBR-1001"


def test_member_id_requires_mi_qualifier() -> None:
    # An NM1*IL carrying some other id qualifier yields no member key.
    text = _read("active_medical_single").replace("*MI*MBR-1001", "*ZZ*MBR-1001")
    inquiry = parse_270_inquiry(text)
    assert inquiry.subscriber.member_id is None
    with pytest.raises(InvalidSegmentError):
        inquiry.require_member_key()


def test_require_member_key_returns_the_id_when_present() -> None:
    inquiry = parse_270_inquiry(_read("deductible_unmet"))
    assert inquiry.require_member_key() == "MBR-1002"


def test_non_d8_dmg_format_is_ignored() -> None:
    # Only the CCYYMMDD (D8) demographics form is modeled in this subset.
    text = _read("active_medical_single").replace("DMG*D8*", "DMG*D9*")
    inquiry = parse_270_inquiry(text)
    assert inquiry.subscriber.birth_date is None
