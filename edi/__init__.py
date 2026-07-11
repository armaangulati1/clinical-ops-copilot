"""X12 278 prior-authorization layer (005010X217 subset, demo scope).

A hand-rolled X12 278 health-care-services-review REQUEST parser and RESPONSE
generator wired onto the existing prior-auth agent. Synthetic data only; not
HIPAA-certified EDI tooling. See edi/README.md for the supported segment subset
and the decision-to-HCR mapping.
"""

from __future__ import annotations

from edi.decision_map import DECISION_TO_HCR, HcrMapping, map_decision
from edi.encoder import encode_278_request
from edi.errors import (
    EmptyInterchangeError,
    InvalidDelimiterError,
    InvalidSegmentError,
    MissingSegmentError,
    TruncatedInterchangeError,
    X12ParseError,
)
from edi.generator import build_278_response
from edi.parser import Patient, Provider, Request278, parse_278_request
from edi.tokenizer import Delimiters, Segment, detect_delimiters, tokenize

__all__ = [
    "DECISION_TO_HCR",
    "Delimiters",
    "EmptyInterchangeError",
    "HcrMapping",
    "InvalidDelimiterError",
    "InvalidSegmentError",
    "MissingSegmentError",
    "Patient",
    "Provider",
    "Request278",
    "Segment",
    "TruncatedInterchangeError",
    "X12ParseError",
    "build_278_response",
    "detect_delimiters",
    "encode_278_request",
    "map_decision",
    "parse_278_request",
    "tokenize",
]
