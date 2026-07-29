"""X12 276 claim-status inquiry parser (self-authored demo subset).

A hand-rolled parser for a *self-authored* subset of the X12 276 health-care
claim status request. It reads a synthetic 276-shaped interchange into a typed
:class:`ClaimStatusInquiry` so the deterministic responder in
``edi.claim_status_277`` can emit a 277-shaped response from the repo's own
synthetic claim store.

Scope and honesty (see edi/README.md for the full note):

* **Self-authored subset**, not the real 005010X212 implementation guide. Only
  the envelope/inquiry shapes this demo needs are modeled; everything else is
  tolerated and ignored, not validated.
* **No real claim-status code content.** Real 277 responses report status in
  ``STC`` segments using externally maintained claim status category and claim
  status code lists. This demo deliberately does NOT reproduce any of that: it
  carries status in an invented ``ZCSI`` segment using a small self-authored
  ``CS-*`` vocabulary defined in ``edi.claim_status_277``. That carrier ID is
  four characters, and an X12 segment ID is two or three, so it cannot collide
  with a real segment (see :mod:`edi.invented_segments`).
* **Claim references travel in ``REF*ZZ`` carriers** tagged ``CLAIM`` in
  ``REF03``, the same mutually-defined pattern the 278 layer uses for its demo
  lookup keys, so no real reference-identification qualifier semantics are
  implied.
* **Synthetic data only.** Fixtures are self-authored; no PHI, no real payer
  traffic, not affiliated with any company or product.
* This simulates the payer side for demo purposes. It is not HIPAA-certified EDI
  tooling, it is not a clearinghouse integration, and it reports no real claim
  adjudication.

The tokenizer, delimiter bootstrap, and structured error hierarchy are shared
with the existing 278 and 835 layers (``edi.tokenizer`` / ``edi.errors``).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from edi.errors import InvalidSegmentError, MissingSegmentError
from edi.tokenizer import Segment, tokenize

# Segments this self-authored subset understands. Others are ignored, not errors.
SUPPORTED_SEGMENTS = frozenset(
    {
        "ISA",
        "GS",
        "ST",
        "BHT",
        "HL",
        "NM1",
        "TRN",
        "REF",
        "DTP",
        "DMG",
        "SE",
        "GE",
        "IEA",
    }
)

# Required for a usable inquiry in this subset.
_REQUIRED_SEGMENTS = ("ST", "BHT", "REF")

# REF*ZZ ... CLAIM is the demo carrier for the claim reference being asked about.
_CLAIM_REF_QUALIFIER = "ZZ"
_CLAIM_REF_TAG = "CLAIM"
_SERVICE_DATE_QUALIFIER = "472"


@dataclass
class InquiringProvider:
    """Provider asking about the claim (NM1*1P)."""

    last_name: str = ""
    first_name: str = ""
    npi: str | None = None


@dataclass
class InquirySubscriber:
    """Subscriber the claims belong to (NM1*IL)."""

    last_name: str = ""
    first_name: str = ""
    member_id: str | None = None


@dataclass
class ClaimStatusInquiry:
    """Intermediate structured view of a parsed 276 inquiry (subset)."""

    transaction_control: str = ""
    submitter_reference: str = ""  # BHT03
    trace_number: str = ""  # TRN02
    payer_name: str = ""
    provider: InquiringProvider = field(default_factory=InquiringProvider)
    subscriber: InquirySubscriber = field(default_factory=InquirySubscriber)
    claim_refs: list[str] = field(default_factory=list)  # REF*ZZ ... CLAIM
    service_date: str | None = None  # DTP*472


def parse_276_inquiry(interchange: str) -> ClaimStatusInquiry:
    """Parse a 276 claim-status inquiry (subset) into a ClaimStatusInquiry."""
    segments, _delimiters = tokenize(interchange)
    _require_segments(segments)

    inquiry = ClaimStatusInquiry()

    for seg in segments:
        sid = seg.segment_id
        if sid == "ST":
            inquiry.transaction_control = seg.element(2)
        elif sid == "BHT":
            inquiry.submitter_reference = seg.element(3)
        elif sid == "TRN":
            inquiry.trace_number = seg.element(2)
        elif sid == "NM1":
            _apply_nm1(seg, inquiry)
        elif sid == "REF":
            _apply_ref(seg, inquiry)
        elif sid == "DTP" and seg.element(1) == _SERVICE_DATE_QUALIFIER:
            inquiry.service_date = seg.element(3) or None

    if not inquiry.claim_refs:
        # A REF segment exists (the id check passed) but none of them carried a
        # claim reference, so there is nothing to look up. Fail loudly.
        raise MissingSegmentError(
            "no REF*ZZ claim reference carrier (REF03 tag 'CLAIM') found",
            segment_id="REF",
        )
    return inquiry


def _require_segments(segments: list[Segment]) -> None:
    present = {seg.segment_id for seg in segments}
    for required in _REQUIRED_SEGMENTS:
        if required not in present:
            raise MissingSegmentError(
                f"required segment {required} not found in interchange",
                segment_id=required,
            )


def _apply_nm1(seg: Segment, inquiry: ClaimStatusInquiry) -> None:
    entity = seg.element(1)
    id_qualifier = seg.element(8)
    id_value = seg.element(9)
    if entity == "PR":
        inquiry.payer_name = seg.element(3)
    elif entity == "1P":
        inquiry.provider = InquiringProvider(
            last_name=seg.element(3),
            first_name=seg.element(4),
            npi=id_value if id_qualifier == "XX" and id_value else None,
        )
    elif entity == "IL":
        inquiry.subscriber = InquirySubscriber(
            last_name=seg.element(3),
            first_name=seg.element(4),
            member_id=id_value if id_qualifier == "MI" and id_value else None,
        )


def _apply_ref(seg: Segment, inquiry: ClaimStatusInquiry) -> None:
    """Collect claim references from REF*ZZ carriers tagged CLAIM in REF03."""
    if seg.element(1) != _CLAIM_REF_QUALIFIER or seg.element(3) != _CLAIM_REF_TAG:
        return
    claim_ref = seg.element(2)
    if not claim_ref:
        raise InvalidSegmentError(
            "REF*ZZ CLAIM carrier is missing a claim reference (REF02)",
            segment_id="REF",
        )
    inquiry.claim_refs.append(claim_ref)
