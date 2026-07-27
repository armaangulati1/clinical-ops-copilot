"""X12 EDI demo layers (subset scope, synthetic data only).

Four hand-rolled, demo-scoped X12 layers over the shared tokenizer/error core:

* **278** health-care-services-review: a REQUEST parser + RESPONSE generator wired
  onto the prior-auth agent (005010X217 subset).
* **835** remittance/denial: a REQUEST parser (self-authored subset) plus a
  deterministic denial-triage layer over an invented ``DR-*`` denial-code system
  (NOT real CARC/RARC/CAS content).
* **270/271** eligibility: an inquiry parser plus a deterministic responder over a
  synthetic coverage table, using invented ``SRV-*``/``EB-*``/``RJ-*``
  vocabularies (NOT real service type, benefit, or reject code lists).
* **276/277** claim status: an inquiry parser plus a deterministic responder over
  a synthetic claim store, using an invented ``CS-*`` vocabulary (NOT real claim
  status category or claim status codes).

Synthetic data only; not HIPAA-certified EDI tooling, and no clearinghouse
integration. The 271 and 277 responders simulate the payer side for demo output.
See edi/README.md for the supported segment subsets, the decision-to-HCR mapping,
the triage rules, and the coverage/claim tables.
"""

from __future__ import annotations

from edi.claim_status_277 import (
    CLAIM_STORE,
    ClaimRejectReason,
    ClaimStatus,
    ClaimStatusResponse,
    ClaimStatusRow,
    StoredClaim,
    answer_276,
    build_277_response,
    resolve_claim_status,
)
from edi.decision_map import DECISION_TO_HCR, HcrMapping, map_decision
from edi.denial_triage import (
    DENIAL_CODE_TABLE,
    ClaimTriage,
    DenialRule,
    TriageRecommendation,
    triage_claim,
    triage_remittance,
)
from edi.eligibility_271 import (
    COVERAGE_TABLE,
    SERVICE_TYPES,
    BenefitOutcome,
    BenefitRow,
    EligibilityResponse,
    MemberCoverage,
    RejectReason,
    ServiceBenefit,
    answer_270,
    build_271_response,
    resolve_eligibility,
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
from edi.x12_270 import (
    EligibilityInquiry,
    RequestingProvider,
    Subscriber,
    parse_270_inquiry,
)
from edi.x12_276 import (
    ClaimStatusInquiry,
    InquiringProvider,
    InquirySubscriber,
    parse_276_inquiry,
)
from edi.x12_835 import (
    ClaimPayment,
    RemittanceAdvice,
    ServiceLine,
    parse_835,
)

__all__ = [
    "BenefitOutcome",
    "BenefitRow",
    "CLAIM_STORE",
    "COVERAGE_TABLE",
    "ClaimPayment",
    "ClaimRejectReason",
    "ClaimStatus",
    "ClaimStatusInquiry",
    "ClaimStatusResponse",
    "ClaimStatusRow",
    "ClaimTriage",
    "DECISION_TO_HCR",
    "DENIAL_CODE_TABLE",
    "Delimiters",
    "DenialRule",
    "EligibilityInquiry",
    "EligibilityResponse",
    "EmptyInterchangeError",
    "HcrMapping",
    "InquiringProvider",
    "InquirySubscriber",
    "InvalidDelimiterError",
    "InvalidSegmentError",
    "MemberCoverage",
    "MissingSegmentError",
    "Patient",
    "Provider",
    "RejectReason",
    "RemittanceAdvice",
    "Request278",
    "RequestingProvider",
    "SERVICE_TYPES",
    "Segment",
    "ServiceBenefit",
    "ServiceLine",
    "StoredClaim",
    "Subscriber",
    "TriageRecommendation",
    "TruncatedInterchangeError",
    "X12ParseError",
    "answer_270",
    "answer_276",
    "build_271_response",
    "build_277_response",
    "build_278_response",
    "detect_delimiters",
    "encode_278_request",
    "map_decision",
    "parse_270_inquiry",
    "parse_276_inquiry",
    "parse_278_request",
    "parse_835",
    "resolve_claim_status",
    "resolve_eligibility",
    "tokenize",
    "triage_claim",
    "triage_remittance",
]
