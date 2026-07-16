"""Malformed-input tests for the HL7 v2 subset parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from hl7v2.errors import (
    EmptyMessageError,
    InvalidDelimiterError,
    InvalidSegmentError,
    MissingSegmentError,
    UnsupportedMessageTypeError,
    UnsupportedVersionError,
)
from hl7v2.parser import parse_message

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "hl7v2" / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_empty_message_raises() -> None:
    with pytest.raises(EmptyMessageError):
        parse_message(_read("malformed_empty.hl7"))


def test_missing_msh_raises() -> None:
    with pytest.raises(MissingSegmentError):
        parse_message(_read("malformed_missing_msh.hl7"))


def test_truncated_msh_raises() -> None:
    with pytest.raises(InvalidSegmentError):
        parse_message(_read("malformed_truncated_msh.hl7"))


def test_unsupported_message_type_raises() -> None:
    with pytest.raises(UnsupportedMessageTypeError):
        parse_message(_read("malformed_unsupported_type.hl7"))


def test_non_distinct_delimiters_raise() -> None:
    # Encoding characters repeat the field separator '|'.
    bad = "MSH|^~|&|ADMITSYS|RIVERBEND_GEN|X|Y|20270115|ORU^R01|C1|T|2.5.1\r"
    with pytest.raises(InvalidDelimiterError):
        parse_message(bad)


def test_unsupported_version_raises() -> None:
    bad = (
        "MSH|^~\\&|ADMITSYS|RIVERBEND_GEN|X|Y|20270115143000||"
        "ADT^A01^ADT_A01|C1|T|3.0\r"
        "PID|1||MRN-1^^^R^MR|"
    )
    with pytest.raises(UnsupportedVersionError):
        parse_message(bad)


def test_adt_without_pid_raises() -> None:
    bad = (
        "MSH|^~\\&|ADMITSYS|RIVERBEND_GEN|X|Y|20270115143000||"
        "ADT^A01^ADT_A01|C1|T|2.5.1\r"
        "EVN|A01|20270115143000\r"
    )
    with pytest.raises(MissingSegmentError):
        parse_message(bad)


def test_oru_without_obx_raises() -> None:
    bad = (
        "MSH|^~\\&|ADMITSYS|NORTHGATE_LAB|X|Y|20270115143000||"
        "ORU^R01^ORU_R01|C1|T|2.5.1\r"
        "PID|1||MRN-1^^^R^MR|\r"
        "OBR|1|||4548-4^A1c^LN\r"
    )
    with pytest.raises(MissingSegmentError):
        parse_message(bad)
