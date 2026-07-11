"""ISA-driven tokenizer for X12 interchanges.

X12 does not fix its delimiters in the standard; every interchange declares its
own in the fixed-width ISA header. This module bootstraps the four delimiters
from that header by position (the canonical X12 approach) and then splits the
interchange into segments, elements, and components. No escaping is performed,
matching X12 semantics: delimiter characters must not appear inside data.
"""

from __future__ import annotations

from dataclasses import dataclass

from edi.errors import (
    EmptyInterchangeError,
    InvalidDelimiterError,
    TruncatedInterchangeError,
)

# Fixed character offsets inside a well-formed 005010 ISA segment.
_ISA_MIN_LEN = 106
_ELEMENT_SEP_INDEX = 3
_REPETITION_SEP_INDEX = 82
_COMPONENT_SEP_INDEX = 104
_SEGMENT_TERMINATOR_INDEX = 105


@dataclass(frozen=True)
class Delimiters:
    """The four X12 delimiters resolved from an ISA header."""

    element: str
    component: str
    repetition: str
    segment: str

    def distinct(self) -> bool:
        chars = {self.element, self.component, self.repetition, self.segment}
        return len(chars) == 4


@dataclass(frozen=True)
class Segment:
    """A single tokenized segment: its id plus raw element strings."""

    segment_id: str
    elements: list[str]

    def element(self, index: int, default: str = "") -> str:
        """Return the 1-based element (X12 convention) or a default."""
        pos = index - 1
        if 0 <= pos < len(self.elements):
            return self.elements[pos]
        return default


def detect_delimiters(interchange: str) -> Delimiters:
    """Resolve delimiters from the ISA header by fixed position."""
    if not interchange.strip():
        raise EmptyInterchangeError("interchange is empty")
    if not interchange.startswith("ISA"):
        raise TruncatedInterchangeError(
            "interchange does not start with an ISA header",
            segment_id="ISA",
        )
    if len(interchange) < _ISA_MIN_LEN:
        raise TruncatedInterchangeError(
            f"ISA header requires at least {_ISA_MIN_LEN} characters, "
            f"got {len(interchange)}",
            segment_id="ISA",
        )

    delimiters = Delimiters(
        element=interchange[_ELEMENT_SEP_INDEX],
        repetition=interchange[_REPETITION_SEP_INDEX],
        component=interchange[_COMPONENT_SEP_INDEX],
        segment=interchange[_SEGMENT_TERMINATOR_INDEX],
    )
    if not delimiters.distinct():
        raise InvalidDelimiterError(
            "ISA header declares non-distinct delimiters",
            segment_id="ISA",
        )
    return delimiters


def tokenize(interchange: str) -> tuple[list[Segment], Delimiters]:
    """Split an interchange into segments using ISA-declared delimiters."""
    delimiters = detect_delimiters(interchange)

    # Ignore any trailing whitespace/newlines carriers use between segments.
    raw_segments = [
        chunk.strip("\r\n")
        for chunk in interchange.split(delimiters.segment)
        if chunk.strip("\r\n")
    ]

    segments: list[Segment] = []
    for raw in raw_segments:
        elements = raw.split(delimiters.element)
        segment_id = elements[0]
        segments.append(Segment(segment_id=segment_id, elements=elements[1:]))
    return segments, delimiters


def split_components(value: str, delimiters: Delimiters) -> list[str]:
    """Split an element into its component parts."""
    return value.split(delimiters.component)
