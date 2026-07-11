"""Structured errors for X12 278 parsing.

Every failure mode raises a subclass of :class:`X12ParseError` with enough
context (segment id, position, offending value) for a caller to log a clear,
PHI-safe diagnostic instead of crashing on malformed EDI.
"""

from __future__ import annotations


class X12ParseError(ValueError):
    """Base class for all X12 278 parse failures."""

    def __init__(self, message: str, *, segment_id: str | None = None) -> None:
        self.segment_id = segment_id
        if segment_id is not None:
            message = f"[{segment_id}] {message}"
        super().__init__(message)


class EmptyInterchangeError(X12ParseError):
    """Raised when the input is empty or whitespace-only."""


class TruncatedInterchangeError(X12ParseError):
    """Raised when the ISA header or the interchange envelope is incomplete."""


class InvalidDelimiterError(X12ParseError):
    """Raised when delimiters cannot be resolved from the ISA header."""


class MissingSegmentError(X12ParseError):
    """Raised when a required segment (e.g. UM, ST, BHT) is absent."""


class InvalidSegmentError(X12ParseError):
    """Raised when a present segment is structurally malformed."""
