"""Malformed 835 handling: clear structured errors, never a crash."""

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
from edi.x12_835 import parse_835

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "edi" / "fixtures" / "x835"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_empty_file_raises_empty_error() -> None:
    with pytest.raises(EmptyInterchangeError):
        parse_835(_read("malformed_empty.835"))


def test_whitespace_only_raises_empty_error() -> None:
    with pytest.raises(EmptyInterchangeError):
        parse_835("   \n  \t ")


def test_truncated_isa_raises_truncated_error() -> None:
    with pytest.raises(TruncatedInterchangeError):
        parse_835(_read("malformed_truncated_isa.835"))


def test_non_isa_start_raises_truncated_error() -> None:
    with pytest.raises(TruncatedInterchangeError):
        parse_835("GS*HP*A*B*20260101*1200*1*X*005010X221~")


def test_wrong_delimiters_raise_invalid_delimiter_error() -> None:
    with pytest.raises(InvalidDelimiterError):
        parse_835(_read("malformed_wrong_delimiters.835"))


def test_missing_clp_raises_missing_segment_error() -> None:
    with pytest.raises(MissingSegmentError) as exc:
        parse_835(_read("malformed_missing_clp.835"))
    assert exc.value.segment_id == "CLP"


def test_non_numeric_amount_raises_invalid_segment_error() -> None:
    good = _read("paid_full_single.835")
    broken = good.replace("CLP*CLM-1001*PAID*500.00", "CLP*CLM-1001*PAID*abc")
    with pytest.raises(InvalidSegmentError):
        parse_835(broken)


@pytest.mark.parametrize("bad_amount", ["NaN", "Infinity", "-Infinity", "sNaN"])
def test_non_finite_amount_raises_invalid_segment_error(bad_amount: str) -> None:
    # Decimal() silently parses NaN/Infinity; those are never valid amounts.
    good = _read("paid_full_single.835")
    broken = good.replace("CLP*CLM-1001*PAID*500.00", f"CLP*CLM-1001*PAID*{bad_amount}")
    with pytest.raises(InvalidSegmentError):
        parse_835(broken)


def test_all_malformed_errors_are_x12_parse_errors() -> None:
    for name in (
        "malformed_empty.835",
        "malformed_truncated_isa.835",
        "malformed_wrong_delimiters.835",
        "malformed_missing_clp.835",
    ):
        with pytest.raises(X12ParseError):
            parse_835(_read(name))
