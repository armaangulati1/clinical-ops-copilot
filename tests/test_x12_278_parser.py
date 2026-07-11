"""Tests for the X12 278 request parser and Case mapping."""

from __future__ import annotations

from pathlib import Path

import pytest

from edi.encoder import encode_278_request
from edi.parser import parse_278_request
from edi.tokenizer import detect_delimiters, tokenize
from schemas.loader import load_case_file

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "edi" / "fixtures"
CASES = PROJECT_ROOT / "data" / "cases"

WELL_FORMED = sorted(
    p for p in FIXTURES.glob("*.278") if not p.name.startswith("malformed_")
)

# fixture stem -> source case id for round-trip checks
ROUND_TRIP_CASES = {
    "submit_ra_case001": "case-001",
    "submit_t2d_case017": "case-017",
    "submit_migraine_case037": "case-037",
    "requestinfo_ra_case007": "case-007",
    "requestinfo_t2d_case026": "case-026",
    "requestinfo_migraine_case039": "case-039",
    "denyrisk_ra_case012": "case-012",
    "denyrisk_migraine_case044": "case-044",
}


def test_fixtures_exist() -> None:
    assert len(WELL_FORMED) >= 8


def test_delimiters_detected_from_isa() -> None:
    text = (FIXTURES / "submit_ra_case001.278").read_text(encoding="utf-8")
    delimiters = detect_delimiters(text)
    assert delimiters.element == "*"
    assert delimiters.component == ">"
    assert delimiters.segment == "~"
    assert delimiters.repetition == "^"
    assert delimiters.distinct()


def test_tokenize_yields_expected_segments() -> None:
    text = (FIXTURES / "submit_ra_case001.278").read_text(encoding="utf-8")
    segments, _ = tokenize(text)
    ids = [seg.segment_id for seg in segments]
    for required in ("ISA", "GS", "ST", "BHT", "HL", "NM1", "UM", "HI", "SE", "IEA"):
        assert required in ids


def test_parse_maps_core_fields() -> None:
    text = (FIXTURES / "submit_ra_case001.278").read_text(encoding="utf-8")
    request = parse_278_request(text)
    assert request.submitter_reference == "case-001"
    assert request.drug == "adalimumab (Humira)"
    assert request.condition == "rheumatoid arthritis"
    assert request.request_category == "HS"
    assert request.diagnosis_codes == ["M06.9"]
    assert request.provider.npi == "1999999984"
    assert request.clinical_note.startswith("Outpatient rheumatology")


@pytest.mark.parametrize("stem,case_id", sorted(ROUND_TRIP_CASES.items()))
def test_round_trip_preserves_case(stem: str, case_id: str) -> None:
    original = load_case_file(CASES / f"{case_id}.json")
    parsed = parse_278_request((FIXTURES / f"{stem}.278").read_text(encoding="utf-8"))
    rebuilt = parsed.to_case()
    assert rebuilt.case_id == original.case_id
    assert rebuilt.clinical_note == original.clinical_note
    assert rebuilt.drug == original.drug
    assert rebuilt.condition == original.condition
    assert rebuilt.patient_id == original.patient_id


def test_patient_id_round_trips_when_present() -> None:
    text = (FIXTURES / "submit_ra_case001_with_patient_id.278").read_text(
        encoding="utf-8"
    )
    request = parse_278_request(text)
    assert request.patient.member_id == "synthea-9f2a1b"
    assert request.to_case().patient_id == "synthea-9f2a1b"


def test_patient_id_absent_maps_to_none() -> None:
    request = parse_278_request(
        (FIXTURES / "submit_ra_case001.278").read_text(encoding="utf-8")
    )
    assert request.patient.member_id is None
    assert request.to_case().patient_id is None


def test_note_chunked_across_multiple_msg_segments() -> None:
    long_case = load_case_file(CASES / "case-001.json")
    # case-001 note is < 264 chars; force multi-MSG by appending a long tail.
    padded = long_case.model_copy(
        update={"clinical_note": long_case.clinical_note + " " + "x" * 300}
    )
    parsed = parse_278_request(encode_278_request(padded))
    assert parsed.clinical_note == padded.clinical_note


def test_unknown_segments_are_ignored_not_fatal() -> None:
    text = (FIXTURES / "submit_ra_case001.278").read_text(encoding="utf-8")
    injected = text.replace("~UM*HS", "~ZZZ*ignored*me~UM*HS")
    request = parse_278_request(injected)
    assert request.submitter_reference == "case-001"
