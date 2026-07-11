"""Malformed-EDI handling: clear structured errors, never a crash."""

from __future__ import annotations

from pathlib import Path

import pytest

from edi.errors import (
    EmptyInterchangeError,
    InvalidDelimiterError,
    MissingSegmentError,
    TruncatedInterchangeError,
    X12ParseError,
)
from edi.parser import parse_278_request

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "edi" / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_empty_file_raises_empty_error() -> None:
    with pytest.raises(EmptyInterchangeError):
        parse_278_request(_read("malformed_empty.278"))


def test_whitespace_only_raises_empty_error() -> None:
    with pytest.raises(EmptyInterchangeError):
        parse_278_request("   \n  \t ")


def test_truncated_isa_raises_truncated_error() -> None:
    with pytest.raises(TruncatedInterchangeError):
        parse_278_request(_read("malformed_truncated_isa.278"))


def test_non_isa_start_raises_truncated_error() -> None:
    with pytest.raises(TruncatedInterchangeError):
        parse_278_request("GS*HI*A*B*20260101*1200*1*X*005010X217~")


def test_wrong_delimiters_raise_invalid_delimiter_error() -> None:
    with pytest.raises(InvalidDelimiterError):
        parse_278_request(_read("malformed_wrong_delimiters.278"))


def test_missing_um_raises_missing_segment_error() -> None:
    with pytest.raises(MissingSegmentError) as exc:
        parse_278_request(_read("malformed_missing_um.278"))
    assert exc.value.segment_id == "UM"


def test_all_malformed_errors_are_x12_parse_errors() -> None:
    for name in (
        "malformed_empty.278",
        "malformed_truncated_isa.278",
        "malformed_wrong_delimiters.278",
        "malformed_missing_um.278",
    ):
        with pytest.raises(X12ParseError):
            parse_278_request(_read(name))
