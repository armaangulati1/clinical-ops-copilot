"""Malformed 270 handling: clear structured errors, never a crash."""

from __future__ import annotations

from pathlib import Path

import pytest

from edi.errors import (
    EmptyInterchangeError,
    InvalidDelimiterError,
    InvalidSegmentError,
    MissingSegmentError,
    TruncatedInterchangeError,
    X12ParseError,
)
from edi.x12_270 import parse_270_inquiry

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "edi" / "fixtures" / "x270"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_empty_file_raises_empty_error() -> None:
    with pytest.raises(EmptyInterchangeError):
        parse_270_inquiry(_read("malformed_empty.270"))


def test_whitespace_only_raises_empty_error() -> None:
    with pytest.raises(EmptyInterchangeError):
        parse_270_inquiry("   \n  \t ")


def test_truncated_isa_raises_truncated_error() -> None:
    with pytest.raises(TruncatedInterchangeError):
        parse_270_inquiry(_read("malformed_truncated_isa.270"))


def test_non_isa_start_raises_truncated_error() -> None:
    with pytest.raises(TruncatedInterchangeError):
        parse_270_inquiry("GS*HS*A*B*20260727*1200*1*X*DEMOSUBSET~")


def test_wrong_delimiters_raise_invalid_delimiter_error() -> None:
    with pytest.raises(InvalidDelimiterError):
        parse_270_inquiry(_read("malformed_wrong_delimiters.270"))


def test_missing_eq_raises_missing_segment_error() -> None:
    with pytest.raises(MissingSegmentError) as exc:
        parse_270_inquiry(_read("malformed_missing_eq.270"))
    assert exc.value.segment_id == "EQ"


def test_missing_bht_raises_missing_segment_error() -> None:
    text = _read("active_medical_single.270")
    broken = text.replace("BHT*0022*13*ELG-0001*20260727*1200~", "")
    with pytest.raises(MissingSegmentError) as exc:
        parse_270_inquiry(broken)
    assert exc.value.segment_id == "BHT"


def test_empty_eq_service_type_raises_invalid_segment_error() -> None:
    text = _read("active_medical_single.270").replace("EQ*SRV-MEDICAL", "EQ*")
    with pytest.raises(InvalidSegmentError) as exc:
        parse_270_inquiry(text)
    assert exc.value.segment_id == "EQ"


@pytest.mark.parametrize(
    "name",
    [
        "malformed_empty.270",
        "malformed_truncated_isa.270",
        "malformed_wrong_delimiters.270",
        "malformed_missing_eq.270",
    ],
)
def test_all_malformed_errors_are_x12_parse_errors(name: str) -> None:
    with pytest.raises(X12ParseError):
        parse_270_inquiry(_read(name))
