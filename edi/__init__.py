"""X12 EDI demo layers (subset scope, synthetic data only).

Two hand-rolled, demo-scoped X12 layers over the shared tokenizer/error core:

* **278** health-care-services-review: a REQUEST parser + RESPONSE generator wired
  onto the prior-auth agent (005010X217 subset).
* **835** remittance/denial: a REQUEST parser (self-authored subset) plus a
  deterministic denial-triage layer over an invented ``DR-*`` denial-code system
  (NOT real CARC/RARC/CAS content).

Synthetic data only; not HIPAA-certified EDI tooling. See edi/README.md for the
supported segment subsets, the decision-to-HCR mapping, and the triage rules.
"""

from __future__ import annotations

from edi.decision_map import DECISION_TO_HCR, HcrMapping, map_decision
from edi.denial_triage import (
    DENIAL_CODE_TABLE,
    ClaimTriage,
    DenialRule,
    TriageRecommendation,
    triage_claim,
    triage_remittance,
)
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
from edi.x12_835 import (
    ClaimPayment,
    RemittanceAdvice,
    ServiceLine,
    parse_835,
)

__all__ = [
    "DECISION_TO_HCR",
    "DENIAL_CODE_TABLE",
    "ClaimPayment",
    "ClaimTriage",
    "Delimiters",
    "DenialRule",
    "EmptyInterchangeError",
    "HcrMapping",
    "InvalidDelimiterError",
    "InvalidSegmentError",
    "MissingSegmentError",
    "Patient",
    "Provider",
    "RemittanceAdvice",
    "Request278",
    "Segment",
    "ServiceLine",
    "TriageRecommendation",
    "TruncatedInterchangeError",
    "X12ParseError",
    "build_278_response",
    "detect_delimiters",
    "encode_278_request",
    "map_decision",
    "parse_278_request",
    "parse_835",
    "tokenize",
    "triage_claim",
    "triage_remittance",
]
