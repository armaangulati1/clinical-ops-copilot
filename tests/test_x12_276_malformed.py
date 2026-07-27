"""Malformed 276 handling: clear structured errors, never a crash."""

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
from edi.x12_276 import parse_276_inquiry

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "edi" / "fixtures" / "x276"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_empty_file_raises_empty_error() -> None:
    with pytest.raises(EmptyInterchangeError):
        parse_276_inquiry(_read("malformed_empty.276"))


def test_whitespace_only_raises_empty_error() -> None:
    with pytest.raises(EmptyInterchangeError):
        parse_276_inquiry("   \n  \t ")


def test_truncated_isa_raises_truncated_error() -> None:
    with pytest.raises(TruncatedInterchangeError):
        parse_276_inquiry(_read("malformed_truncated_isa.276"))


def test_non_isa_start_raises_truncated_error() -> None:
    with pytest.raises(TruncatedInterchangeError):
        parse_276_inquiry("GS*HR*A*B*20260727*1200*1*X*DEMOSUBSET~")


def test_wrong_delimiters_raise_invalid_delimiter_error() -> None:
    with pytest.raises(InvalidDelimiterError):
        parse_276_inquiry(_read("malformed_wrong_delimiters.276"))


def test_missing_ref_raises_missing_segment_error() -> None:
    with pytest.raises(MissingSegmentError) as exc:
        parse_276_inquiry(_read("malformed_missing_ref.276"))
    assert exc.value.segment_id == "REF"


def test_ref_present_but_no_claim_carrier_still_raises() -> None:
    # The segment-id check passes, so the parser must also assert that at least
    # one REF actually carried a claim reference.
    text = _read("single_paid.276").replace("*CLM-1001*CLAIM", "*CLM-1001*OTHER")
    with pytest.raises(MissingSegmentError) as exc:
        parse_276_inquiry(text)
    assert exc.value.segment_id == "REF"


def test_missing_st_raises_missing_segment_error() -> None:
    text = _read("single_paid.276").replace("ST*276*0001~", "")
    with pytest.raises(MissingSegmentError) as exc:
        parse_276_inquiry(text)
    assert exc.value.segment_id == "ST"


def test_empty_claim_reference_raises_invalid_segment_error() -> None:
    text = _read("single_paid.276").replace("REF*ZZ*CLM-1001*CLAIM", "REF*ZZ**CLAIM")
    with pytest.raises(InvalidSegmentError) as exc:
        parse_276_inquiry(text)
    assert exc.value.segment_id == "REF"


@pytest.mark.parametrize(
    "name",
    [
        "malformed_empty.276",
        "malformed_truncated_isa.276",
        "malformed_wrong_delimiters.276",
        "malformed_missing_ref.276",
    ],
)
def test_all_malformed_errors_are_x12_parse_errors(name: str) -> None:
    with pytest.raises(X12ParseError):
        parse_276_inquiry(_read(name))
