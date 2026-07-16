"""Tests for the HL7 v2 subset parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from hl7v2.parser import (
    detect_delimiters,
    parse_message,
    tokenize,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "hl7v2" / "fixtures"

WELL_FORMED = sorted(
    p for p in FIXTURES.glob("*.hl7") if not p.name.startswith("malformed_")
)


def _read(name: str) -> str:
    return (FIXTURES / f"{name}.hl7").read_text(encoding="utf-8")


def test_fixtures_exist() -> None:
    assert len(WELL_FORMED) >= 6


def test_delimiters_detected_from_msh() -> None:
    delimiters = detect_delimiters(_read("adt_a01_admit_basic"))
    assert delimiters.field == "|"
    assert delimiters.component == "^"
    assert delimiters.repetition == "~"
    assert delimiters.escape == "\\"
    assert delimiters.subcomponent == "&"
    assert delimiters.distinct()


def test_tokenize_parses_msh_envelope() -> None:
    _segments, header, _delims = tokenize(_read("adt_a01_admit_basic"))
    assert header.message_type == "ADT^A01"
    assert header.message_structure == "ADT_A01"
    assert header.version == "2.5.1"
    assert header.processing_id == "T"
    assert header.message_control_id == "MSG00001"


def test_parse_adt_core_fields() -> None:
    message = parse_message(_read("adt_a01_admit_basic"))
    assert message.message_type == "ADT^A01"
    assert message.event_type == "A01"
    assert message.patient is not None
    assert message.patient.primary_id == "MRN-0000123"
    assert message.patient.family_name == "HOLLOWAY"
    assert message.patient.given_name == "JOHN"
    assert message.patient.birth_date == "19850312"
    assert message.patient.administrative_sex == "M"
    assert message.visit is not None
    assert message.visit.patient_class == "I"
    assert message.visit.assigned_location == "3W"
    assert message.visit.visit_number == "VN-778001"


def test_parse_repeating_identifier_list() -> None:
    message = parse_message(_read("adt_a01_admit_repeat_ids"))
    assert message.patient is not None
    ids = [(i.id_value, i.identifier_type_code) for i in message.patient.identifiers]
    assert ids == [("MRN-0000456", "MR"), ("PI-0088231", "PI")]
    assert message.patient.primary_id == "MRN-0000456"


def test_parse_oru_typed_observations() -> None:
    message = parse_message(_read("oru_r01_a1c_bmi"))
    assert message.message_type == "ORU^R01"
    assert message.order is not None
    assert message.order.service_code == "4548-4"
    assert len(message.observations) == 2
    a1c = message.observations[0]
    assert a1c.value_type == "NM"
    assert a1c.identifier_code == "4548-4"
    assert a1c.identifier_coding_system == "LN"
    assert a1c.typed_value() == 8.1
    assert a1c.units == "%"
    assert a1c.result_status == "F"


def test_string_and_numeric_value_typing() -> None:
    message = parse_message(_read("oru_r01_mixed_types"))
    numeric, string = message.observations
    assert isinstance(numeric.typed_value(), float)
    assert numeric.typed_value() == 12.5
    assert isinstance(string.typed_value(), str)
    assert string.typed_value() == "No growth after 48 hours"


def test_escaped_delimiter_is_unescaped() -> None:
    message = parse_message(_read("oru_r01_escaped"))
    comment = message.observations[1]
    assert comment.value_raw == "Low result| recollect if clinically indicated"


def test_lf_terminated_message_parses_like_cr() -> None:
    text = _read("adt_a01_admit_basic")
    lf_text = text.replace("\r", "\n")
    assert parse_message(lf_text) == parse_message(text)


@pytest.mark.parametrize("fixture", [p.stem for p in WELL_FORMED])
def test_all_well_formed_fixtures_parse(fixture: str) -> None:
    message = parse_message(_read(fixture))
    assert message.message_type in {"ADT^A01", "ORU^R01"}
    assert message.patient is not None
