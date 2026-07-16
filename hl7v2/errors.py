"""Structured errors for HL7 v2 parsing.

Every failure mode raises a subclass of :class:`HL7ParseError` with enough
context (segment id where known) for a caller to log a clear, PHI-safe
diagnostic instead of crashing on a malformed message. Mirrors the structured
error surface of the X12 278 layer (``edi/errors.py``).
"""

from __future__ import annotations


class HL7ParseError(ValueError):
    """Base class for all HL7 v2 parse failures."""

    def __init__(self, message: str, *, segment_id: str | None = None) -> None:
        self.segment_id = segment_id
        if segment_id is not None:
            message = f"[{segment_id}] {message}"
        super().__init__(message)


class EmptyMessageError(HL7ParseError):
    """Raised when the input is empty or whitespace-only."""


class MissingSegmentError(HL7ParseError):
    """Raised when a required segment (e.g. MSH, PID) is absent."""


class InvalidDelimiterError(HL7ParseError):
    """Raised when encoding characters cannot be resolved from the MSH header."""


class InvalidSegmentError(HL7ParseError):
    """Raised when a present segment is structurally malformed."""


class UnsupportedMessageTypeError(HL7ParseError):
    """Raised when MSH-9 is outside this subset (only ADT^A01 / ORU^R01)."""


class UnsupportedVersionError(HL7ParseError):
    """Raised when MSH-12 is not an HL7 v2.x version string."""
